import socket
import threading
from threading import Thread, Lock
import logging
import traceback

import micropython_time as time
from typing import List, Optional
from socket import error as SocketError
import errno
from LoRaNetworking.LoRaTCP import LoRaTCP
from LoRaNetworking.LoRaNetworking import LoRaNetworking

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('LoRaGateway')

class ConnectionBridge(Thread):
    CONNECTIONS = list()
    CONNECTIONS_LOCK = Lock()
    
    def __init__(self, lora_socket: LoRaTCP, peer):
        super().__init__(name=f"ConnectionBridge-{peer}")
        self.daemon = True  # Daemon thread for proper shutdown
        
        try:
            logger.info(f"Creating new connection bridge for peer: {peer}")
            address, port = peer
            self.peer = peer
            self.lora_sock = lora_socket
            self.sock: Optional[socket.socket] = None
            self.shutdown_event = threading.Event()
            self.is_running = False
            
            # Configure LoRa socket
            self.lora_sock.setblocking(False)
            self.lora_sock.settimeout(0.5)
            
            # Create and configure TCP socket
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5.0)  # Longer timeout for connection
            self.sock.connect((address, port))
            self.sock.settimeout(0.5)  # Shorter timeout for operations
            
            # Add to connections list thread-safely
            with ConnectionBridge.CONNECTIONS_LOCK:
                ConnectionBridge.CONNECTIONS.append(self)
                
            logger.info(f"Connection bridge established: {peer}")
            
        except Exception as e:
            logger.error(f"Failed to create connection bridge for {peer}: {e}")
            self._cleanup_resources()
            raise

    def run(self):
        """Main bridge loop handling bidirectional data transfer"""
        self.is_running = True
        logger.info(f"Starting connection bridge for {self.peer}")
        
        try:
            while not self.shutdown_event.is_set() and self.is_running:
                connection_alive = True
                
                # Handle TCP socket -> LoRa socket direction
                try:
                    if self.sock:
                        data = self.sock.recv(4096)
                        if len(data) > 0:
                            logger.debug(f"Received {len(data)} bytes from TCP broker: {self.peer}")
                            bytes_written = self.lora_sock.write(data, len(data))
                            logger.debug(f"Forwarded {bytes_written} bytes to LoRa")
                        elif len(data) == 0:
                            logger.info(f"TCP connection closed by broker: {self.peer}")
                            connection_alive = False
                            
                except socket.timeout:
                    pass  # Normal timeout, continue
                except SocketError as e:
                    if e.errno == errno.ECONNRESET:
                        logger.warning(f"TCP connection reset by broker: {self.peer}")
                        connection_alive = False
                    elif e.errno == errno.ECONNABORTED:
                        logger.warning(f"TCP connection aborted by broker: {self.peer}")
                        connection_alive = False
                    else:
                        logger.error(f"TCP socket error from broker {self.peer}: {e}")
                        connection_alive = False
                except Exception as e:
                    logger.error(f"Unexpected error reading from TCP socket {self.peer}: {e}")
                    logger.debug(traceback.format_exc())
                    connection_alive = False

                # Handle LoRa socket -> TCP socket direction
                try:
                    data = self.lora_sock.read()
                    if data and len(data) > 0:
                        logger.debug(f"Received {len(data)} bytes from LoRa sensor")
                        if self.sock:
                            self.sock.sendall(data)
                            logger.debug(f"Forwarded {len(data)} bytes to TCP broker: {self.peer}")
                        
                except OSError as e:
                    error_str = str(e)
                    if "110" in error_str:  # ETIMEDOUT
                        pass  # Normal timeout, continue
                    elif "Socket is closed" in error_str:
                        logger.info("LoRa socket closed, terminating bridge")
                        connection_alive = False
                    else:
                        logger.error(f"LoRa socket error: {e}")
                        connection_alive = False
                except Exception as e:
                    logger.error(f"Unexpected error reading from LoRa socket: {e}")
                    logger.debug(traceback.format_exc())
                    connection_alive = False
                
                # Exit if connection is no longer alive
                if not connection_alive:
                    logger.info(f"Connection no longer alive, stopping bridge for {self.peer}")
                    break
                    
        except Exception as e:
            logger.error(f"Fatal error in connection bridge {self.peer}: {e}")
            logger.debug(traceback.format_exc())
        finally:
            self.is_running = False
            self._cleanup_resources()
            logger.info(f"Connection bridge stopped for {self.peer}")

    def stop(self):
        """Gracefully stop the connection bridge"""
        logger.info(f"Stopping connection bridge for {self.peer}")
        self.shutdown_event.set()
        self.is_running = False
        
        # Give the thread a moment to finish gracefully
        if self.is_alive():
            self.join(timeout=2.0)
            if self.is_alive():
                logger.warning(f"Connection bridge thread for {self.peer} did not stop gracefully")
        
        self._cleanup_resources()
        
    def _cleanup_resources(self):
        """Clean up socket resources and remove from connections list"""
        try:
            # Close TCP socket
            if self.sock:
                try:
                    self.sock.close()
                    logger.debug(f"TCP socket closed for {self.peer}")
                except Exception as e:
                    logger.warning(f"Error closing TCP socket for {self.peer}: {e}")
                finally:
                    self.sock = None
            
            # Close LoRa socket
            if hasattr(self, 'lora_sock') and self.lora_sock:
                try:
                    self.lora_sock.close()
                    logger.debug(f"LoRa socket closed for {self.peer}")
                except Exception as e:
                    logger.warning(f"Error closing LoRa socket for {self.peer}: {e}")
            
            # Remove from connections list
            with ConnectionBridge.CONNECTIONS_LOCK:
                if self in ConnectionBridge.CONNECTIONS:
                    ConnectionBridge.CONNECTIONS.remove(self)
                    logger.debug(f"Removed connection bridge for {self.peer} from connections list")
                    
        except Exception as e:
            logger.error(f"Error during resource cleanup for {self.peer}: {e}")
    
    @classmethod
    def stop_all_connections(cls):
        """Stop all active connection bridges"""
        logger.info("Stopping all connection bridges")
        with cls.CONNECTIONS_LOCK:
            connections_copy = cls.CONNECTIONS.copy()
        
        for connection in connections_copy:
            try:
                connection.stop()
            except Exception as e:
                logger.error(f"Error stopping connection {connection.peer}: {e}")
        
        logger.info("All connection bridges stopped")





class LoRaGateway:
    """
    LoRa Gateway that manages incoming LoRa connections and bridges them to TCP brokers
    """

    def __init__(self, shutdown_event: threading.Event):
        self.lora_networking = LoRaNetworking()
        self.shutdown_event = shutdown_event
        self.running = False
        logger.info("LoRaGateway initialized")

    def run(self):
        """Main gateway loop - waits for LoRa connections and creates bridges"""
        logger.info("LoRaGateway starting up")
        self.running = True
        last_status_output = time.ticks_ms()
        connection_count = 0
        
        try:
            while not self.shutdown_event.is_set() and self.running:
                try:
                    # Status logging
                    current_time = time.ticks_ms()
                    if time.ticks_diff(current_time, last_status_output) > 10_000:
                        active_connections = len(ConnectionBridge.CONNECTIONS)
                        logger.info(f"Gateway status: {active_connections} active connections, "
                                  f"{connection_count} total connections created")
                        last_status_output = current_time
                    
                    # Wait for incoming LoRa connection
                    logger.debug("Waiting for incoming LoRa connection...")
                    listen_socket = None
                    
                    try:
                        listen_socket = LoRaTCP()
                        logger.debug("Created LoRaTCP socket, starting listen...")
                        listen_socket.listen()  # This blocks until connection arrives
                        
                        if self.shutdown_event.is_set():
                            logger.info("Shutdown requested during listen, breaking")
                            if listen_socket:
                                listen_socket.close()
                            break
                        
                        # Get peer information
                        peer = listen_socket.getpeername()
                        logger.info(f"New LoRa connection received from: {peer}")
                        
                        # Create and start connection bridge
                        bridge = ConnectionBridge(listen_socket, peer)
                        bridge.start()
                        connection_count += 1
                        
                        logger.info(f"Connection bridge #{connection_count} started for {peer}")
                        
                    except Exception as e:
                        logger.error(f"Error handling incoming connection: {e}")
                        logger.debug(traceback.format_exc())
                        
                        # Clean up failed socket
                        if listen_socket:
                            try:
                                listen_socket.close()
                            except:
                                pass
                        
                        # Sleep briefly to avoid tight loop on persistent errors
                        time.sleep(1.0)
                        
                except KeyboardInterrupt:
                    logger.info("KeyboardInterrupt received, stopping gateway")
                    break
                except Exception as e:
                    logger.error(f"Unexpected error in gateway main loop: {e}")
                    logger.debug(traceback.format_exc())
                    time.sleep(1.0)  # Prevent tight error loop
                    
        except Exception as e:
            logger.error(f"Fatal error in LoRaGateway: {e}")
            logger.debug(traceback.format_exc())
        finally:
            self.running = False
            self.stop()
            logger.info("LoRaGateway exited")

    def stop(self):
        """Gracefully stop the gateway and all connections"""
        logger.info("Stopping LoRaGateway...")
        self.running = False
        
        try:
            # Stop all connection bridges
            ConnectionBridge.stop_all_connections()
            
            # Stop LoRa networking
            logger.info("Stopping LoRa networking...")
            if hasattr(self, 'lora_networking') and self.lora_networking:
                self.lora_networking.stop()
                
            logger.info("LoRaGateway stopped successfully")
            
        except Exception as e:
            logger.error(f"Error during LoRaGateway shutdown: {e}")
            logger.debug(traceback.format_exc())
