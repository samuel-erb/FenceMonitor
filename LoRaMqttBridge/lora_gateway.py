import socket
import threading
from threading import Thread

import micropython_time as time
from typing import List
from socket import error as SocketError
import errno
from LoRaNetworking.LoRaTCP import LoRaTCP
from LoRaNetworking.LoRaNetworking import LoRaNetworking

class ConnectionBridge(Thread):
    CONNECTIONS = list()
    def __init__(self, lora_socket: LoRaTCP, peer):
        super().__init__()
        print(f"[ConnectionBridge] Created new instance for socket: {peer}")
        address, port = peer
        self.lora_sock = lora_socket
        self.lora_sock.setblocking(False)
        self.lora_sock.settimeout(0.5)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((address, port))
        self.sock.settimeout(0.5)
        self.shutdown_event = threading.Event()
        ConnectionBridge.CONNECTIONS.append(self)

    def run(self):
        while not self.shutdown_event.is_set():
            try:
                data = self.sock.recv(4096)
                if len(data) > 0:
                    print(f"[LoRaGateway] Received {len(data)} bytes from broker")
                    self.lora_sock.write(data, len(data))
            except socket.timeout:
                pass
            except SocketError as e:
                if e.errno != errno.ECONNRESET:
                    raise e
                self.lora_sock.close()

            try:
                data = self.lora_sock.read()
                if len(data) > 0:
                    print(f"[LoRaGateway] Received {len(data)} bytes from sensor")
                    self.sock.sendall(data)
            except OSError as e:
                if "110" in str(e):
                    pass
                else:
                    print(f"[LoRaGateway] Error while receiving data from sensor: {e}")

    def stop(self):
        self.shutdown_event.set()
        self.sock.close()
        self.lora_sock.close()





class LoRaGateway:

    def __init__(self, shutdown_event: threading.Event):
        self.lora_networking = LoRaNetworking()
        self.connections = list() # type: List[ConnectionBridge]
        self.shutdown_event = shutdown_event

    def run(self):
        print("[LoRaGateway] Started!")
        last_status_output = time.ticks_ms()
        while not self.shutdown_event.is_set():
            if time.ticks_diff(time.ticks_ms(), last_status_output) > 10_000:
                print(f"[LoRaGateway] Managing {len(self.connections)} connections!")
                last_status_output = time.ticks_ms()
            listen_socket = LoRaTCP()
            listen_socket.listen()
            peer = listen_socket.getpeername()
            bridge = ConnectionBridge(listen_socket, peer)
            bridge.start()
            time.sleep(0.5)
        self.stop()
        print("[LoRaGateway] Exited!")

    def stop(self):
        for con in ConnectionBridge.CONNECTIONS:
            con.stop()
        self.running = False
        time.sleep(5.0)
        self.lora_networking.stop()
        exit(0)
