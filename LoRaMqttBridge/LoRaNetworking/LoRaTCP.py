from collections import deque
from LoRaNetworking.LoRaTCPSegment import LoRaTCPSegment, Seq
from LoRaNetworking.TCB import TCB
from LoRaNetworking.LoRaDataLink import LoRaDataLink, LoRaDataFrame

try:
    from typing import Dict, Deque
except ImportError:
    pass
import gc
from micropython import const
import micropython_time as time

# DATAFRAME_MAX_PAYLOAD_LENGTH - Header(2 + 2 + 2 + 1) -> 242: Socket_ID, Flags, Seq_Number, ACK_Number
LoRaTCP_MAX_PAYLOAD_SIZE = const(242)

LOGLEVEL_DEBUG = const(0)
LOGLEVEL_INFO = const(1)
LOGLEVEL_WARNING = const(2)
LOGLEVEL_ERROR = const(3)

TCP_LOG_LEVEL = const(LOGLEVEL_DEBUG)

TCB_STATES = {
    0: "STATE_CLOSED",
    1: "STATE_LISTEN",
    2: "STATE_SYN_RCVD",
    3: "STATE_SYN_SENT",
    4: "STATE_ESTAB",
    5: "STATE_FIN_WAIT_1",
    6: "STATE_CLOSE_WAIT",
    7: "STATE_FIN_WAIT_2",
    8: "STATE_CLOSING",
    9: "STATE_LAST_ACK",
    10: "STATE_TIME_WAIT"
}


def _log(message: str, loglevel=LOGLEVEL_DEBUG):
    if loglevel == LOGLEVEL_DEBUG and TCP_LOG_LEVEL == LOGLEVEL_DEBUG:
        print(f"[LoRaTCP] \033[37mDebug: {message}\033[0m")
    elif loglevel == LOGLEVEL_INFO and TCP_LOG_LEVEL <= LOGLEVEL_INFO:
        print(f"[LoRaTCP] \033[92mInfo: {message}\033[0m")
    elif loglevel == LOGLEVEL_WARNING and TCP_LOG_LEVEL <= LOGLEVEL_WARNING:
        print(f"[LoRaTCP] \033[33mWarning: {message}\033[0m")
    elif loglevel == LOGLEVEL_ERROR and TCP_LOG_LEVEL <= LOGLEVEL_ERROR:
        print(f"[LoRaTCP] \033[31mError: {message}\033[0m")


def ip_to_int(ip_str: str) -> int:
    """
    Konvertiert IPv4-String zu 32-Bit Integer
    """
    parts = ip_str.split('.')
    if len(parts) != 4:
        raise ValueError(f"Ungültige IPv4-Adresse: {ip_str}")

    result = 0
    for i, part in enumerate(parts):
        octet = int(part)
        if not (0 <= octet <= 255):
            raise ValueError(f"Ungültiges IPv4-Oktett: {octet}")
        result |= (octet << (8 * (3 - i)))
    return result


def int_to_ip(ip_int: int) -> str:
    """
    Konvertiert 32-Bit Integer zu IPv4-String
    """
    return f"{(ip_int >> 24) & 0xFF}.{(ip_int >> 16) & 0xFF}.{(ip_int >> 8) & 0xFF}.{ip_int & 0xFF}"


class LoRaTCP:
    """
    Implementiert ein TCP-ähnliches Protokoll über LoRa.

    Diese Klasse kann als Drop-In-Replacement für ein TCP/IP-Socket verwendet werden
    und bietet die gleichen Methoden und Verhaltensweisen wie ein Standard-Socket.
    Unterstützt Verbindungsaufbau, Datenübertragung, Flusskontrolle und ordnungsgemäßes
    Verbindungsende über das LoRa-Funkprotokoll.
    """

    MAX_RETRANSMISSION_ATTEMPTS = 25

    INSTANCES = list()
    __slots__ = ('_data_link', 'tcb', '_incoming_dataframes', '_last_run', '_timeout', '_blocking',
                 '_last_retransmission_sequence_number', '_retransmission_attempts')

    def __init__(self):
        """
        Initialisiert eine neue LoRaTCP-Instanz.

        Erstellt die notwendigen Datenstrukturen für TCP-Verbindungsmanagement,
        initialisiert den Transmission Control Block (TCB) und registriert die
        Instanz in der globalen Liste für Verwaltungszwecke.
        """
        _log("Initializing new LoRaTCP instance", LOGLEVEL_INFO)
        self.tcb = TCB("", 0)  # type: TCB
        self._data_link = LoRaDataLink()
        self._incoming_dataframes = list()
        self._last_run = time.ticks_ms()
        self._timeout = None
        self._blocking = False
        self._last_retransmission_sequence_number = None
        self._retransmission_attempts = 0
        LoRaTCP.INSTANCES.append(self)
        _log(f"LoRaTCP instance created. Total instances: {len(LoRaTCP.INSTANCES)}", LOGLEVEL_INFO)

    def connect(self, peer):
        """
        Stellt eine Verbindung zu einem entfernten TCP her (aktive Verbindung).

        Initiiert den TCP-Handshake durch Senden eines SYN-Segments an den
        angegebenen Peer. Die Methode wechselt den Socket-Zustand von CLOSED
        zu SYN_SENT und wartet auf die Antwort des Peers.

        Args:
            peer: Tupel aus (IP-Adresse, Port) des Ziels

        Raises:
            OSError: Wenn das Socket nicht im CLOSED-Zustand ist
        """
        address, port = peer
        _log(f"Attempting connection to peer: {address}:{port}", LOGLEVEL_INFO)
        if self.tcb.state == TCB.STATE_CLOSED:
            _log("Connecting to {}:{}".format(address, port))
            _log(f"Setting remote address: {address}, remote port: {port}", LOGLEVEL_DEBUG)
            self.tcb.remote_ip = address
            self.tcb.remote_port = port

            _log(f"Creating SYN segment with socket_id={self.tcb.socket_id}, "
                 f"seq={self.tcb.iss}", LOGLEVEL_DEBUG)
            payload = (ip_to_int(self.tcb.remote_ip).to_bytes(4, 'big') +
                       self.tcb.remote_port.to_bytes(2, 'big'))
            new_seg = LoRaTCPSegment(self.tcb.socket_id, self.tcb.iss, syn_flag=True,
                                     ack_flag=False, payload=payload)
            self.tcb.snd_una = self.tcb.iss
            self.tcb.snd_nxt = self.tcb.iss
            _log(f"Updated send variables: snd_una={self.tcb.snd_una}, "
                 f"snd_nxt={self.tcb.snd_nxt}", LOGLEVEL_DEBUG)
            self._data_link.register_syn_sent_socket(self)
            _log("Registered socket with data link", LOGLEVEL_DEBUG)
            self.send_segment(new_seg)
            self.tcb.state = TCB.STATE_SYN_SENT
            _log(f"State changed to SYN_SENT. Connection initiation complete", LOGLEVEL_INFO)
        else:
            _log(f"Cannot connect: socket not in CLOSED state (current state: {TCB_STATES[self.tcb.state]})",
                 LOGLEVEL_ERROR)
            raise OSError("Socket not in CLOSED state for connect()")

    def listen(self):
        """
        Versetzt das Socket in den Listen-Modus für eingehende Verbindungen.

        Implementiert passive Verbindungsöffnung (EVENT_Passive_OPEN).
        Das Socket wartet auf eingehende Verbindungsanfragen von Clients.
        Wird typischerweise auf der Basisstation verwendet, um auf Sensor-
        Verbindungen zu warten. Registriert sich bei der LoRaDataLink für
        unbekannte Socket-IDs.

        Raises:
            OSError: Wenn das Socket nicht im CLOSED-Zustand ist
        """
        _log("Listen method called", LOGLEVEL_INFO)
        if self.tcb.state == TCB.STATE_CLOSED:
            _log("Listening for connection...")
            _log("Initializing TCB for listening state", LOGLEVEL_DEBUG)
            self.tcb = TCB("", 0)
            self.tcb.snd_nxt = self.tcb.iss
            self.tcb.active_open = False
            self.tcb.state = TCB.STATE_LISTEN
            _log(f"TCB configured: active_open={self.tcb.active_open}, state={TCB_STATES[self.tcb.state]}",
                 LOGLEVEL_DEBUG)
            self._data_link.register_listening_socket(self)
            _log("Socket registered with data link as listening socket", LOGLEVEL_INFO)
            while self.tcb.state == TCB.STATE_LISTEN:
                time.sleep_ms(500)
        else:
            _log(f"Cannot listen: socket not in CLOSED state (current state: {TCB_STATES[self.tcb.state]})",
                 LOGLEVEL_ERROR)
            raise OSError("Socket not in CLOSED state for listen()")

    def settimeout(self, timeout):
        """
        Setzt das Timeout-Verhalten des Sockets.

        Konfiguriert wie lange Operationen warten sollen, bevor sie einen
        Timeout-Fehler werfen. Unterstützt blockierende, nicht-blockierende
        und zeitbegrenzte Modi.

        Args:
            timeout: None (blockierend ohne Timeout),
                    0 (nicht-blockierend),
                    float (blockierend mit Timeout in Sekunden)
        """
        _log(f"Setting timeout: {timeout}", LOGLEVEL_DEBUG)
        if timeout is None:
            self._blocking = True
            self._timeout = None
            _log("Socket set to blocking mode with no timeout", LOGLEVEL_DEBUG)
        elif timeout == 0:
            self._blocking = False
            self._timeout = 0
            _log("Socket set to non-blocking mode", LOGLEVEL_DEBUG)
        else:
            self._blocking = True
            self._timeout = timeout
            _log(f"Socket set to blocking mode with timeout: {timeout}s", LOGLEVEL_DEBUG)

    def setblocking(self, flag):
        """
        Setzt den blockierenden Modus des Sockets.

        Steuert ob Socket-Operationen blockieren oder sofort zurückkehren,
        wenn keine Daten verfügbar sind.

        Args:
            flag: True für blockierenden Modus, False für nicht-blockierenden Modus
        """
        _log(f"Setting blocking flag: {flag}", LOGLEVEL_DEBUG)
        self._blocking = bool(flag)
        if flag:
            self._timeout = None
            _log("Socket set to blocking mode", LOGLEVEL_DEBUG)
        else:
            self._timeout = 0
            _log("Socket set to non-blocking mode", LOGLEVEL_DEBUG)

    def write(self, data, size=None):
        """
        Schreibt Daten in das Socket (Socket write() API-kompatibel).

        Implementiert das Standard-Socket write() Verhalten. Konvertiert
        automatisch Strings zu Bytes und unterstützt optionale Größenbegrenzung.

        Args:
            data: Zu sendende Daten (str oder bytes)
            size: Optionale maximale Anzahl zu sendender Bytes

        Returns:
            int: Anzahl der tatsächlich geschriebenen Bytes
        """
        if isinstance(data, str):
            data = data.encode('utf-8')
        if size is not None:
            # Nur die ersten 'size' Bytes senden
            actual_data = data[:size]
            _log(
                f"Write called with data length: {len(data)}, size parameter: {size}, sending: {len(actual_data)} bytes",
                LOGLEVEL_DEBUG)
            _log(f"Write data (limited): {actual_data.hex()}", LOGLEVEL_INFO)
        else:
            # Alle Daten senden
            actual_data = data
            _log(f"Write called with data length: {len(data)}, size parameter: {size}", LOGLEVEL_DEBUG)
            _log(f"Write data (full): {actual_data.hex()}", LOGLEVEL_INFO)

        self.send(actual_data)  # send() ohne size parameter

        bytes_written = len(actual_data)
        _log(f"Write completed, returned: {bytes_written}", LOGLEVEL_DEBUG)
        return bytes_written

    def send(self, data: bytes):
        """
        Sendet Daten über die bestehende Verbindung.

        Fügt Daten zum Sendepuffer hinzu, der je nach Verbindungszustand
        sofort oder verzögert übertragen wird. Implementiert TCP-Semantik
        für verschiedene Verbindungszustände.

        Args:
            data: Zu sendende Daten als bytes

        Raises:
            OSError: Bei verschiedenen Verbindungsfehlern je nach Zustand:
                    - "connection does not exist" (CLOSED)
                    - "foreign socket unspecified" (LISTEN)
                    - "connection closing" (FIN_WAIT_*, CLOSING, etc.)
        """
        _log(f"Send called with data length: {len(data)}, current state: {self.tcb.state}, data: {data.hex()}",
             LOGLEVEL_INFO)
        if self.tcb.state == TCB.STATE_CLOSED:
            _log("Cannot send: connection does not exist", LOGLEVEL_ERROR)
            raise OSError("connection does not exist")
        elif self.tcb.state == TCB.STATE_LISTEN:
            _log("Cannot send: foreign socket unspecified", LOGLEVEL_ERROR)
            raise OSError("foreign socket unspecified")
        elif self.tcb.state in [TCB.STATE_SYN_SENT, TCB.STATE_SYN_RCVD]:
            _log(f"State {self.tcb.state}: Queuing data for transmission after ESTABLISHED", LOGLEVEL_DEBUG)
            with self.tcb.send_buffer_lock:
                prev_len = len(self.tcb.send_buffer)
                self.tcb.send_buffer = self.tcb.send_buffer + data
                _log(f"Send buffer updated: {prev_len} -> {len(self.tcb.send_buffer)} bytes", LOGLEVEL_DEBUG)
                # Queue the data for transmission after entering ESTABLISHED state.
        elif self.tcb.state in [TCB.STATE_ESTAB, TCB.STATE_CLOSE_WAIT]:
            # Segmentize the buffer and send it with a piggybacked acknowledgment (acknowledgment value = RCV.NXT).
            #   If there is insufficient space to remember this buffer, simply return "error: insufficient resources".
            _log(f"State {self.tcb.state}: Adding data to send buffer for immediate transmission", LOGLEVEL_DEBUG)
            with self.tcb.send_buffer_lock:
                prev_len = len(self.tcb.send_buffer)
                self.tcb.send_buffer = self.tcb.send_buffer + data
                _log(f"Send buffer updated: {prev_len} -> {len(self.tcb.send_buffer)} bytes", LOGLEVEL_DEBUG)
        elif self.tcb.state in [TCB.STATE_FIN_WAIT_1, TCB.STATE_FIN_WAIT_2,
                                TCB.STATE_CLOSING, TCB.STATE_LAST_ACK,
                                TCB.STATE_TIME_WAIT]:
            _log(f"Cannot send: connection closing (state: {self.tcb.state})", LOGLEVEL_ERROR)
            raise OSError("connection closing")

    def read(self, bufsize=242):
        """
        Liest Daten aus dem Socket (Socket read/recv API-kompatibel).

        Implementiert Standard-TCP Socket read/recv Verhalten mit Unterstützung
        für blockierende, nicht-blockierende und zeitbegrenzte Modi.
        Wartet auf mindestens 1 Byte bei blockierenden Operationen.

        Args:
            bufsize: Maximale Anzahl zu lesender Bytes (Standard: 242)

        Returns:
            bytes: Gelesene Daten oder None bei nicht-blockierendem Modus ohne Daten

        Raises:
            OSError: Bei geschlossenem Socket (Code ohne Details) oder
                    Timeout (Code 110 - ETIMEDOUT)

        Verhalten:
        - Blockierend: Wartet auf mindestens 1 Byte, gibt verfügbare Daten zurück
        - Nicht-blockierend: Gibt sofort None zurück wenn keine Daten verfügbar
        - Timeout: Wartet bis Timeout auf mindestens 1 Byte, dann OSError
        """
        # _log(f"Read called with bufsize: {bufsize}, current state: {self.tcb.state}", LOGLEVEL_DEBUG)

        if self.tcb.state == TCB.STATE_CLOSED:
            _log("Cannot read: Socket is closed", LOGLEVEL_ERROR)
            raise OSError("Socket is closed")

        if self.tcb.state in [TCB.STATE_LISTEN, TCB.STATE_SYN_SENT]:
            _log(f"Cannot read: No data available in state {TCB_STATES[self.tcb.state]}", LOGLEVEL_DEBUG)
            if not self._blocking:
                return None
            # For blocking sockets, wait for connection establishment

        # _log(f"Available data before read: {len(self.tcb.reassembled_data)} bytes", LOGLEVEL_DEBUG)

        start_time = time.ticks_ms()
        iterations = 0

        # Warte auf MINDESTENS 1 Byte, nicht auf bufsize Bytes
        while len(self.tcb.reassembled_data) == 0:  # ← NUR bis IRGENDWELCHE Daten da sind
            iterations += 1

            if self._blocking:
                if self._timeout is not None:
                    elapsed = (time.ticks_ms() - start_time) / 1000
                    if elapsed >= self._timeout:
                        # _log(f"Read timeout after {elapsed}s (limit: {self._timeout}s)", LOGLEVEL_WARNING)
                        raise OSError(110)  # ETIMEDOUT

                if iterations % 100 == 0:  # Spam verhindern
                    _log(f"Blocking read iteration {iterations}, "
                         f"elapsed: {(time.ticks_ms() - start_time) / 1000:.2f}s", LOGLEVEL_DEBUG)
                time.sleep_ms(10)
            else:
                # Non-blocking: Sofortiger Return
                _log("Non-blocking read: no data available", LOGLEVEL_DEBUG)
                return None
                # raise OSError(11)  # EAGAIN/EWOULDBLOCK

        # Gib verfügbare Daten zurück (bis maximum bufsize)
        with self.tcb.reassembled_data_lock:
            actual_read = min(bufsize, len(self.tcb.reassembled_data))
            data = self.tcb.reassembled_data[:actual_read]
            # Lösche gelesene Daten aus dem TCB
            self.tcb.reassembled_data = self.tcb.reassembled_data[actual_read:]

        _log(
            f"Read completed: requested={bufsize}, actual={actual_read}, "
            f"remaining={len(self.tcb.reassembled_data)}, data: {data.hex()}", LOGLEVEL_INFO)
        return data

    def close(self):
        """
        Schließt die Verbindung ordnungsgemäß (EVENT_CLOSE).

        Implementiert TCP-Verbindungsabbau abhängig vom aktuellen Zustand.
        Sendet bei Bedarf FIN-Segmente und führt Zustandsübergänge durch.

        Zustandsabhängiges Verhalten:
        - CLOSED: Ignoriert stillschweigend (bereits geschlossen)
        - LISTEN/SYN_SENT: Sofortiges Schließen ohne FIN
        - SYN_RCVD/ESTAB: Sendet FIN und wechselt zu FIN_WAIT_1
        - CLOSE_WAIT: Sendet FIN (Antwort auf empfangenes FIN)
        - Andere Zustände: Bereits im Schließvorgang
        """
        _log(f"Close called, current state: {TCB_STATES[self.tcb.state]}", LOGLEVEL_INFO)
        if self.tcb.state == TCB.STATE_CLOSED:
            # If the user does not have access to such a connection, return "error: connection illegal for this process".
            _log("Cannot close: connection does not exist", LOGLEVEL_WARNING)
            return  # Silently ignore close on already closed socket
        elif self.tcb.state == TCB.STATE_LISTEN:
            # Any outstanding RECEIVEs are returned with "error: closing" responses. Delete TCB, enter CLOSED state, and return.
            _log("Closing from LISTEN state", LOGLEVEL_DEBUG)
            self._internal_close_call()
        elif self.tcb.state == TCB.STATE_SYN_SENT:
            # Delete the TCB and return "error: closing" responses to any queued SENDs, or RECEIVEs.
            _log("Closing from SYN_SENT state", LOGLEVEL_DEBUG)
            self._internal_close_call()
        elif self.tcb.state == TCB.STATE_SYN_RCVD:
            # If no SENDs have been issued and there is no pending data to send,
            # then form a FIN segment and send it, and enter FIN-WAIT-1 state;
            # otherwise queue for processing after entering ESTABLISHED state.
            _log("Closing from SYN_RCVD state: sending FIN segment", LOGLEVEL_DEBUG)
            self.send_segment(
                LoRaTCPSegment(self.tcb.socket_id, seq=self.tcb.snd_nxt, ack=self.tcb.rcv_nxt, ack_flag=True,
                               fin_flag=True))
        elif self.tcb.state == TCB.STATE_ESTAB:
            # Queue this until all preceding SENDs have been segmentized, then form a FIN segment and send it. In any case, enter FIN-WAIT-1 state.
            _log("Closing from ESTABLISHED state: sending FIN segment and entering FIN_WAIT_1", LOGLEVEL_DEBUG)
            self.send_segment(
                LoRaTCPSegment(self.tcb.socket_id, seq=self.tcb.snd_nxt, ack=self.tcb.rcv_nxt, ack_flag=True,
                               fin_flag=True))
            self.tcb.state = TCB.STATE_FIN_WAIT_1
            _log(f"State changed to FIN_WAIT_1", LOGLEVEL_INFO)
        elif self.tcb.state in [TCB.STATE_FIN_WAIT_1, TCB.STATE_FIN_WAIT_2]:
            _log("connection closing", LOGLEVEL_ERROR)
        elif self.tcb.state == TCB.STATE_CLOSE_WAIT:
            # Queue this request until all preceding SENDs have been segmentized; then send a FIN segment, enter CLOSING state.
            _log("Closing from CLOSE_WAIT state: sending FIN segment", LOGLEVEL_DEBUG)
            self.send_segment(
                LoRaTCPSegment(self.tcb.socket_id, seq=self.tcb.snd_nxt, ack=self.tcb.rcv_nxt, ack_flag=True,
                               fin_flag=True))
        elif self.tcb.state in [TCB.STATE_LAST_ACK, TCB.STATE_TIME_WAIT, TCB.STATE_CLOSING]:
            _log("connection closing", LOGLEVEL_ERROR)

    def add_lora_dataframe_to_queue(self, lora_dataframe: LoRaDataFrame):
        """
        Fügt einen empfangenen LoRa-Dataframe zur Verarbeitungsqueue hinzu.

        Diese Methode wird von der LoRaDataLink aufgerufen, um
        empfangene Datenrahmen an die entsprechende Socket-Instanz
        weiterzuleiten. Die Rahmen werden in run() verarbeitet.

        Args:
            lora_dataframe: Der empfangene LoRa-Datenrahmen
        """
        _log(f"Adding LoRa dataframe to queue: payload_length={len(lora_dataframe.payload)}", LOGLEVEL_DEBUG)
        self._incoming_dataframes.append(lora_dataframe)
        _log(f"Queue length after addition: {len(self._incoming_dataframes)}", LOGLEVEL_DEBUG)

    def _internal_close_call(self):
        """
        Führt interne Aufräumarbeiten beim Schließen durch.

        Private Methode für ordnungsgemäße Ressourcenfreigabe:
        - Löscht TCB (Transmission Control Block)
        - Leert Retransmission Queue
        - Entfernt Socket aus LoRaDataLink-Verwaltung
        - Entfernt Instanz aus globaler Liste
        """
        _log("Performing internal close call", LOGLEVEL_DEBUG)
        _log(f"Cleaning up TCB: retransmission_queue_length={len(self.tcb.retransmission_queue)}", LOGLEVEL_DEBUG)
        self.tcb.delete()
        self._data_link.remove_socket(self)
        _log("Socket removed from data link", LOGLEVEL_DEBUG)
        LoRaTCP.INSTANCES.remove(self)
        _log(f"Instance removed from global list. Remaining instances: {len(LoRaTCP.INSTANCES)}", LOGLEVEL_INFO)

    def _check_time_wait_timer(self):
        """
        Überprüft den Time-Wait Timer für TCP-Verbindungsabbau.
        """
        # If the time-wait timeout expires on a connection delete the TCB, enter the CLOSED state and return.
        if self.tcb.time_wait_timer is None:
            return

        elapsed = time.ticks_diff(time.ticks_ms(), self.tcb.time_wait_timer)
        if elapsed > TCB.TIME_WAIT_TIMEOUT_MS:
            _log(f"Time-wait timer expired after {elapsed}ms (timeout: {TCB.TIME_WAIT_TIMEOUT_MS}ms)", LOGLEVEL_INFO)
            self.tcb.state = TCB.STATE_CLOSED
            self._internal_close_call()

    def _check_retransmission_timer(self):
        """
        Überprüft den Retransmission Timer für zuverlässige Übertragung.
        """

        # For any state if the retransmission timeout expires on a segment in the retransmission queue,
        # send the segment at the front of the retransmission queue again,
        # reinitialize the retransmission timer,
        # and return.
        if self.tcb.retransmission_timeout_timer is None:
            return

        elapsed = time.ticks_diff(time.ticks_ms(), self.tcb.retransmission_timeout_timer)
        if elapsed > TCB.RETRANSMISSION_TIMEOUT_MS:
            _log(f"Retransmission timer expired after {elapsed}ms (timeout: {TCB.RETRANSMISSION_TIMEOUT_MS}ms)",
                 LOGLEVEL_WARNING)
            if len(self.tcb.retransmission_queue) > 0:
                segment = self.tcb.retransmission_queue.popleft()  # type: LoRaTCPSegment
                self.tcb.retransmission_queue.appendleft(
                    segment)  # Peek Left TODO möglicherweise Thread safe implementieren

                if segment.seq == self._last_retransmission_sequence_number:
                    self._retransmission_attempts += 1
                else:
                    self._last_retransmission_sequence_number = segment.seq
                    self._retransmission_attempts = 0

                _log(
                    f"Attempt {self._retransmission_attempts} retransmitting segment: seq={segment.seq}, payload_len={len(segment.payload)}",
                    LOGLEVEL_INFO)

                if self._retransmission_attempts >= LoRaTCP.MAX_RETRANSMISSION_ATTEMPTS:
                    _log("Retransmission attempt limit reached. Sending RST", LOGLEVEL_WARNING)
                    new_seg = LoRaTCPSegment(segment.socket_id, seq=self.tcb.snd_nxt, rst_flag=True)
                    self.send_segment(new_seg)
                    self.close()

                if not segment.syn_flag:
                    segment.ack = self.tcb.rcv_nxt
                    segment.ack_flag = True
                self.send_segment(segment, is_retransmission=True)
                self.tcb.start_retransmission_timeout_timer()
                _log("Retransmission timer restarted", LOGLEVEL_DEBUG)
            else:
                self.tcb.retransmission_timeout_timer = None

    def run(self):
        """
        Hauptverarbeitungsschleife der LoRaTCP-Instanz.

        Diese Methode sollte regelmäßig aufgerufen werden (Polling-basiert)
        und verarbeitet alle anstehenden Aufgaben:

        - Verarbeitung eingehender LoRa-Datenframes aus der Queue
        - Deserialisierung und Validierung von TCP-Segmenten
        - Ausführung der TCP-Zustandsmaschine
        - Datenreassemblierung für die Anwendungsschicht
        - Senden gepufferter Daten in ESTABLISHED-Zuständen
        - Überwachung und Verarbeitung von Timern (Retransmission, Time-Wait)

        Die Methode ist darauf ausgelegt, effizient ohne Blockierung zu arbeiten
        und sollte in der Hauptschleife des Netzwerk-Threads aufgerufen werden.
        """
        current_time = time.ticks_ms()
        time_since_last_run = time.ticks_diff(current_time, self._last_run)
        # _log(f"Run method called, time since last run: {time_since_last_run}ms", LOGLEVEL_DEBUG)

        if time_since_last_run > 1000:
            _log("Last data handling occurred more than 1000 ms ago!", LOGLEVEL_WARNING)
        self._last_run = current_time

        # Process incoming dataframes
        incoming_count = len(self._incoming_dataframes)
        if incoming_count > 0:
            _log(f"Processing {incoming_count} incoming dataframes", LOGLEVEL_DEBUG)

        processed_frames = 0
        while len(self._incoming_dataframes) > 0:
            lora_dataframe: LoRaDataFrame = self._incoming_dataframes.pop(0)
            _log(f"Processing dataframe {processed_frames + 1}: payload_length={len(lora_dataframe.payload)}",
                 LOGLEVEL_DEBUG)

            try:
                # Parse TCP segment with error handling for malformed data
                seg = LoRaTCPSegment.from_bytes(lora_dataframe.payload)  # type: LoRaTCPSegment
                _log(
                    f"Parsed TCP segment: socket_id={seg.socket_id}, seq={seg.seq}, ack={seg.ack}, flags=SYN:{seg.syn_flag},ACK:{seg.ack_flag},FIN:{seg.fin_flag},RST:{seg.rst_flag}",
                    LOGLEVEL_DEBUG)

                # Validate segment basic constraints
                if not self._validate_segment(seg):
                    _log(f"Segment validation failed, dropping segment", LOGLEVEL_WARNING)
                    processed_frames += 1
                    continue

                self.handle_event_segment_arrives(seg)
                processed_frames += 1

            except (ValueError, IndexError) as e:
                _log(f"Error parsing segment from dataframe: {e}, dropping segment", LOGLEVEL_ERROR)
                processed_frames += 1
                continue
            except Exception as e:
                _log(f"Unexpected error processing segment: {e}", LOGLEVEL_ERROR)
                processed_frames += 1
                continue

        if processed_frames > 0:
            _log(f"Processed {processed_frames} incoming dataframes", LOGLEVEL_INFO)

        segments_sent = 0
        if self.tcb.state in [TCB.STATE_ESTAB, TCB.STATE_CLOSE_WAIT, TCB.STATE_FIN_WAIT_1]:
            # Process send buffer
            send_buffer_len = len(self.tcb.send_buffer)
            if send_buffer_len > 0:
                _log(f"Processing send buffer: {send_buffer_len} bytes pending", LOGLEVEL_DEBUG)

            while len(self.tcb.send_buffer) > 0:
                with self.tcb.send_buffer_lock:
                    payload_len = min(self.tcb.snd_wnd, len(self.tcb.send_buffer))
                    payload = self.tcb.send_buffer[:payload_len]
                    self.tcb.send_buffer = self.tcb.send_buffer[payload_len:]
                    _log(
                        f"Sending segment {segments_sent + 1}: payload_len={payload_len}, remaining_buffer={len(self.tcb.send_buffer)}",
                        LOGLEVEL_DEBUG)
                    new_seg = LoRaTCPSegment(self.tcb.socket_id, seq=self.tcb.snd_nxt, ack=self.tcb.rcv_nxt,
                                             ack_flag=True,
                                             payload=payload)
                    self.send_segment(new_seg)
                    segments_sent += 1

            if segments_sent > 0:
                _log(f"Sent {segments_sent} segments from send buffer", LOGLEVEL_INFO)

        # Check timers
        self._check_retransmission_timer()
        self._check_time_wait_timer()
        # _log(f"Run method completed: processed={processed_frames} frames, sent={segments_sent} segments", LOGLEVEL_DEBUG)

    def handle_event_segment_arrives(self, seg: LoRaTCPSegment):
        """
        Behandelt das Eintreffen eines TCP-Segments (RFC 793 State-Machine).

        Implementiert die vollständige TCP-Zustandsmaschine gemäß RFC 793
        und verarbeitet eingehende Segmente entsprechend dem aktuellen
        Verbindungszustand. Führt alle notwendigen Validierungen,
        Zustandsübergänge und Antworten durch.

        Args:
            seg: Das eingetroffene TCP-Segment

        Verarbeitung umfasst:
        - Zustandsspezifische Segment-Behandlung (CLOSED, LISTEN, SYN_SENT, etc.)
        - Sequenznummer-Validierung und Fenster-Prüfung
        - ACK-Verarbeitung und Retransmission Queue-Updates
        - RST-Behandlung für Verbindungsreset
        - SYN-Verarbeitung für Verbindungsaufbau
        - FIN-Verarbeitung für Verbindungsabbau
        - Datenextraktion und Pufferung für die Anwendung
        """
        state = self.tcb.state
        tcb = self.tcb
        _log(
            f"Handling segment arrival: socket_id={seg.socket_id}, seq={seg.seq}, ack={seg.ack}, current_state={TCB_STATES[state]}",
            LOGLEVEL_DEBUG)
        # _log(f"Segment flags: SYN={seg.syn_flag}, ACK={seg.ack_flag}, FIN={seg.fin_flag}, RST={seg.rst_flag}, payload_len={len(seg.payload)}", LOGLEVEL_DEBUG)

        # If the state is CLOSED (i.e., TCB does not exist) then
        if state == TCB.STATE_CLOSED:
            _log("Processing segment in CLOSED state", LOGLEVEL_DEBUG)
            # all data in the incoming segment is discarded.
            # An incoming segment containing a RST is discarded.
            # An incoming segment not containing a RST causes a RST to be sent in response.
            # The acknowledgment and sequence field values are selected to make
            # the reset sequence acceptable to the TCP that sent the offending segment.
            if seg.rst_flag:
                _log(f"STATE: CLOSED, Received Segment discarded because it contained RST flag: {seg}")
                return
            else:
                # If the ACK bit is off, sequence number zero is used,
                # <SEQ=0><ACK=SEG.SEQ+SEG.LEN><CTL=RST,ACK>
                if not seg.ack_flag:
                    ack = Seq(seg.seq) + Seq(seg.payload)
                    new_seg = LoRaTCPSegment(seg.socket_id, seq=Seq(0), ack=ack,
                                             rst_flag=True, ack_flag=True)
                    _log(
                        f"STATE: CLOSED, Received Segment discarded. It contained no RST and ACK flag so we are sending a RST reply with Seq 0: {seg}")
                    _log(f"Sending RST reply: seq=0, ack={ack}", LOGLEVEL_DEBUG)
                    self.send_segment(new_seg)
                else:
                    # If the ACK bit is on,
                    # <SEQ=SEG.ACK><CTL=RST>
                    new_seg = LoRaTCPSegment(seg.socket_id, seq=seg.seq, rst_flag=True)
                    _log(
                        f"STATE: CLOSED, Received Segment discarded. It contained no RST flag so we are sending a RST reply with Seq SEG.SEQ: {seg}")
                    _log(f"Sending RST reply: seq={seg.seq}", LOGLEVEL_DEBUG)
                    self.send_segment(new_seg)
            return
        # If the state is LISTEN then
        elif state == TCB.STATE_LISTEN:
            _log("Processing segment in LISTEN state", LOGLEVEL_DEBUG)
            # Dies ist das erste Segment und enthält im Payload Remote-IP und Port

            # first check for an RST
            if seg.rst_flag:
                # An incoming RST should be ignored. Return.
                _log(f"STATE: LISTEN, Received Segment discarded because it contained RST flag: {seg}")
                return

            # second check for an ACK
            if seg.ack_flag:
                # Any acknowledgment is bad if it arrives on a connection still in the LISTEN state.
                # An acceptable reset segment should be formed for any arriving ACK-bearing segment.
                # The RST should be formatted as follows:  <SEQ=SEG.ACK><CTL=RST>
                # Quelle: RFC 793, p. 65
                new_seg = LoRaTCPSegment(seg.socket_id, seq=seg.ack, rst_flag=True)
                _log(f"STATE: LISTEN, Received Segment discarded because it contained ACK flag: {seg}")
                _log(f"Sending RST reply for unexpected ACK: seq={seg.ack}", LOGLEVEL_DEBUG)
                self.send_segment(new_seg)
                return
            # third check for a SYN
            if seg.syn_flag:
                _log("Processing SYN in LISTEN state", LOGLEVEL_INFO)
                # If the SYN bit is set, check the security.
                # If the security/compartment on the incoming segment does not exactly
                # match the security/compartment in the TCB then send a reset and return.
                # <SEQ=SEG.ACK><CTL=RST>
                # Ignorieren haben wir nicht

                # If the SEG.PRC is greater than the TCB.PRC then if allowed by the user
                # and the system set TCB.PRC<-SEG.PRC, if not allowed send a reset and return.
                # <SEQ=SEG.ACK><CTL=RST>
                # If the SEG.PRC is less than the TCB.PRC then continue.
                # Ignorieren haben wir nicht

                # Set RCV.NXT to SEG.SEQ+1, IRS [Initial receive sequence number] is set to SEG.SEQ
                # and any other control or text should be queued for processing later.
                # Wir müssen remote-ip und remote-port acken!
                self.tcb.rcv_nxt = Seq(seg.seq) + len(seg.payload) + 1
                self.tcb.irs = seg.seq
                _log(f"STATE: LISTEN, SYN received: RCV.NXT={self.tcb.rcv_nxt}, IRS={seg.seq}: {seg}")
                # ISS should be selected and a SYN segment sent of the form:
                #   <SEQ=ISS><ACK=RCV.NXT><CTL=SYN,ACK>
                new_seg = LoRaTCPSegment(seg.socket_id,
                                         seq=Seq(self.tcb.iss), ack=self.tcb.rcv_nxt,
                                         syn_flag=True, ack_flag=True)
                _log(f"Sending SYN-ACK reply: seq={self.tcb.iss}, ack={self.tcb.rcv_nxt}", LOGLEVEL_DEBUG)
                self.send_segment(new_seg)
                # SND.NXT is set to ISS+1 and SND.UNA to ISS.
                self.tcb.snd_nxt = Seq(self.tcb.iss) + 1
                self.tcb.snd_una = self.tcb.iss
                _log(f"STATE: LISTEN, SYN received: SND.NXT={self.tcb.snd_nxt}, SND.UNA={self.tcb.snd_una}")

                # The connection state should be changed to SYN-RECEIVED.
                self.tcb.state = TCB.STATE_SYN_RCVD
                _log(f"STATE: LISTEN, SYN received: Set STATE=SYN_RCVD")
                # Note that any other incoming control or data (combined with SYN)
                # will be processed in the SYN-RECEIVED state,
                # but processing of SYN and ACK should not be repeated.

                # If the listen was not fully specified (i.e., the foreign socket was not fully specified),
                # then the unspecified fields should be filled in now.
                # Quelle: RFC 793, p. 66
                host = int_to_ip(int.from_bytes(seg.payload[:4], 'big'))
                port = int.from_bytes(seg.payload[4:6], 'big')
                self.tcb.socket_id = seg.socket_id
                self.tcb.remote_ip = host
                self.tcb.remote_port = port
                _log(f"STATE: LISTEN, SYN received: remote ip={host}, remote port={port}, socket_id={seg.socket_id}")
                self._data_link.register_syn_sent_socket(self)
                _log("Socket registered as SYN_RCVD with data link", LOGLEVEL_DEBUG)

            # fourth other text or control
            # Any other control or text-bearing segment (not containing SYN) must have an ACK and
            # thus would be discarded by the ACK processing. An incoming RST segment could not be valid,
            # since it could not have been sent in response to anything sent by this incarnation of the connection.
            # So you are unlikely to get here, but if you do, drop the segment, and return.
            return

        # If the state is SYN-SENT then
        elif state == TCB.STATE_SYN_SENT:
            _log("Processing segment in SYN_SENT state", LOGLEVEL_DEBUG)
            ack_acceptable = False

            # first check the ACK bit
            if seg.ack_flag:
                _log(f"Checking ACK in SYN_SENT: seg.ack={seg.ack}, iss={tcb.iss}, snd_nxt={tcb.snd_nxt}",
                     LOGLEVEL_DEBUG)
                # If SEG.ACK =< ISS, or SEG.ACK > SND.NXT,
                if Seq(seg.ack) <= Seq(tcb.iss) or Seq(seg.ack) > Seq(tcb.snd_nxt):
                    _log(f"ACK out of range: {seg.ack} not in ({tcb.iss}, {tcb.snd_nxt}]", LOGLEVEL_WARNING)
                    # send a reset (unless the RST bit is set, if so drop the segment and return)
                    # <SEQ=SEG.ACK><CTL=RST>
                    if not seg.rst_flag:
                        new_seg = LoRaTCPSegment(seg.socket_id, seq=seg.ack, rst_flag=True)
                        _log(f"Sending RST for unacceptable ACK: seq={seg.ack}", LOGLEVEL_DEBUG)
                        self.send_segment(new_seg)
                    # and discard the segment. Return.
                    # Quelle:  RFC 793, p. 66
                    return
                # If SND.UNA =< SEG.ACK =< SND.NXT then the ACK is acceptable.
                ack_acceptable = self.tcb.is_ack_acceptable(seg.ack)
                _log(f"ACK acceptability check: {ack_acceptable}", LOGLEVEL_DEBUG)

            # second check the RST bit
            if seg.rst_flag:
                _log("Processing RST in SYN_SENT state", LOGLEVEL_WARNING)
                # If the ACK was acceptable then signal the user "error: connection reset",
                # drop the segment, enter CLOSED state, delete TCB, and return.
                if ack_acceptable:
                    _log("error: connection reset", LOGLEVEL_ERROR)
                    self.tcb.state = TCB.STATE_CLOSED
                    self._internal_close_call()
                    return
                else:  # Otherwise (no ACK) drop the segment and return.
                    _log("RST received but ACK not acceptable, dropping segment", LOGLEVEL_DEBUG)
                    return
            # third check the security and precedence  If the security/compartment in the segment does not exactly match the security/compartment in the TCB, send a reset  If there is an ACK  <SEQ=SEG.ACK><CTL=RST>  Otherwise  <SEQ=0><ACK=SEG.SEQ+SEG.LEN><CTL=RST,ACK>  If there is an ACK  The precedence in the segment must match the precedence in the TCB, if not, send a reset  <SEQ=SEG.ACK><CTL=RST>  If there is no ACK  If the precedence in the segment is higher than the precedence in the TCB then if allowed by the user and the system raise the precedence in the TCB to that in the segment, if not allowed to raise the prec then send a reset.  <SEQ=0><ACK=SEG.SEQ+SEG.LEN><CTL=RST,ACK>  If the precedence in the segment is lower than the precedence in the TCB continue.  If a reset was sent, discard the segment and continue.

            # fourth check the SYN bit
            # This step should be reached only if the ACK is ok, or there is no ACK, and it the segment did not contain a RST.
            # If the SYN bit is on and the security/compartment and precedence are acceptable then
            if seg.syn_flag:
                _log("Processing SYN in SYN_SENT state", LOGLEVEL_INFO)
                # RCV.NXT is set to SEG.SEQ+1, IRS is set to SEG.SEQ.
                self.tcb.rcv_nxt = seg.seq + 1
                self.tcb.irs = seg.seq
                _log(f"Updated receive variables: rcv_nxt={self.tcb.rcv_nxt}, irs={self.tcb.irs}", LOGLEVEL_DEBUG)
                if seg.ack_flag:
                    # SND.UNA should be advanced to equal SEG.ACK (if there is an ACK),
                    self.tcb.snd_una = seg.ack
                    _log(f"Updated snd_una to {self.tcb.snd_una}", LOGLEVEL_DEBUG)
                    # and any segments on the retransmission queue which are thereby acknowledged should be removed.
                    removed_count = len(self.tcb.retransmission_queue)
                    self.tcb.remove_acknowledged_segments_from_retransmission_queue()
                    removed_count -= len(self.tcb.retransmission_queue)
                    if removed_count > 0:
                        _log(f"Removed {removed_count} acknowledged segments from retransmission queue", LOGLEVEL_DEBUG)

                if self.tcb.iss < self.tcb.snd_una:
                    # If SND.UNA > ISS (our SYN has been ACKed),
                    # change the connection state to ESTABLISHED, form an ACK segment and send it
                    # <SEQ=SND.NXT><ACK=RCV.NXT><CTL=ACK>
                    # Data or controls which were queued for transmission may be included.
                    _log("SYN ACKed, transitioning to ESTABLISHED state", LOGLEVEL_INFO)
                    self.tcb.state = TCB.STATE_ESTAB
                    with self.tcb.send_buffer_lock:
                        payload_len = min(len(self.tcb.send_buffer), self.tcb.snd_wnd)
                        payload = self.tcb.send_buffer[:payload_len]
                        self.tcb.send_buffer = self.tcb.send_buffer[payload_len:]
                        _log(
                            f"Sending ACK with payload: payload_len={payload_len}, remaining_buffer={len(self.tcb.send_buffer)}",
                            LOGLEVEL_DEBUG)
                        new_seg = LoRaTCPSegment(seg.socket_id, seq=self.tcb.snd_nxt, ack=self.tcb.rcv_nxt,
                                                 ack_flag=True, payload=payload)
                        self.send_segment(new_seg)
                else:
                    # Otherwise enter SYN-RECEIVED, form a SYN,ACK segment
                    # <SEQ=ISS><ACK=RCV.NXT><CTL=SYN,ACK>
                    # Dieses Segment kann nur ein Sensor empfangen. Dieser Zustand wird jedoch nie erreicht,
                    # weil die Basisstation immer mit einem SYN, ACK antworten wird.
                    _log("Entering SYN_RCVD state (unusual case)", LOGLEVEL_WARNING)
                    self.tcb.state = TCB.STATE_SYN_RCVD
                    new_seg = LoRaTCPSegment(seg.socket_id, seq=Seq(self.tcb.iss), ack=self.tcb.rcv_nxt,
                                             ack_flag=True)
                    self.send_segment(new_seg)
            return

        else:  # Otherwise,
            _log(f"Processing segment in state {TCB_STATES[state]}", LOGLEVEL_DEBUG)
            # Track if FIN was acknowledged in this segment for proper state transitions
            fin_was_acked = False
            # first check sequence number
            if state in [TCB.STATE_SYN_RCVD, TCB.STATE_ESTAB,
                         TCB.STATE_FIN_WAIT_1, TCB.STATE_FIN_WAIT_2,
                         TCB.STATE_CLOSE_WAIT, TCB.STATE_CLOSING,
                         TCB.STATE_LAST_ACK, TCB.STATE_TIME_WAIT]:
                # Segments are processed in sequence.
                # Initial tests on arrival are used to discard old duplicates,
                # but further processing is done in SEG.SEQ order.
                # If a segment's contents straddle the boundary between old and new,
                # only the new parts should be processed.

                # There are four cases for the acceptability test for an incoming segment:
                acceptable = self.check_if_segment_is_in_receive_window(seg)
                _log(
                    f"Sequence number acceptability check: {acceptable} (seq={seg.seq}, rcv_nxt={self.tcb.rcv_nxt}, rcv_wnd={self.tcb.rcv_wnd})",
                    LOGLEVEL_DEBUG)

                # If the RCV.WND is zero, no segments will be acceptable,
                # but special allowance should be made to accept valid ACKs, URGs and RSTs.
                if self.tcb.rcv_wnd == 0:
                    acceptable = False

                if not acceptable:
                    _log("Segment not acceptable, checking for special cases", LOGLEVEL_DEBUG)
                    if self.tcb.is_ack_acceptable(seg.ack):
                        _log(f"ACK is acceptable, updating snd_una: {self.tcb.snd_una} -> {seg.ack}", LOGLEVEL_DEBUG)
                        self.tcb.snd_una = seg.ack
                        self.tcb.remove_acknowledged_segments_from_retransmission_queue()
                    if seg.rst_flag and self.tcb.rcv_nxt <= seg.seq < (self.tcb.rcv_nxt + self.tcb.rcv_wnd):
                        _log("RST in acceptable range, closing connection", LOGLEVEL_WARNING)
                        self.tcb.state = TCB.STATE_CLOSED
                        self._internal_close_call()
                        return
                    # If an incoming segment is not acceptable,
                    # an acknowledgment should be sent in reply (unless the RST bit is set, if so drop the segment and return):
                    # <SEQ=SND.NXT><ACK=RCV.NXT><CTL=ACK>

                    if not acceptable and not seg.rst_flag:
                        _log("Sending ACK for unacceptable segment", LOGLEVEL_DEBUG)
                        # new_seg = LoRaTCPSegment(seg.socket_id, seq=self.tcb.snd_nxt, rst_flag=True)
                        new_seg = LoRaTCPSegment(seg.socket_id, seq=self.tcb.snd_nxt, ack=self.tcb.rcv_nxt,
                                                 ack_flag=True)
                        self.send_segment(new_seg)
                        # After sending the acknowledgment, drop the unacceptable segment and return.
                        return
                    return
            # second check the RST bit,
            if state == TCB.STATE_SYN_RCVD:
                if seg.rst_flag:
                    _log("Processing RST in SYN_RCVD state", LOGLEVEL_WARNING)
                    # If this connection was initiated with a passive OPEN (i.e., came from the LISTEN state),
                    # then return this connection to LISTEN state and return.
                    if not self.tcb.active_open:
                        _log("Passive connection reset, returning to LISTEN state", LOGLEVEL_INFO)
                        self.tcb.state = TCB.STATE_LISTEN
                        self.tcb.retransmission_queue = deque(maxlen=20)
                        gc.collect()
                        return
                        # The user need not be informed.
                    else:
                        # If this connection was initiated with an active OPEN (i.e., came from SYN-SENT state)
                        # then the connection was refused, signal the user "connection refused".
                        _log("connection refused", LOGLEVEL_WARNING)
                        self.tcb.state = TCB.STATE_CLOSED
                        self._internal_close_call()
                        return
                    # In either case, all segments on the retransmission queue should be removed.
                    # And in the active OPEN case, enter the CLOSED state and delete the TCB, and return.
            elif tcb.state in [TCB.STATE_ESTAB, TCB.STATE_FIN_WAIT_1, TCB.STATE_FIN_WAIT_2, TCB.STATE_CLOSE_WAIT]:
                # If the RST bit is set then, any outstanding RECEIVEs and SEND should receive "reset" responses.
                # All segment queues should be flushed.
                # Users should also receive an unsolicited general "connection reset" signal.
                # Enter the CLOSED state, delete the TCB, and return.
                if seg.rst_flag:
                    _log(f"RST received in state {TCB_STATES[self.tcb.state]}, closing connection", LOGLEVEL_WARNING)
                    tcb.state = TCB.STATE_CLOSED
                    self._internal_close_call()
                    return
            elif tcb.state in [TCB.STATE_CLOSING, TCB.STATE_LAST_ACK, TCB.STATE_TIME_WAIT]:
                # If the RST bit is set then, enter the CLOSED state, delete the TCB, and return.
                if seg.rst_flag:
                    _log(f"RST received in closing state {TCB_STATES[self.tcb.state]}", LOGLEVEL_INFO)
                    tcb.state = TCB.STATE_CLOSED
                    self._internal_close_call()
                    return
            # third check security and precedence
            # ignoring this

            # fourth, check the SYN bit,
            if tcb.state in [TCB.STATE_SYN_RCVD, TCB.STATE_ESTAB,
                             TCB.STATE_FIN_WAIT_1, TCB.STATE_FIN_WAIT_2,
                             TCB.STATE_CLOSE_WAIT, TCB.STATE_CLOSING,
                             TCB.STATE_LAST_ACK, TCB.STATE_TIME_WAIT]:
                # If the SYN is in the window it is an error, send a reset,
                # any outstanding RECEIVEs and SEND should receive "reset" responses,
                # all segment queues should be flushed, the user should also receive
                # an unsolicited general "connection reset" signal, enter the CLOSED state,
                # delete the TCB, and return.
                if self.is_syn_in_window(seg):
                    _log("SYN in window detected, sending RST and closing connection", LOGLEVEL_ERROR)
                    new_seg = LoRaTCPSegment(seg.socket_id, seq=tcb.snd_nxt, rst_flag=True)
                    self.send_segment(new_seg)
                    tcb.state = TCB.STATE_CLOSED
                    self._internal_close_call()
                    return
                # If the SYN is not in the window this step would not be reached and an
                # ack would have been sent in the first step (sequence number check).
            # fifth check the ACK field,
            if not seg.ack_flag:
                # if the ACK bit is off drop the segment and return
                _log("No ACK flag, dropping segment", LOGLEVEL_DEBUG)
                return
            elif tcb.state == TCB.STATE_SYN_RCVD:
                _log("Processing ACK in SYN_RCVD state", LOGLEVEL_DEBUG)
                # If SND.UNA =< SEG.ACK =< SND.NXT then enter ESTABLISHED state and continue processing.
                if tcb.snd_una <= seg.ack <= tcb.snd_nxt:
                    _log("ACK acceptable, transitioning to ESTABLISHED state", LOGLEVEL_INFO)
                    tcb.state = TCB.STATE_ESTAB
                    if not tcb.is_ack_acceptable(seg.ack):
                        _log("ACK not acceptable despite being in range, sending RST", LOGLEVEL_WARNING)
                        new_seg = LoRaTCPSegment(seg.socket_id, seq=seg.ack, rst_flag=True)
                        self.send_segment(new_seg)
            elif tcb.state in [TCB.STATE_ESTAB, TCB.STATE_CLOSE_WAIT]:
                _log(f"Processing ACK in {TCB_STATES[self.tcb.state]} state", LOGLEVEL_DEBUG)
                # If SND.UNA < SEG.ACK =< SND.NXT then, set SND.UNA <- SEG.ACK.
                if tcb.snd_una <= seg.ack <= tcb.snd_nxt:
                    # Any segments on the retransmission queue which are thereby entirely acknowledged are removed.
                    # Users should receive positive acknowledgments for buffers which have been SENT
                    # and fully acknowledged (i.e., SEND buffer should be returned with "ok" response).
                    # If the ACK is a duplicate (SEG.ACK < SND.UNA), it can be ignored.
                    if seg.ack < tcb.snd_una:
                        _log(f"Ignored duplicate ACK SEG.ACK({seg.ack}) < SND.UNA({tcb.snd_una})", LOGLEVEL_DEBUG)
                    old_snd_una = tcb.snd_una
                    tcb.snd_una = seg.ack
                    _log(f"Updated snd_una: {old_snd_una} -> {tcb.snd_una}", LOGLEVEL_DEBUG)
                    removed_count = len(tcb.retransmission_queue)
                    tcb.remove_acknowledged_segments_from_retransmission_queue()
                    removed_count -= len(tcb.retransmission_queue)
                    if removed_count > 0:
                        _log(f"Removed {removed_count} acknowledged segments from retransmission queue", LOGLEVEL_DEBUG)

                # If the ACK acks something not yet sent (SEG.ACK > SND.NXT) then send an ACK,
                # drop the segment, and return.
                if seg.ack > tcb.snd_nxt:
                    _log(f"ACK for unsent data: {seg.ack} > {tcb.snd_nxt}, dropping", LOGLEVEL_WARNING)
                    return
                #
                # Ignoring Send windows If SND.UNA < SEG.ACK =< SND.NXT, the send window should be updated.
                #   If (SND.WL1 < SEG.SEQ or (SND.WL1 = SEG.SEQ and SND.WL2 =< SEG.ACK)),
                #   set SND.WND <- SEG.WND, set SND.WL1 <- SEG.SEQ, and set SND.WL2 <- SEG.ACK.
                #   Note that SND.WND is an offset from SND.UNA, that SND.WL1 records the sequence number
                #   of the last segment used to update SND.WND, and that SND.WL2 records the acknowledgment number
                #   of the last segment used to update SND.WND. The check here prevents using old segments to update the window.
            elif tcb.state in [TCB.STATE_FIN_WAIT_1, TCB.STATE_FIN_WAIT_2]:
                _log(f"Processing ACK in {TCB_STATES[self.tcb.state]} state", LOGLEVEL_DEBUG)

                # In addition to the processing for the ESTABLISHED state,
                # ######## ESTAB Processing #########
                # If SND.UNA < SEG.ACK =< SND.NXT then, set SND.UNA <- SEG.ACK.
                if tcb.snd_una <= seg.ack <= tcb.snd_nxt:
                    # Any segments on the retransmission queue which are thereby entirely acknowledged are removed.
                    # Users should receive positive acknowledgments for buffers which have been SENT
                    # and fully acknowledged (i.e., SEND buffer should be returned with "ok" response).
                    old_snd_una = tcb.snd_una
                    tcb.snd_una = seg.ack
                    _log(f"Updated snd_una: {old_snd_una} -> {tcb.snd_una}", LOGLEVEL_DEBUG)
                    tcb.remove_acknowledged_segments_from_retransmission_queue()

                    # Check if this ACK acknowledges our FIN (only for FIN_WAIT_1)
                    if tcb.state == TCB.STATE_FIN_WAIT_1 and self.is_fin_acknowledged():
                        fin_was_acked = True
                        _log("FIN acknowledged, transitioning to FIN_WAIT_2", LOGLEVEL_INFO)
                        tcb.state = TCB.STATE_FIN_WAIT_2

                # If the ACK is a duplicate (SEG.ACK < SND.UNA), it can be ignored.
                # if seg.ack < tcb.snd_una:

                # If the ACK acks something not yet sent (SEG.ACK > SND.NXT) then send an ACK,
                # drop the segment, and return.
                if seg.ack > tcb.snd_nxt:
                    _log(f"ACK for unsent data in FIN_WAIT: {seg.ack} > {tcb.snd_nxt}", LOGLEVEL_WARNING)
                    return
                # ######## ESTAB Processing End #########
                if tcb.state == TCB.STATE_FIN_WAIT_2:
                    # In addition to the processing for the ESTABLISHED state,
                    # ######## ESTAB Processing #########
                    # If SND.UNA < SEG.ACK =< SND.NXT then, set SND.UNA <- SEG.ACK.
                    if tcb.snd_una <= seg.ack <= tcb.snd_nxt:
                        # Any segments on the retransmission queue which are thereby entirely acknowledged are removed.
                        # Users should receive positive acknowledgments for buffers which have been SENT
                        # and fully acknowledged (i.e., SEND buffer should be returned with "ok" response).
                        tcb.snd_una = seg.ack
                        tcb.remove_acknowledged_segments_from_retransmission_queue()
                    # If the ACK is a duplicate (SEG.ACK < SND.UNA), it can be ignored.
                    # if seg.ack < tcb.snd_una:

                    # If the ACK acks something not yet sent (SEG.ACK > SND.NXT) then send an ACK,
                    # drop the segment, and return.
                    if seg.ack > tcb.snd_nxt:
                        return
                    # ######## ESTAB Processing End #########
                    # if the retransmission queue is empty,
                    # the user's CLOSE can be acknowledged ("ok") but do not delete the TCB.
                    pass
            elif tcb.state == TCB.STATE_CLOSING:
                _log("Processing ACK in CLOSING state", LOGLEVEL_DEBUG)
                # In addition to the processing for the ESTABLISHED state,
                # ######## ESTAB Processing #########
                # If SND.UNA < SEG.ACK =< SND.NXT then, set SND.UNA <- SEG.ACK.
                if tcb.snd_una <= seg.ack <= tcb.snd_nxt:
                    # Any segments on the retransmission queue which are thereby entirely acknowledged are removed.
                    # Users should receive positive acknowledgments for buffers which have been SENT
                    # and fully acknowledged (i.e., SEND buffer should be returned with "ok" response).
                    tcb.snd_una = seg.ack
                    tcb.remove_acknowledged_segments_from_retransmission_queue()
                # If the ACK is a duplicate (SEG.ACK < SND.UNA), it can be ignored.
                # if seg.ack < tcb.snd_una:

                # If the ACK acks something not yet sent (SEG.ACK > SND.NXT) then send an ACK,
                # drop the segment, and return.
                if seg.ack > tcb.snd_nxt:
                    return
                # ######## ESTAB Processing End #########
                # if the ACK acknowledges our FIN then enter the TIME-WAIT state, otherwise ignore the segment.
                if self.is_fin_acknowledged():
                    _log("FIN acknowledged in CLOSING state, transitioning to TIME_WAIT", LOGLEVEL_INFO)
                    tcb.state = TCB.STATE_TIME_WAIT
            elif tcb.state == TCB.STATE_LAST_ACK:
                _log("Processing ACK in LAST_ACK state", LOGLEVEL_DEBUG)
                # The only thing that can arrive in this state is an acknowledgment of our FIN.
                # If our FIN is now acknowledged, delete the TCB, enter the CLOSED state, and return.
                if self.is_fin_acknowledged():
                    _log("FIN acknowledged in LAST_ACK state, closing connection", LOGLEVEL_INFO)
                    tcb.state = TCB.STATE_CLOSED
                    self._internal_close_call()
                    return
            elif tcb.state == TCB.STATE_TIME_WAIT:
                _log("Processing ACK in TIME_WAIT state", LOGLEVEL_DEBUG)
                # The only thing that can arrive in this state is a retransmission of the remote FIN.
                # Acknowledge it, and restart the 2 MSL timeout.
                tcb.MSL_TIMEOUT_MS = time.ticks_ms()
                _log("Restarted MSL timeout in TIME_WAIT", LOGLEVEL_DEBUG)
                new_seg = LoRaTCPSegment(seg.socket_id, seq=tcb.snd_nxt, ack=tcb.rcv_nxt, ack_flag=True)
                pass
            # sixth, check the URG bit,
            # ingoring this

            # seventh, process the segment text,
            if tcb.state in [TCB.STATE_ESTAB, TCB.STATE_FIN_WAIT_1, TCB.STATE_FIN_WAIT_2] and len(seg.payload) > 0:
                _log(
                    f"Processing segment payload in {TCB_STATES[self.tcb.state]} state: payload_len={len(seg.payload)}",
                    LOGLEVEL_DEBUG)
                # Once in the ESTABLISHED state, it is possible to deliver segment text to user RECEIVE buffers.
                # Text from segments can be moved into buffers until either the buffer is full or the segment is empty.
                # If the segment empties and carries an PUSH flag, then the user is informed, when the buffer is returned,
                # that a PUSH has been received.

                _log(f"Adding payload to receive buffer: seq={seg.seq}, len={len(seg.payload)}", LOGLEVEL_DEBUG)
                tcb.receive_buffer[seg.seq] = seg.payload

                # When the TCP takes responsibility for delivering the data to the user
                # it must also acknowledge the receipt of the data.

                # Once the TCP takes responsibility for the data it advances RCV.NXT over the data accepted,
                # and adjusts RCV.WND as apporopriate to the current buffer availability.
                # The total of RCV.NXT and RCV.WND should not be reduced.

                # new_rcv_nxt = seg.seq + len(seg.payload)
                # _log(f"Advancing rcv_nxt from {tcb.rcv_nxt} to {new_rcv_nxt}", LOGLEVEL_DEBUG)
                # tcb.rcv_nxt = new_rcv_nxt
                self._reassemble_received_data()

                # RCV.WND entsprechend der aktuellen Pufferverfügbarkeit anpassen
                # Normalerweise wird das Fenster um die Anzahl der gepufferten Bytes reduziert
                old_rcv_wnd = tcb.rcv_wnd
                tcb.rcv_wnd = LoRaTCP_MAX_PAYLOAD_SIZE - len(tcb.receive_buffer)
                if old_rcv_wnd != tcb.rcv_wnd:
                    _log(f"Updated receive window: {old_rcv_wnd} -> {tcb.rcv_wnd}", LOGLEVEL_DEBUG)

                # Send an acknowledgment of the form:  <SEQ=SND.NXT><ACK=RCV.NXT><CTL=ACK>
                # This acknowledgment should be piggybacked on a segment being transmitted if possible without incurring undue delay.
                with self.tcb.send_buffer_lock:
                    payload_len = min(len(self.tcb.send_buffer), tcb.snd_wnd)
                    # TODO Darf nur versendet werden wenn Daten empfangen wurden
                    payload = self.tcb.send_buffer[:payload_len]
                    self.tcb.send_buffer = self.tcb.send_buffer[payload_len:]
                    _log(f"Sending ACK with piggyback data: ack={tcb.rcv_nxt}, payload_len={payload_len}",
                         LOGLEVEL_DEBUG)
                    new_seg = LoRaTCPSegment(seg.socket_id, seq=tcb.snd_nxt, ack=tcb.rcv_nxt, ack_flag=True,
                                             payload=payload)
                    self.send_segment(new_seg)
            elif tcb.state in [TCB.STATE_CLOSE_WAIT, TCB.STATE_CLOSING, TCB.STATE_LAST_ACK, TCB.STATE_TIME_WAIT]:
                # This should not occur, since a FIN has been received from the remote side. Ignore the segment text.
                if len(seg.payload) > 0:
                    _log(
                        f"Ignoring payload in closing state {TCB_STATES[self.tcb.state]}: payload_len={len(seg.payload)}",
                        LOGLEVEL_WARNING)
                pass

            # eighth, check the FIN bit,
            if seg.fin_flag:
                _log(f"Processing FIN in state {TCB_STATES[self.tcb.state]}", LOGLEVEL_INFO)
                if tcb.state in [TCB.STATE_CLOSED, TCB.STATE_LISTEN, TCB.STATE_SYN_SENT]:
                    # Do not process the FIN if the state is CLOSED, LISTEN or SYN-SENT
                    # since the SEG.SEQ cannot be validated; drop the segment and return.
                    _log(f"Ignoring FIN in state {TCB_STATES[self.tcb.state]} (cannot validate sequence)",
                         LOGLEVEL_DEBUG)
                    return
                # If the FIN bit is set, signal the user "connection closing" and return any
                # pending RECEIVEs with same message, advance RCV.NXT over the FIN,
                # and send an acknowledgment for the FIN. Note that FIN implies PUSH for any
                # segment text not yet delivered to the user.
                if len(seg.payload) > 0:
                    _log(f"FIN with payload: adding {len(seg.payload)} bytes to receive buffer", LOGLEVEL_DEBUG)
                    tcb.receive_buffer[Seq(seg.seq)] = seg.payload
                    # Advance RCV.NXT over the payload
                    tcb.rcv_nxt = tcb.rcv_nxt + len(seg.payload)

                # Advance RCV.NXT over the FIN (FIN occupies 1 sequence number)
                old_rcv_nxt = tcb.rcv_nxt
                tcb.rcv_nxt = tcb.rcv_nxt + 1
                _log(f"Advanced RCV.NXT over FIN: {old_rcv_nxt} -> {tcb.rcv_nxt}", LOGLEVEL_DEBUG)
                # Send an acknowledgment for the FIN
                _log(f"Sending ACK for FIN: ack={tcb.rcv_nxt}", LOGLEVEL_DEBUG)
                new_seg = LoRaTCPSegment(seg.socket_id, seq=tcb.snd_nxt, ack=tcb.rcv_nxt, ack_flag=True)
                self.send_segment(new_seg)
                if tcb.state in [TCB.STATE_SYN_RCVD, TCB.STATE_ESTAB]:
                    _log(f"FIN received in {TCB_STATES[self.tcb.state]}, transitioning to CLOSE_WAIT", LOGLEVEL_INFO)
                    tcb.state = TCB.STATE_CLOSE_WAIT
                elif tcb.state == TCB.STATE_FIN_WAIT_1:
                    # If our FIN has been ACKed (perhaps in this segment), then enter TIME-WAIT,
                    # start the time-wait timer, turn off the other timers;
                    # Check if FIN was acknowledged in the current segment processing or previously
                    if fin_was_acked or self.is_fin_acknowledged():
                        _log("FIN received and our FIN ACKed in FIN_WAIT_1, transitioning to TIME_WAIT", LOGLEVEL_INFO)
                        tcb.state = TCB.STATE_TIME_WAIT
                        tcb.cancel_all_timers()
                        tcb.start_time_wait_timer()
                    # otherwise enter the CLOSING state.
                    else:
                        _log("FIN received in FIN_WAIT_1 but our FIN not ACKed, transitioning to CLOSING",
                             LOGLEVEL_INFO)
                        tcb.state = TCB.STATE_CLOSING
                elif tcb.state == TCB.STATE_FIN_WAIT_2:
                    # Enter the TIME-WAIT state. Start the time-wait timer, turn off the other timers.
                    _log("FIN received in FIN_WAIT_2, transitioning to TIME_WAIT", LOGLEVEL_INFO)
                    tcb.state = TCB.STATE_TIME_WAIT
                    tcb.cancel_all_timers()
                    tcb.start_time_wait_timer()
                elif tcb.state in [TCB.STATE_CLOSE_WAIT, TCB.STATE_CLOSING, TCB.STATE_LAST_ACK]:
                    _log(f"FIN received in {TCB_STATES[self.tcb.state]}, no state change", LOGLEVEL_DEBUG)
                    pass
                elif tcb.state == TCB.STATE_TIME_WAIT:
                    _log("FIN received in TIME_WAIT, restarting time-wait timer", LOGLEVEL_DEBUG)
                    tcb.start_time_wait_timer()
            return

    def send_segment(self, seg: LoRaTCPSegment, is_retransmission=False):
        """
        Sendet ein TCP-Segment über die LoRa-Datenverbindung.

        Serialisiert das TCP-Segment und übergibt es an die LoRaDataLink-Schicht.
        Verwaltet Retransmission Queue und aktualisiert Sequenznummern bei
        Erstübertragungen. Startet Timer für zuverlässige Übertragung.

        Args:
            seg: Das zu sendende TCP-Segment
            is_retransmission: True wenn es sich um eine Wiederholung handelt,
                             False für Erstübertragung (Standard)
        """
        _log(
            f"Sending segment: socket_id={seg.socket_id}, seq={seg.seq}, ack={seg.ack}, flags=SYN:{seg.syn_flag},ACK:{seg.ack_flag},FIN:{seg.fin_flag},RST:{seg.rst_flag}, payload_len={len(seg.payload)}",
            LOGLEVEL_DEBUG)

        segment_bytes = seg.to_bytes()
        _log(f"Segment serialized to {len(segment_bytes)} bytes", LOGLEVEL_DEBUG)
        self._data_link.add_to_send_queue(segment_bytes)

        # Zur Retransmission Queue hinzufügen (nur bei Erstübertragung)
        if not is_retransmission and (len(seg.payload) > 0 or seg.syn_flag or seg.fin_flag):
            _log(
                f"Adding segment to retransmission queue (payload_len={len(seg.payload)}, SYN={seg.syn_flag}, FIN={seg.fin_flag})",
                LOGLEVEL_DEBUG)
            self.tcb.retransmission_queue.append(seg)
            self.tcb.start_retransmission_timeout_timer()
            _log(f"Retransmission queue length: {len(self.tcb.retransmission_queue)}", LOGLEVEL_DEBUG)

        # SND.NXT aktualisieren (nur bei Erstübertragung)
        if not is_retransmission:
            old_snd_nxt = self.tcb.snd_nxt
            if len(seg.payload) > 0:
                self.tcb.snd_nxt = self.tcb.snd_nxt + len(seg.payload)
            if seg.fin_flag or seg.syn_flag:
                self.tcb.snd_nxt = self.tcb.snd_nxt + 1
                if seg.fin_flag:
                    self.tcb.fin_seq = seg.seq
                    _log(f"FIN sequence number recorded: {self.tcb.fin_seq}", LOGLEVEL_DEBUG)
            if old_snd_nxt != self.tcb.snd_nxt:
                _log(f"Updated SND.NXT: {old_snd_nxt} -> {self.tcb.snd_nxt}", LOGLEVEL_DEBUG)

    def is_fin_acknowledged(self) -> bool:
        """
        Prüft ob das gesendete FIN-Segment bestätigt wurde.

        Überprüft anhand der Sequenznummern (snd_una vs fin_seq), ob ein
        zuvor gesendetes FIN-Segment vom entfernten TCP bestätigt wurde. Wird für
        korrekte Zustandsübergänge während des Verbindungsabbaus benötigt.

        Returns:
            bool: True wenn FIN bestätigt wurde, False andernfalls
        """
        result = (self.tcb.fin_seq is not None and
                  self.tcb.snd_una > self.tcb.fin_seq)
        _log(f"FIN acknowledgment check: fin_seq={self.tcb.fin_seq}, snd_una={self.tcb.snd_una}, result={result}",
             LOGLEVEL_DEBUG)
        return result

    def is_syn_in_window(self, seg: LoRaTCPSegment) -> bool:
        """
        Prüft ob ein SYN-Segment im aktuellen Empfangsfenster liegt.

        Ein SYN-Segment im Empfangsfenster während einer etablierten
        Verbindung ist ein Protokollfehler und führt zum Connection Reset.
        Verwendet Sequenznummer-Arithmetik mit Wraparound-Behandlung durch Verwendung der Seq-Klasse.

        Args:
            seg: Das zu prüfende TCP-Segment

        Returns:
            bool: True wenn SYN im Fenster liegt (Fehler), False andernfalls
        """
        if not seg.syn_flag:
            return False

        rcv_nxt = self.tcb.rcv_nxt
        rcv_wnd = self.tcb.rcv_wnd

        # Sequence Number Arithmetic mit Wrap-around
        result = (Seq(rcv_nxt) <= Seq(seg.seq) <
                  Seq(rcv_nxt) + Seq(rcv_wnd))
        _log(f"SYN in window check: seq={seg.seq}, rcv_nxt={rcv_nxt}, rcv_wnd={rcv_wnd}, result={result}",
             LOGLEVEL_DEBUG)
        return result

    def check_if_segment_is_in_receive_window(self, seg: LoRaTCPSegment) -> bool:
        """
        Prüft ob ein Segment im akzeptablen Empfangsfenster liegt.

        Überprüft ob Segmente akzeptiert werden
        basierend auf Sequenznummer, Segmentlänge und Empfangsfenster.
        Behandelt alle vier RFC-definierten Fälle.

        Args:
            seg: Das zu prüfende TCP-Segment

        Returns:
            bool: True wenn Segment akzeptabel ist, False andernfalls

        RFC 793 Fälle:
        - Länge 0, Fenster 0: SEG.SEQ = RCV.NXT
        - Länge 0, Fenster >0: RCV.NXT ≤ SEG.SEQ < RCV.NXT+RCV.WND
        - Länge >0, Fenster 0: Nie akzeptabel
        - Länge >0, Fenster >0: Erstes oder letztes Byte im Fenster
        """
        seg_seq = Seq(seg.seq)
        seg_len = len(seg.payload)
        rcv_nxt = Seq(self.tcb.rcv_nxt)
        rcv_wnd = self.tcb.rcv_wnd

        _log(f"Receive window check: seq={seg_seq}, len={seg_len}, rcv_nxt={rcv_nxt}, rcv_wnd={rcv_wnd}",
             LOGLEVEL_DEBUG)

        acceptable = False

        if seg_len == 0 and rcv_wnd == 0:
            # Zero length segment, zero window: must be exactly RCV.NXT
            acceptable = (seg_seq == rcv_nxt)
            _log(f"Zero length segment, zero window: {acceptable}", LOGLEVEL_DEBUG)
        elif seg_len == 0 and rcv_wnd > 0:
            # Zero length segment, positive window: RCV.NXT <= SEG.SEQ < RCV.NXT+RCV.WND
            acceptable = rcv_nxt <= seg_seq < (rcv_nxt + rcv_wnd)
            _log(f"Zero length segment, positive window: {acceptable}", LOGLEVEL_DEBUG)
        elif seg_len > 0 and rcv_wnd == 0:
            # Positive length segment, zero window: never acceptable
            acceptable = False
            _log(f"Positive length segment, zero window: {acceptable}", LOGLEVEL_DEBUG)
        elif seg_len > 0 and rcv_wnd > 0:
            # Positive length segment, positive window: Either first or last byte must be in window
            last_byte_seq = seg_seq + seg_len - 1
            acceptable = (rcv_nxt <= seg_seq < (rcv_nxt + rcv_wnd)) or \
                         (rcv_nxt <= last_byte_seq < (rcv_nxt + rcv_wnd))
            _log(f"Positive length segment, positive window: last_byte_seq={last_byte_seq}, acceptable={acceptable}",
                 LOGLEVEL_DEBUG)
        return acceptable

    def _validate_segment(self, seg: LoRaTCPSegment) -> bool:
        """
        Validiert grundlegende Segment-Eigenschaften gegen Protokollverstöße.

        Überprüft empfangene Segmente auf fehlerhafte Formate
        und ungültige Flag-Kombinationen, um fehlerhafte oder schädliche
        Segmente frühzeitig zu erkennen und zu verwerfen.

        Args:
            seg: Das zu validierende TCP-Segment

        Returns:
            bool: True wenn Segment gültig ist, False bei Protokollverletzung

        Prüfungen:
        - Payload-Größe innerhalb der Limits
        - Ungültige Flag-Kombinationen (SYN+FIN, RST+SYN/FIN)
        - Grundlegende Strukturintegrität
        """
        try:
            # Check payload size constraints
            if len(seg.payload) > LoRaTCP_MAX_PAYLOAD_SIZE:
                _log(f"Payload too large: {len(seg.payload)} > {LoRaTCP_MAX_PAYLOAD_SIZE}", LOGLEVEL_WARNING)
                return False

            # Check for invalid flag combinations
            if seg.syn_flag and seg.fin_flag:
                _log("Invalid flag combination: SYN and FIN both set", LOGLEVEL_WARNING)
                return False

            if seg.rst_flag and (seg.syn_flag or seg.fin_flag):
                _log("Invalid flag combination: RST with SYN or FIN", LOGLEVEL_WARNING)
                return False

            return True

        except Exception as e:
            _log(f"Exception during segment validation: {e}", LOGLEVEL_ERROR)
            return False

    def _reassemble_received_data(self):
        """
        Setzt empfangene TCP-Segmente in korrekter Reihenfolge zusammen.

        Verarbeitet alle Segmente aus dem receive_buffer und fügt zusammenhängende
        Daten zu reassembled_data hinzu. Aktualisiert RCV.NXT nur für korrekt
        geordnete, zusammenhängende Segmente. Thread-sicher durch Verwendung
        von Locks.

        Verhalten:
        - Verarbeitet nur Segmente ab der erwarteten Sequenznummer (RCV.NXT)
        - Überspringt Lücken in der Sequenz (Out-of-Order Handling)
        - Aktualisiert Empfangsfenster entsprechend verarbeiteter Daten
        """
        if len(self.tcb.receive_buffer) == 0:
            return

        _log(f"Starting data reassembly: buffer_segments={len(self.tcb.receive_buffer)}, rcv_nxt={self.tcb.rcv_nxt}",
             LOGLEVEL_DEBUG)

        with self.tcb.reassembled_data_lock:
            segments_processed = 0
            initial_data_len = len(self.tcb.reassembled_data)

            while True:
                # Suche das nächste erwartete Segment
                expected_seq = self.tcb.rcv_nxt

                if expected_seq not in self.tcb.receive_buffer:
                    _log(f"No contiguous segment found for seq={expected_seq}", LOGLEVEL_DEBUG)
                    break  # Kein zusammenhängendes Segment gefunden

                # Segment aus Buffer holen und verarbeiten
                segment_data = self.tcb.receive_buffer.pop(expected_seq)
                _log(f"Processing segment: seq={expected_seq}, len={len(segment_data)}", LOGLEVEL_DEBUG)

                # Zu reassembled_data hinzufügen
                self.tcb.reassembled_data += segment_data

                # RCV.NXT über die verarbeiteten Daten hinaus bewegen
                old_rcv_nxt = self.tcb.rcv_nxt
                self.tcb.rcv_nxt = self.tcb.rcv_nxt + len(segment_data)
                _log(f"Advanced rcv_nxt: {old_rcv_nxt} -> {self.tcb.rcv_nxt}", LOGLEVEL_DEBUG)
                segments_processed += 1

                # _log(
                #    f"Reassembled segment: seq={expected_seq}, len={len(segment_data)}, new_rcv_nxt={self.tcb.rcv_nxt}")

            if segments_processed > 0:
                # IGNORE Receive Window aktualisieren
                final_data_len = len(self.tcb.reassembled_data)
                data_added = final_data_len - initial_data_len
                _log(
                    f"Reassembled {segments_processed} segments, total reassembled data: {final_data_len} bytes (+{data_added})")
                _log(f"Remaining segments in receive buffer: {len(self.tcb.receive_buffer)}", LOGLEVEL_DEBUG)

    def getpeername(self):
        """
        Gibt die Adresse des verbundenen Peers zurück.

        Kompatibel mit Standard-Socket API. Liefert IP-Adresse und Port
        des entfernten Endpunkts der aktuellen Verbindung.

        Returns:
            tuple: (IP-Adresse, Port) des verbundenen Peers
        """
        peer = (self.tcb.remote_ip, self.tcb.remote_port)
        _log(f"getpeername called: {peer}", LOGLEVEL_DEBUG)
        return peer