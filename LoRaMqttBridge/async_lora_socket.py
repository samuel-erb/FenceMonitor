import threading

import micropython_time as time
import binascii
import machine
import _thread

from lora import RxPacket, SX1262


class AsyncLoRaSocket:
    """
    AsyncLoRaSocket simulates a stream socket over LoRa with asynchronous receiving.

    Empfangene Pakete werden in einer Queue gespeichert und bei read()-Aufrufen
    aus dieser Queue geholt.

    Header format for chunks:
      [sensor_id:1][msg_id:1][seq_num:1][total_chunks:1] + payload
    """

    _transmission_lock = threading.Lock()

    modem: SX1262 = None
    sensor_id: int = None
    last_packet_sent = 0

    HEADER_SIZE = 4
    MAX_CHUNK_SIZE = 240  # payload bytes per chunk (250 - 4 header bytes)
    WAIT_BETWEEN_SEND = 2000
    MAX_QUEUE_SIZE = 50000  # Maximale Größe der Queue in Bytes

    @staticmethod
    def configure_socket(lora_modem: SX1262):
        if lora_modem is None:
            raise RuntimeError("[AsyncLoRaSocket] Failed to configure socket! Provided modem was 'None'")
        AsyncLoRaSocket.modem = lora_modem

    def __init__(self):
        if AsyncLoRaSocket.modem is None:
            raise RuntimeError("[AsyncLoRaSocket] Please run AsyncLoRaSocket.configure_socket before instantiating!")

        self.lora = AsyncLoRaSocket.modem
        self.remote_id = None
        self.timeout = None
        self._next_msg_id = 0

        # Einfache Liste für die Queue und Thread-Steuerung
        self.recv_queue = []
        self.queue_size = 0
        self.queue_lock = _thread.allocate_lock()
        self.running = True


        # buffers für Nachrichtenzusammenstellung
        self._recv_buffers = {}
        self._recv_meta = {}  # msg_id -> total_chunks

        # Thread für asynchronen Empfang
        self.recv_thread = None

    def _receiver_thread_func(self, _):
        """Thread-Funktion zum asynchronen Empfangen von Daten."""
        print("[AsyncLoRaSocket] Receiver thread started")

        while self.running:
            try:
                # Non-blockierendes Empfangen mit kurzen Timeouts
                packet = self.lora.recv(timeout_ms=10)
                if packet:
                    if len(packet) < 4:
                        continue

                    sid, msg_id, seq, total = packet[0], packet[1], packet[2], packet[3]
                    data = packet[4:]

                    print(f"[LoRa rcv {len(packet)}] sid: {sid}, msg_id: {msg_id}, seq: {seq}, total: {total}, payload: {data}")

                    # Nachrichtenpuffer initialisieren und Daten speichern
                    if msg_id not in self._recv_buffers[sid]:
                        self._recv_buffers[sid][msg_id] = {}
                        self._recv_meta[sid][msg_id] = total
                    self._recv_buffers[sid][msg_id][seq] = data

                    # Prüfen, ob Nachricht vollständig ist
                    if len(self._recv_buffers[sid][msg_id]) == total:
                        parts = [self._recv_buffers[sid][msg_id][i] for i in range(total)]
                        full_data = b"".join(parts)

                        # In Queue schreiben (Thread-sicher)
                        with self.queue_lock:
                            # Prüfen, ob genug Platz in der Queue ist
                            if self.queue_size + len(full_data) > self.MAX_QUEUE_SIZE:
                                print("[AsyncLoRaSocket] Warning: Queue full, dropping oldest data")
                                # Älteste Daten entfernen, bis genug Platz ist
                                while self.queue_size + len(full_data) > self.MAX_QUEUE_SIZE and self.recv_queue:
                                    old_data = self.recv_queue.pop(0)  # pop from start (oldest data)
                                    self.queue_size -= len(old_data)

                            # Daten zur Queue hinzufügen
                            self.recv_queue.append(full_data)
                            self.queue_size += len(full_data)

                        # Puffer aufräumen
                        del self._recv_buffers[sid][msg_id]
                        del self._recv_meta[sid][msg_id]
                        print(f"[LoRa rcv] sid: {sid}, msg_id: {msg_id} ☑️ → Queue ({self.queue_size} bytes)")


                time.sleep_ms(10)  # Kurze Pause, um CPU zu sparen

            except Exception as e:
                print(f"[AsyncLoRaSocket] Receiver thread error: {e}")
                # Kurze Pause vor dem nächsten Versuch
                time.sleep_ms(100)

        print("[AsyncLoRaSocket] Receiver thread stopped")

    def connect(self, addr=None):
        """Verbindung zum Gateway herstellen und Empfangs-Thread starten."""
        self.remote_id = addr
        print("[AsyncLoRaSocket] Connected to remote device")

        # Thread starten, falls noch nicht läuft
        if self.recv_thread is None:
            self.running = True
            # In MicroPython benötigt start_new_thread ein zusätzliches Dummy-Argument
            self.recv_thread = _thread.start_new_thread(self._receiver_thread_func, (None,))

    def settimeout(self, seconds):
        """Timeout für Lesevorgänge setzen (für read()-Methode)."""
        if seconds < 3:
            print("[AsyncLoRaSocket] Warning: The timeout should be at least 3 seconds")
        self.timeout = seconds
        print(f"[AsyncLoRaSocket] Timeout set to {seconds} seconds")

    def setblocking(self, flag):
        """Blockierendes Verhalten einstellen."""
        if flag:
            self.timeout = None
        else:
            self.timeout = 0
        print(f"[AsyncLoRaSocket] Blocking set to {flag}")

    def close(self):
        """Empfangs-Thread beenden."""
        self.running = False
        # Warten kann hier entfallen, da wir den Thread nicht wirklich tracken können
        print("[AsyncLoRaSocket] Socket closed")

    def write(self, buf, sensor_id, size=None):
        """Daten senden (gleich wie in der Original-Implementierung)."""
        data = buf if size is None else buf[:size]
        total_len = len(data)

        # Anzahl der Chunks berechnen
        max_payload = self.MAX_CHUNK_SIZE
        total_chunks = (total_len + max_payload - 1) // max_payload
        msg_id = self._next_msg_id & 0xFF
        self._next_msg_id = (self._next_msg_id + 1) & 0xFF

        # Jeden Chunk senden
        for seq in range(total_chunks):
            start = seq * max_payload
            end = start + max_payload
            chunk = data[start:end]
            header = bytes([sensor_id, msg_id, seq, total_chunks])

            now = time.ticks_ms()
            if time.ticks_diff(now, AsyncLoRaSocket.last_packet_sent) < self.WAIT_BETWEEN_SEND:
                time.sleep_ms(self.WAIT_BETWEEN_SEND - time.ticks_diff(now, AsyncLoRaSocket.last_packet_sent))

            print(
                f"[LoRa wrt] sid: {sensor_id}, msg_id: {msg_id}, seq: {seq}, total: {total_chunks}, payload: {chunk}",
                end="")
            with AsyncLoRaSocket._transmission_lock:
                self.lora.send(RxPacket(header + chunk))
            print(" ☑️")
            AsyncLoRaSocket.last_packet_sent = time.ticks_ms()

        print(f"[LoRa wrt] sid: {self.sensor_id}, msg_id: {msg_id} ☑️", end="\n\n")
        return total_len

    def read(self, bufsize=240):
        """
        Liest bis zu bufsize Bytes aus der Empfangs-Queue.

        Wenn keine Daten verfügbar sind, wird je nach Timeout-Einstellung
        gewartet oder ein Fehler ausgelöst.
        """
        start_time = time.ticks_ms()

        while True:
            # Thread-sicher aus Queue lesen
            with self.queue_lock:
                if self.recv_queue:
                    # Daten aus der Queue holen
                    data = self.recv_queue.pop(0)  # pop from start (oldest data)
                    self.queue_size -= len(data)

                    # Nur die angeforderten Bytes zurückgeben
                    result = data[:bufsize]

                    # Falls mehr Daten vorhanden als angefordert, Rest zurück in die Queue
                    if len(data) > bufsize:
                        remaining = data[bufsize:]
                        self.recv_queue.insert(0, remaining)  # insert at start
                        self.queue_size += len(remaining)
                        print(f"[AsyncLoRaSocket] Read {len(result)} bytes, {len(remaining)} bytes put back in queue")
                    else:
                        print(f"[AsyncLoRaSocket] Read {len(result)} bytes from queue")

                    return result

            # Timeout prüfen
            if self.timeout is not None:
                elapsed = time.ticks_diff(time.ticks_ms(), start_time) / 1000
                if elapsed > self.timeout:
                    raise OSError("[AsyncLoRaSocket] Read timeout")

            # Kurze Pause, um CPU zu sparen
            time.sleep_ms(10)

    def available(self):
        """Gibt zurück, wie viele Bytes in der Queue verfügbar sind."""
        with self.queue_lock:
            return self.queue_size