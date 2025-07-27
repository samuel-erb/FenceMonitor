import gc
from micropython import const
import machine
import micropython_time as time
from config.lora_config import configure_modem, calculate_lora_airtime_ms
from LoRaNetworking.Queue import Queue
from Singleton import Singleton
from lora import RxPacket, SX1262

LORA_DATALINK_MODE_SENSOR = const(0)
LORA_DATALINK_MODE_GATEWAY = const(1)
LORA_DATALINK_MODE = LORA_DATALINK_MODE_GATEWAY


LOGLEVEL_DEBUG = const(0)
LOGLEVEL_INFO = const(1)
LOGLEVEL_WARNING = const(2)
LOGLEVEL_ERROR = const(3)

DATALINK_LOG_LEVEL = const(LOGLEVEL_DEBUG)


def _log(message: str, loglevel=LOGLEVEL_DEBUG):
    if loglevel == LOGLEVEL_DEBUG and DATALINK_LOG_LEVEL == LOGLEVEL_DEBUG:
        print(f"[LoRaDataLink] \033[37mDebug: {message}\033[0m")
    elif loglevel == LOGLEVEL_INFO and DATALINK_LOG_LEVEL <= LOGLEVEL_INFO:
        print(f"[LoRaDataLink] \033[92mInfo: {message}\033[0m")
    elif loglevel == LOGLEVEL_WARNING and DATALINK_LOG_LEVEL <= LOGLEVEL_WARNING:
        print(f"[LoRaDataLink] \033[33mWarning: {message}\033[0m")
    elif loglevel == LOGLEVEL_ERROR and DATALINK_LOG_LEVEL <= LOGLEVEL_ERROR:
        print(f"[LoRaDataLink] \033[31mError: {message}\033[0m")


# Alternative zu Enums in MicroPython:
# Wir definieren einfache Konstanten und ein Dictionary für die Namen.
# Damit sparen wir den Enum-Import und bleiben MicroPython-kompatibel.
DATAFRAME_TYPE = {
    0x00: "LoRaDataLink_Woke_Up",
    0x01: "LoRaTCP_Segment"
}

LoRaDataLink_Woke_Up = const(0x00)
LoRaTCP_Segment = const(0x01)

DataFrameHeaderLength = const(7)  # 6 Bytes für Sensor-Adresse und 1 Byte für DataFrameType
DataFrameMaxPayloadLength = const(248)  # 255 - DataFrameHeaderLength -> 248 Maximale Länge des Payloads im LoRa-Frame

# Timeout of communication in milliseconds after which a sensor is regarded as inactive
SENSOR_ACTIVE_TIMEOUT = 10_000


class SensorState:
    __slots__ = ('sensor_address', 'socket_ids', 'last_communication')
    INSTANCES = list()

    def __init__(self, sensor_address: bytes):
        self.sensor_address = sensor_address  # type: bytes
        self.socket_ids = list()  # type: List[int]
        self.last_communication = None  # type: int
        SensorState.INSTANCES.append(self)

    def is_active(self) -> bool:
        if self.last_communication is None:
            return False
        else:
            return time.ticks_diff(time.ticks_ms(), self.last_communication) <= SENSOR_ACTIVE_TIMEOUT

    @staticmethod
    def get_state_by_address(sensor_address: bytes) -> "SensorState":
        state = None
        for instance in SensorState.INSTANCES:  # type: SensorState
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


def diagnose_lora(lora_modem: SX1262):
    """Führt eine Diagnose des SX1262 LoRa-Modems durch"""
    # SX1262 Register
    REG_LSYNCRH = 0x740
    REG_LSYNCRL = 0x741
    REG_RX_GAIN = 0x08AC
    _log("\n=== SX1262 LoRa Modem Diagnose ===")

    # Status abfragen
    try:
        status = lora_modem._get_status()
        mode, cmd_status = status
        _log(f"Status Mode: {mode} (2=STDBY_RC, 3=STDBY_HSE32, 5=RX, 6=TX)")
        _log(f"Command Status: {cmd_status}")
    except Exception as e:
        _log(f"Fehler beim Status-Abruf: {e}")

    # Fehler abfragen
    try:
        error_status = lora_modem._check_error()
        _log(f"Error Status: {error_status} (Keine Fehler wenn kein Fehler geworfen wurde)")
    except Exception as e:
        _log(f"Aktuelle Fehler: {e}")

    # Frequenz (aus gespeichertem Wert)
    freq_mhz = lora_modem._rf_freq_hz / 1_000_000
    _log(f"Konfigurierte Frequenz: {freq_mhz:.3f} MHz")

    # Spreading Factor
    _log(f"Spreading Factor: {lora_modem._sf}")

    # Bandwidth
    _log(f"Bandwidth: {lora_modem._bw} kHz")

    # Coding Rate
    _log(f"Coding Rate: 4/{lora_modem._coding_rate}")

    # Preamble
    _log(f"Preamble Länge: {lora_modem._preamble_len}")

    # Output Power
    _log(f"Output Power: {lora_modem._output_power} dBm")

    # CRC
    _log(f"CRC: {'Aktiviert' if lora_modem._crc_en else 'Deaktiviert'}")

    # Implicit Header
    _log(f"Header Mode: {'Implicit' if lora_modem._implicit_header else 'Explicit'}")

    # IQ Einstellungen
    _log(f"IQ RX Invert: {lora_modem._invert_iq[0]}")
    _log(f"IQ TX Invert: {lora_modem._invert_iq[1]}")

    # Sync Word Register lesen
    try:
        sync_h = lora_modem._reg_read(REG_LSYNCRH)
        sync_l = lora_modem._reg_read(REG_LSYNCRL)
        syncword = (sync_h << 8) | sync_l
        _log(f"Sync Word: 0x{syncword:04X}")
    except Exception as e:
        _log(f"Fehler beim Sync Word Lesen: {e}")

    # RX Gain Register
    try:
        rx_gain = lora_modem._reg_read(REG_RX_GAIN)
        _log(f"RX Gain: 0x{rx_gain:02X} ({'Boost' if rx_gain == 0x96 else 'Normal'})")
    except Exception as e:
        _log(f"Fehler beim RX Gain Lesen: {e}")

    _log("=== Diagnose abgeschlossen ===\n")


class LoRaDataFrame:
    __slots__ = ("address", "data_type", "payload", "sockets", "listening_sockets")
    """
    Kapselt die Nutzdaten eines Protokollframes für die Übertragung via LoRa.
    Ein Frame besteht aus:
    - 6 Byte Adresse
    - 1 Byte Typ-Header
    - Payload (max. so, dass Frame <= 255 Byte)
    """

    def __init__(self, address: bytes, data_type: int, payload: bytes):
        if len(address) != 6:
            raise ValueError("address must be 6 bytes")
        if data_type not in DATAFRAME_TYPE:
            raise ValueError("invalid data_type")
        if len(payload) > DataFrameMaxPayloadLength:
            raise ValueError("payload too large for frame")
        self.address = address
        self.data_type = data_type
        self.payload = payload

    def to_bytes(self) -> bytes:
        """
        Serialisiert den Frame für die Übertragung via LoRa.
        Fügt Address, Data-Type-Byte und Payload zusammen.
        """
        return self.address + bytes([self.data_type]) + self.payload

    @classmethod
    def from_bytes(cls, data: bytes) -> "LoRaDataFrame":
        """
        Wandelt empfangene Rohbytes in ein LoRaDataFrame-Objekt um.
        """
        if len(data) < 7:
            raise ValueError("Frame too short")
        address = data[:6]
        data_type_value = data[6]
        if data_type_value not in DATAFRAME_TYPE:
            raise ValueError("Unknown data type: {}".format(data_type_value))
        payload = data[7:]
        return cls(address, data_type_value, payload)

    def __repr__(self):
        type_name = DATAFRAME_TYPE.get(self.data_type, "Unknown")
        return f"<LoRaDataFrame address={self.address.hex()} type={type_name} payload_len={len(self.payload)}>"


class LoRaDataLink(Singleton):
    """
    Diese Klasse stellt die Data Link Layer Funktionalität bereit.
    Sie implementiert eine asynchrone Sender- und Empfänger-Logik für LoRa,
    wobei der offizielle MicroPython SX1262-Treiber verwendet wird.

    Außerdem verwaltet sie einen Sendepuffer (transmitQueue) und einen Empfangspuffer (receiveQueue).
    """

    __slots__ = ('mode', 'sensor_address', '_driver', '_receiveQueue', '_transmitQueue', '_duty_cycle_timer',
                 '_transmit_time', 'sockets', 'listening_sockets', '_transmission_block',
                 '_duty_cycle_message_displayed', '_busy_timeout_retries')

    def _init_once(self, **kwargs):
        self.mode = LORA_DATALINK_MODE
        if self.mode == LORA_DATALINK_MODE_SENSOR:
            self.sensor_address = machine.unique_id()[:6]  # Eindeutige Geräteadresse
        else:
            self.sensor_address = None

        self._driver = configure_modem()
        if DATALINK_LOG_LEVEL == LOGLEVEL_DEBUG:
            diagnose_lora(self._driver)
        self.sockets = list()  # type: List[LoRaTCP]
        self.listening_sockets = list()  # type: List[LoRaTCP]
        self._receiveQueue = Queue(maxsize=10)
        self._transmitQueue = Queue(maxsize=10)
        self._duty_cycle_timer = time.ticks_ms() # Wird jede Stunde auf die aktuelle Zeit gesetzt
        self._transmit_time = 0 # Enthält die kumulierte Sendezeit
        self._duty_cycle_message_displayed = False
        self._transmission_block = False # Einfaches Lock um die Kommunikation zu pausieren
        self._busy_timeout_retries = 0 # Zähler für Busy-Timeout Fehler

    def register_listening_socket(self, socket: "LoRaTCP"):
        if self.mode == LORA_DATALINK_MODE_SENSOR:
            raise Exception("You can't register a listening socket on a Sensor!")
        self.listening_sockets.append(socket)

    def register_syn_rcvd_socket(self, socket: "LoRaTCP"):
        if socket in self.listening_sockets:
            self.listening_sockets.remove(socket)
        if SensorState.get_by_socket_id(socket.tcb.socket_id) is None:
            state = SensorState(socket.tcb.socket_id)
            state.last_communication = time.ticks_ms()
        self.sockets.append(socket)

    def run(self):
        if self._transmission_block:
            return
        rx_packet = None
        try:
            self._driver.standby()
            while not self._driver.is_idle():
                time.sleep_ms(50)
            rx_packet = self._driver.recv(timeout_ms=400)
        except Exception as e:
            _log(f"Error: {e}")
            if "BUSY timeout" in str(e):
                self._transmission_block = True
                _log("Attempting recovery after BUSY timeout while receiving...")
                time.sleep_ms(1000)
                try:
                    # Versuche, das Modem in einen bekannten Zustand zu bringen
                    self._driver = configure_modem()
                    time.sleep_ms(500)
                    self._driver.standby()
                    time.sleep_ms(500)
                    if (self._busy_timeout_retries == 10):
                        machine.reset()
                    _log("Recovery successful")
                    self._busy_timeout_retries += 1
                except Exception as recover_error:
                    _log(f"Recovery failed: {recover_error}")
                    time.sleep_ms(2000)  # Längere Pause nach gescheitertem Recovery
                finally:
                    self._transmission_block = False

        if isinstance(rx_packet, RxPacket) and len(rx_packet) >= DataFrameHeaderLength:
            try:
                lora_dataframe = LoRaDataFrame.from_bytes(rx_packet)
                _log(f'Received dataframe: {lora_dataframe}')
                # Filter: Nur Frames akzeptieren, die an dieses Gerät adressiert sind
                # oder wenn wir die Basisstation sind, werden alle Dataframes akzeptiert
                if self.mode == LORA_DATALINK_MODE_GATEWAY or self.sensor_address == lora_dataframe.address:
                    if lora_dataframe.data_type == LoRaTCP_Segment:
                        # Weil wir keine Ports benutzen müsen wir die Socket-ID auslesen und den Dataframe dem richtigen Socket zuordnen
                        socket_id = int.from_bytes(lora_dataframe.payload[0:6], 'big')
                        socket = None
                        for sock in self.sockets:  # type: LoRaTCP
                            if sock.tcb.socket_id == socket_id:
                                socket = sock

                        # wenn wir kein Socket mit der Socket-ID haben, schauen wir, ob wir ein Socket im LISTEN state haben
                        if socket is None and len(self.listening_sockets) > 0:
                            socket = self.listening_sockets[0]  # type: LoRaTCP

                        if socket is None:
                            raise Exception(
                                f"Received a LoRaTCP_Segment with socket-id {socket_id}, but we dont have any open sockets nor listening sockets: {lora_dataframe}")

                        if self.mode == LORA_DATALINK_MODE_GATEWAY:
                            state = SensorState.get_state_by_address(lora_dataframe.address)
                            if state is None:
                                state = SensorState(lora_dataframe.address)
                            if socket_id not in state.socket_ids:
                                state.socket_ids.append(socket_id)
                            _log(f"Updated last communication time for sensor {state.sensor_address}")
                            state.last_communication = time.ticks_ms()

                        socket.add_lora_dataframe_to_queue(lora_dataframe)

                    elif lora_dataframe.data_type == LoRaDataLink_Woke_Up and self.mode == LORA_DATALINK_MODE_GATEWAY:
                        state = SensorState.get_state_by_address(lora_dataframe.address)
                        if state is None:
                            state = SensorState(lora_dataframe.address)
                        state.last_communication = time.ticks_ms()

            except ValueError as e:
                _log(f'Received ValueError: {e}', LOGLEVEL_WARNING)
            except Exception as e:
                _log(f'{e}', LOGLEVEL_WARNING)

        time.sleep_ms(100)
        
        # Check duty cycle enforcement (1% duty cycle = 36 seconds per hour)
        current_time = time.ticks_ms()
        cycle_elapsed = time.ticks_diff(current_time, self._duty_cycle_timer)
        
        # If within the monitoring period (1 hour) and transmission time exceeded limit (36 seconds)
        if cycle_elapsed < 60 * 60 * 1000 and self._transmit_time > 36_000:  # Within 1 hour and exceeded 36 seconds
            # Calculate remaining time until next duty cycle period
            remaining_cycle_time = (60 * 60 * 1000) - cycle_elapsed
            
            if self.mode == LORA_DATALINK_MODE_GATEWAY:
                if not self._duty_cycle_message_displayed:
                    _log(
                        f'Reached duty cycle budget of 36 seconds / hour. We will only receive messages for the next {remaining_cycle_time} ms...',
                        LOGLEVEL_INFO)
                    self._duty_cycle_message_displayed = True
                return  # Skip transmission but continue receiving
            else:  # Sensors must sleep to comply with duty cycle
                _log(f'Reached duty cycle budget of 36 seconds / hour. Waiting for {remaining_cycle_time} ms...',
                     LOGLEVEL_INFO)
                time.sleep_ms(remaining_cycle_time)
        elif cycle_elapsed >= 60 * 60 * 1000:  # Hour has passed, reset duty cycle
            self._duty_cycle_timer = current_time
            self._transmit_time = 0
            self._duty_cycle_message_displayed = False
            self._busy_timeout_retries = 0
            _log("Reset duty cycle timer after 1 hour", LOGLEVEL_INFO)
        if len(self._transmitQueue) > 0:
            lora_dataframe: LoRaDataFrame = self._find_dataframe_for_active_sensor()
            if lora_dataframe is None:
                return
            # Warte bis Kanal frei
            cad_message_displayed = False
            while self._is_channel_active():
                if not cad_message_displayed:
                    _log('Wait for channel access...')
                    cad_message_displayed = True
                time.sleep_ms(5)
            _log('Channel is free to send')
            start = time.ticks_ms()
            try:
                self._driver.send(lora_dataframe.to_bytes())
                time_on_air = time.ticks_diff(time.ticks_ms(), start)
                self._transmit_time += time_on_air
            except Exception as e:
                _log(f"{e}", LOGLEVEL_ERROR)
                self._transmitQueue.put_sync_left(lora_dataframe)
                if "BUSY timeout" in str(e):
                    self._transmission_block = True
                    _log("Attempting recovery after BUSY timeout while sending...")
                    time.sleep_ms(1000)
                    try:
                        # Versuche, das Modem in einen bekannten Zustand zu bringen
                        self._driver = configure_modem()
                        time.sleep_ms(500)
                        self._driver.standby()
                        time.sleep_ms(500)
                        if (self._busy_timeout_retries == 10):
                            machine.reset()
                        _log("Recovery successful")
                        self._busy_timeout_retries += 1
                    except Exception as recover_error:
                        _log(f"Recovery failed: {recover_error}")
                        time.sleep_ms(2000)  # Längere Pause nach gescheitertem Recovery
                    finally:
                        self._transmission_block = False
            _log(f'Sent packet: {lora_dataframe}')

    def _is_channel_active(self) -> bool:
        """
        Platzhalter für Channel Activity Detection (CAD).
        Sollte prüfen, ob aktuell jemand sendet, um Kollisionen zu vermeiden.
        """
        # TODO
        return False

    def _find_dataframe_for_active_sensor(self):
        """
        Durchsucht die transmitQueue nach einem Dataframe für einen aktiven Sensor.
        Gibt das erste gefundene Dataframe zurück und entfernt es aus der Queue.
        Dataframes für inaktive Sensoren bleiben in der Queue für späteren Versuch.
        """
        if self.mode == LORA_DATALINK_MODE_SENSOR:
            return self._transmitQueue.pop_sync()

        frames_to_check = []
        active_frame = None

        # Alle Frames aus der Queue extrahieren
        while len(self._transmitQueue) > 0:
            frame = self._transmitQueue.pop_sync()
            if frame is not None:
                frames_to_check.append(frame)

        # Frames prüfen und das erste für einen aktiven Sensor finden
        for frame in frames_to_check:
            sensor_address = frame.address
            state = SensorState.get_state_by_address(sensor_address)

            if state is not None and state.is_active():
                # Aktiver Sensor gefunden - dieses Frame senden
                if active_frame is None:
                    active_frame = frame
                    _log(f"Found frame for active sensor {sensor_address.hex()}", LOGLEVEL_DEBUG)
                else:
                    # Weitere Frames für aktive Sensoren zurück in die Queue
                    self._transmitQueue.put_sync(frame)
            else:
                # Sensor ist inaktiv - Frame zurück in die Queue für späteren Versuch
                self._transmitQueue.put_sync(frame)
                sensor_hex = sensor_address.hex() if sensor_address else "unknown"
                _log(f"Keeping frame for inactive sensor {sensor_hex} in queue", LOGLEVEL_DEBUG)



        return active_frame

    def add_to_send_queue(self, data: bytes):
        if self.mode == LORA_DATALINK_MODE_GATEWAY:
            socket_id = int.from_bytes(data[0:6], 'big')
            state = SensorState.get_by_socket_id(socket_id)
            if state is None:
                raise RuntimeError(
                    f"Cannot add packet to DataLinkQueue because we dont hava a socket record for this socket-id: {socket_id}")
            lora_dataframe = LoRaDataFrame(state.sensor_address, LoRaTCP_Segment, data)
            self._transmitQueue.put_sync(lora_dataframe)
        else:
            lora_dataframe = LoRaDataFrame(self.sensor_address, LoRaTCP_Segment, data)
            self._transmitQueue.put_sync(lora_dataframe)

    def is_sleep_ready(self) -> bool:
        """
        Prüft, ob momentan keine Pakete gesendet oder empfangen werden,
        damit Energiesparmodus aktiviert werden kann.
        """
        _log(f"is_sleep_ready: transmitQueue={len(self._transmitQueue)}, receiveQueue={len(self._receiveQueue)} -> {len(self._transmitQueue) == 0 and len(self._receiveQueue) == 0}", LOGLEVEL_INFO)
        return len(self._transmitQueue) == 0 and len(self._receiveQueue) == 0

    def woke_up(self) -> None:
        """
        Methode um dem Netz zu signalisieren, dass der Knoten aus dem Schlafmodus erwacht ist.
        Stoppt die Sendeschleife, wartet bis Kanal frei ist und sendet ein Wake-up Paket.
        """
        if self.mode == LORA_DATALINK_MODE_GATEWAY:
            raise Exception("[LoRaDataLink] Called woke_up method with mode LORA_DATALINK_MODE_GATEWAY")
        _log("Woke-up")
        self._busy_timeout_retries = 0
        #self._driver = configure_modem()
        time.sleep_ms(100)
        while self._is_channel_active():
            time.sleep_ms(25)
        wake_up_message = LoRaDataFrame(self.sensor_address, LoRaDataLink_Woke_Up, b'')
        self._driver.standby()
        time.sleep_ms(100)
        self._driver.send(wake_up_message.to_bytes())
        _log("Sent Woke-up message")
        self._transmission_block = False
        time.sleep_ms(50)

    def remove_socket(self, socket: "LoRaTCP"):
        self.sockets.remove(socket)

    def prepare_for_sleep(self):
        self._transmission_block = True
        self._driver.standby()
        time.sleep(10)