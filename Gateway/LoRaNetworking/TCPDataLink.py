import socket
import struct
import threading
import time
from queue import Queue as ThreadQueue, Empty

from LoRaNetworking.Queue import Queue
from LoRaNetworking.LoRaTCPSegment import LoRaTCPSegment

LOGLEVEL_DEBUG = 0
LOGLEVEL_INFO = 1
LOGLEVEL_WARNING = 2
LOGLEVEL_ERROR = 3
DATALINK_LOG_LEVEL = LOGLEVEL_DEBUG

LORA_DATALINK_MODE_SENSOR = 0
LORA_DATALINK_MODE_GATEWAY = 1
LORA_DATALINK_MODE = LORA_DATALINK_MODE_SENSOR

DATAFRAME_HEADER_LENGTH = 7
DATAFRAME_MAX_PAYLOAD_LENGTH = 249

DATAFRAME_TYPE = {
    0x00: "LoRaDataLink_Woke_Up",
    0x01: "LoRaTCP_Segment"
}

LoRaDataLink_Woke_Up = 0x00
LoRaTCP_Segment = 0x01

SENSOR_ACTIVE_TIMEOUT = 10_000

def _log(message: str, loglevel=LOGLEVEL_DEBUG):
    if loglevel == LOGLEVEL_DEBUG and DATALINK_LOG_LEVEL == LOGLEVEL_DEBUG:
        print(f"[TCPDataLink] \033[37mDebug: {message}\033[0m")
    elif loglevel == LOGLEVEL_INFO and DATALINK_LOG_LEVEL <= LOGLEVEL_INFO:
        print(f"[TCPDataLink] \033[92mInfo: {message}\033[0m")
    elif loglevel == LOGLEVEL_WARNING and DATALINK_LOG_LEVEL <= LOGLEVEL_WARNING:
        print(f"[TCPDataLink] \033[33mWarning: {message}\033[0m")
    elif loglevel == LOGLEVEL_ERROR and DATALINK_LOG_LEVEL <= LOGLEVEL_ERROR:
        print(f"[TCPDataLink] \033[31mError: {message}\033[0m")

class SensorState:
    __slots__ = ('sensor_address', 'socket_ids', 'last_communication')
    INSTANCES = list()

    def __init__(self, sensor_address: bytes):
        self.sensor_address = sensor_address
        self.socket_ids = list()
        self.last_communication = None
        SensorState.INSTANCES.append(self)

    def is_active(self) -> bool:
        if self.last_communication is None:
            return False
        else:
            return (time.time() * 1000 - self.last_communication) <= SENSOR_ACTIVE_TIMEOUT

    @staticmethod
    def get_state_by_address(sensor_address: bytes) -> "SensorState":
        state = None
        for instance in SensorState.INSTANCES:
            if instance.sensor_address == sensor_address:
                state = instance
        return state

    @staticmethod
    def get_by_socket_id(socket_id: bytes) -> "SensorState":
        state = None
        for instance in SensorState.INSTANCES:
            if socket_id in instance.socket_ids:
                state = instance
        return state

class LoRaDataFrame:
    __slots__ = ("address", "data_type", "payload")
    
    _STRUCT_FORMAT = ">6sB"
    _HEADER_SIZE = struct.calcsize(_STRUCT_FORMAT)

    def __init__(self, address: bytes, data_type: int, payload: bytes):
        if len(address) != 6:
            raise ValueError("address must be 6 bytes")
        if data_type not in DATAFRAME_TYPE:
            raise ValueError("invalid data_type")
        if len(payload) > (DATAFRAME_MAX_PAYLOAD_LENGTH):
            raise ValueError("payload too large for frame")
        self.address = address
        self.data_type = data_type
        self.payload = payload

    def to_bytes(self) -> bytes:
        header = struct.pack(self._STRUCT_FORMAT, self.address, self.data_type)
        return header + self.payload

    @classmethod
    def from_bytes(cls, data: bytes) -> "LoRaDataFrame":
        if len(data) < cls._HEADER_SIZE:
            raise ValueError("Frame too short")
        address, data_type_value = struct.unpack(cls._STRUCT_FORMAT, data[:cls._HEADER_SIZE])
        if data_type_value not in DATAFRAME_TYPE:
            raise ValueError(f"Unknown data type: {data_type_value}")
        payload = data[cls._HEADER_SIZE:]
        return cls(address, data_type_value, payload)

    def __repr__(self):
        type_name = DATAFRAME_TYPE.get(self.data_type, "Unknown")
        return f"<LoRaDataFrame address={self.address.hex()} type={type_name} payload_len={len(self.payload)}>"

def get_socket_id_from_frame(segment_bytes: bytes) -> int:
    socket_id_flag_byte = segment_bytes[0]
    socket_id = (socket_id_flag_byte & 0xF0) >> 4
    return socket_id

class TCPDataLink:

    def __init__(self, server_port=80, server_host='192.168.1.2', listen=True):
        self.mode = LORA_DATALINK_MODE_GATEWAY if listen else LORA_DATALINK_MODE_SENSOR
        
        if self.mode == LORA_DATALINK_MODE_SENSOR:
            self.sensor_address = b'\x01\x02\x03\x04\x05\x06'  # Feste Test-Adresse für Sensor
        else:
            self.sensor_address = None

        self.sockets = list()
        self.listening_sockets = list()
        self._receiveQueue = Queue(maxsize=10)
        self._transmitQueue = Queue(maxsize=10)
        self._duty_cycle_timer = time.time() * 1000
        self._transmit_time = 0
        self._duty_cycle_message_displayed = False
        self.duty_cycle_budget_ms = 3_600_000
        self._transmission_block = False
        self._busy_timeout_retries = 0
        self._running = False
        self._tcp_thread = None
        self._connected = False
        self._peer_address = None
        self._message_queue = ThreadQueue()
        
        self._tcp_socket = None
        self._server_socket = None
        self.server_port = server_port
        self.server_host = server_host
        
        self._start_tcp_connection()

    def _start_tcp_connection(self):
        self._running = True
        self._tcp_thread = threading.Thread(target=self._tcp_worker, daemon=True)
        self._tcp_thread.start()
        _log(f"Started TCP connection thread for mode {'SENSOR' if self.mode == LORA_DATALINK_MODE_SENSOR else 'GATEWAY'}")

    def _tcp_worker(self):
        while self._running:
            try:
                if self.mode == LORA_DATALINK_MODE_SENSOR:
                    self._run_sensor_tcp()
                else:
                    self._run_gateway_tcp()
            except Exception as e:
                _log(f"TCP worker error: {e}", LOGLEVEL_ERROR)
                time.sleep(5)  # Increased delay to prevent spam

    def _run_sensor_tcp(self):
        try:
            self._tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._tcp_socket.settimeout(1.0)
            _log(f"Sensor connecting to {self.server_host}:{self.server_port}")
            self._tcp_socket.connect((self.server_host, self.server_port))
            self._connected = True
            _log("Sensor connected to Gateway")
            
            while self._running and self._connected:
                # Run the datalink to process LoRaTCP sockets
                self.run()
                
                try:
                    data = self._tcp_socket.recv(4096)
                    if not data:
                        _log("Connection closed by peer")
                        break
                    segment = LoRaTCPSegment.from_bytes(LoRaDataFrame.from_bytes(data).payload) # type: LoRaTCPSegment
                    _log(f"Sensor received segment: {segment}")
                    self._handle_received_data(data)
                except socket.timeout:
                    pass
                except Exception as e:
                    _log(f"Sensor receive error: {e}", LOGLEVEL_ERROR)
                    break
                
                try:
                    message = self._message_queue.get_nowait()
                    self._tcp_socket.send(message)
                    segment = LoRaTCPSegment.from_bytes(LoRaDataFrame.from_bytes(message).payload)  # type: LoRaTCPSegment
                    _log(f"Sensor sent segment: {segment}")
                except Empty:
                    pass
                except Exception as e:
                    _log(f"Sensor send error: {e}", LOGLEVEL_ERROR)
                    break
                    
        except Exception as e:
            _log(f"Sensor TCP error: {e}", LOGLEVEL_ERROR)
        finally:
            self._connected = False
            if self._tcp_socket:
                self._tcp_socket.close()
                self._tcp_socket = None
            time.sleep(2)

    def _run_gateway_tcp(self):
        try:
            if self._server_socket is None:
                self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    self._server_socket.bind((self.server_host, self.server_port))
                    self._server_socket.listen(1)
                    self._server_socket.settimeout(1.0)
                    _log(f"Gateway listening on {self.server_host}:{self.server_port}")
                except OSError as e:
                    _log(f"Gateway bind error: {e}", LOGLEVEL_ERROR)
                    if self._server_socket:
                        self._server_socket.close()
                        self._server_socket = None
                    time.sleep(10)  # Wait longer before retrying bind
                    return
            
            try:
                client_socket, client_address = self._server_socket.accept()
                _log(f"Gateway accepted connection from {client_address}")
                self._tcp_socket = client_socket
                self._tcp_socket.settimeout(1.0)
                self._connected = True
                self._peer_address = client_address
                
                while self._running and self._connected:
                    # Run the datalink to process LoRaTCP sockets
                    self.run()
                    
                    try:
                        data = self._tcp_socket.recv(4096)
                        if not data:
                            _log("Connection closed by peer")
                            break
                        segment = LoRaTCPSegment.from_bytes(
                            LoRaDataFrame.from_bytes(data).payload)  # type: LoRaTCPSegment
                        _log(f"Gateway received segment: {segment}")
                        self._handle_received_data(data)
                    except socket.timeout:
                        pass
                    except Exception as e:
                        _log(f"Gateway receive error: {e}", LOGLEVEL_ERROR)
                        break
                    
                    try:
                        message = self._message_queue.get_nowait()
                        self._tcp_socket.send(message)
                        segment = LoRaTCPSegment.from_bytes(
                            LoRaDataFrame.from_bytes(message).payload)  # type: LoRaTCPSegment
                        _log(f"Gateway sent segment: {segment}")
                    except Empty:
                        pass
                    except Exception as e:
                        _log(f"Gateway send error: {e}", LOGLEVEL_ERROR)
                        break
                        
            except socket.timeout:
                pass
            except Exception as e:
                _log(f"Gateway accept error: {e}", LOGLEVEL_ERROR)
                
        except Exception as e:
            _log(f"Gateway TCP error: {e}", LOGLEVEL_ERROR)
        finally:
            self._connected = False
            if self._tcp_socket and self._tcp_socket != self._server_socket:
                self._tcp_socket.close()
                self._tcp_socket = None

    def _handle_received_data(self, data: bytes):
        try:
            lora_dataframe = LoRaDataFrame.from_bytes(data)
            _log(f'Received dataframe: {lora_dataframe}')
            
            if self.mode == LORA_DATALINK_MODE_GATEWAY or self.sensor_address == lora_dataframe.address:
                if lora_dataframe.data_type == LoRaTCP_Segment:
                    socket_id = get_socket_id_from_frame(lora_dataframe.payload)
                    socket = None
                    for sock in self.sockets:
                        if sock.tcb.socket_id == socket_id:
                            socket = sock

                    if socket is None and len(self.listening_sockets) > 0:
                        socket = self.listening_sockets[0]

                    if socket is None:
                        raise Exception(f"Received a LoRaTCP_Segment with socket-id {socket_id}, but we dont have any open sockets nor listening sockets: {lora_dataframe}")

                    if self.mode == LORA_DATALINK_MODE_GATEWAY:
                        state = SensorState.get_state_by_address(lora_dataframe.address)
                        if state is None:
                            state = SensorState(lora_dataframe.address)
                        if socket_id not in state.socket_ids:
                            state.socket_ids.append(socket_id)
                        _log(f"Updated last communication time for sensor {state.sensor_address}")
                        state.last_communication = time.time() * 1000

                    socket.add_lora_dataframe_to_queue(lora_dataframe)

                elif lora_dataframe.data_type == LoRaDataLink_Woke_Up and self.mode == LORA_DATALINK_MODE_GATEWAY:
                    state = SensorState.get_state_by_address(lora_dataframe.address)
                    if state is None:
                        state = SensorState(lora_dataframe.address)
                    state.last_communication = time.time() * 1000

        except ValueError as e:
            _log(f'Received ValueError: {e}', LOGLEVEL_WARNING)
        except Exception as e:
            _log(f'{e}', LOGLEVEL_WARNING)

    def register_listening_socket(self, socket: "LoRaTCP"):
        if self.mode == LORA_DATALINK_MODE_SENSOR:
            raise Exception("You can't register a listening socket on a Sensor!")
        self.listening_sockets.append(socket)

    def register_syn_sent_socket(self, socket: "LoRaTCP"):
        if socket in self.listening_sockets:
            self.listening_sockets.remove(socket)
        if SensorState.get_by_socket_id(socket.tcb.socket_id) is None:
            state = SensorState(socket.tcb.socket_id)
            state.last_communication = time.time() * 1000
        self.sockets.append(socket)

    def run(self):
        if self._transmission_block:
            return
        
        # Run all registered LoRaTCP sockets to process incoming segments
        for socket in self.sockets + self.listening_sockets:
            socket.run()
        
        remaining_cycle_time = self._get_remaining_duty_cycle_time_reset_timer_if_necessary()
        if self.mode == LORA_DATALINK_MODE_GATEWAY and self._transmit_time > self.duty_cycle_budget_ms:
            if not self._duty_cycle_message_displayed:
                _log(f'Reached duty cycle budget of {self.duty_cycle_budget_ms/1000} seconds per hour. Stop sending messages for the next {remaining_cycle_time} ms...', LOGLEVEL_INFO)
                self._duty_cycle_message_displayed = True
            return
        elif self._transmit_time > self.duty_cycle_budget_ms:
            _log(f'Reached duty cycle budget of {self.duty_cycle_budget_ms/1000} seconds per hour. Sleeping for {remaining_cycle_time} ms...', LOGLEVEL_INFO)
            time.sleep(remaining_cycle_time / 1000)
        
        lora_dataframe: LoRaDataFrame = self._find_dataframe_for_active_sensor()
        if lora_dataframe is not None and self._connected:
            try:
                start = time.time() * 1000
                message_bytes = lora_dataframe.to_bytes()
                self._message_queue.put(message_bytes)
                time_on_air = time.time() * 1000 - start
                self._transmit_time += time_on_air
                _log(f'Queued packet for transmission: {lora_dataframe}')
            except Exception as e:
                _log(f"{e}", LOGLEVEL_ERROR)
                self._transmitQueue.put_sync_left(lora_dataframe)

    def _get_remaining_duty_cycle_time_reset_timer_if_necessary(self) -> int:
        current_time = time.time() * 1000
        cycle_elapsed = current_time - self._duty_cycle_timer
        if cycle_elapsed >= 3_600_000:
            self._duty_cycle_timer = current_time
            self._transmit_time = 0
            self._duty_cycle_message_displayed = False
            self._busy_timeout_retries = 0
            _log("Reset duty cycle timer after 1 hour", LOGLEVEL_INFO)
        cycle_elapsed = current_time - self._duty_cycle_timer
        remaining_cycle_time = 3_600_000 - cycle_elapsed
        return remaining_cycle_time

    def _find_dataframe_for_active_sensor(self):
        if len(self._transmitQueue) == 0:
            return None

        if self.mode == LORA_DATALINK_MODE_SENSOR:
            return self._transmitQueue.pop_sync()

        frames_to_check = []
        active_frame = None

        while len(self._transmitQueue) > 0:
            frame = self._transmitQueue.pop_sync()
            if frame is not None:
                frames_to_check.append(frame)

        for frame in frames_to_check:
            sensor_address = frame.address
            state = SensorState.get_state_by_address(sensor_address)

            if state is not None and state.is_active():
                if active_frame is None:
                    active_frame = frame
                    _log(f"Found frame for active sensor {sensor_address.hex()}", LOGLEVEL_DEBUG)
                else:
                    self._transmitQueue.put_sync(frame)
            else:
                self._transmitQueue.put_sync(frame)
                sensor_hex = sensor_address.hex() if sensor_address else "unknown"

        return active_frame

    def add_to_send_queue(self, data: bytes):
        if self.mode == LORA_DATALINK_MODE_GATEWAY:
            socket_id = get_socket_id_from_frame(data)
            state = SensorState.get_by_socket_id(socket_id)
            if state is None:
                raise RuntimeError(f"Cannot add packet to DataLinkQueue because we dont hava a socket record for this socket-id: {socket_id}")
            lora_dataframe = LoRaDataFrame(state.sensor_address, LoRaTCP_Segment, data)
            self._transmitQueue.put_sync(lora_dataframe)
        else:
            lora_dataframe = LoRaDataFrame(self.sensor_address, LoRaTCP_Segment, data)
            self._transmitQueue.put_sync(lora_dataframe)

    def is_sleep_ready(self) -> bool:
        _log(f"is_sleep_ready: transmitQueue={len(self._transmitQueue)}, receiveQueue={len(self._receiveQueue)} -> {len(self._transmitQueue) == 0 and len(self._receiveQueue) == 0}", LOGLEVEL_INFO)
        return len(self._transmitQueue) == 0 and len(self._receiveQueue) == 0

    def woke_up(self) -> None:
        if self.mode == LORA_DATALINK_MODE_GATEWAY:
            raise Exception("[TCPDataLink] Called woke_up method with mode LORA_DATALINK_MODE_GATEWAY")
        _log("Woke-up")
        self._busy_timeout_retries = 0
        time.sleep(0.1)
        wake_up_message = LoRaDataFrame(self.sensor_address, LoRaDataLink_Woke_Up, b'')
        if self._connected:
            self._message_queue.put(wake_up_message.to_bytes())
            _log("Sent Woke-up message")
        self._transmission_block = False
        time.sleep(0.05)

    def remove_socket(self, socket: "LoRaTCP"):
        if socket in self.sockets:
            self.sockets.remove(socket)

    def prepare_for_sleep(self):
        self._transmission_block = True

    def shutdown(self):
        self._running = False
        self._connected = False
        if self._tcp_thread:
            self._tcp_thread.join(timeout=2)
        if self._tcp_socket:
            self._tcp_socket.close()
        if self._server_socket:
            self._server_socket.close()
        _log("TCP DataLink shutdown complete")