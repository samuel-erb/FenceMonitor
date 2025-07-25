from machine import UART, Pin, RTC
import time

from micropython import const


class NEO6M:
    # mode: 1 = Power Save Mode, 4 = Eco Mode, 0 = Maximum Performance Mode
    POWER_SAVE_MODE = const(4)
    ECO_MODE = const(0)
    MAXIMUM_PERFORMANCE_MODE = const(0)

    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(NEO6M, cls).__new__(cls)
        return cls._instance

    def __init__(self, uart_id=1, tx_pin=47, rx_pin=48, baud_rate=9600, timeout=1000):
        """
        Initialisiert das NEO-6M GPS-Modul.

        Args:
            uart_id: UART-Kanal (Standard: 1)
            tx_pin: TX-Pin-Nummer (Standard: 47)
            rx_pin: RX-Pin-Nummer (Standard: 48)
            baud_rate: Baudrate (Standard: 9600)
            timeout: Timeout in ms (Standard: 1000)
        """
        self.uart = UART(uart_id, baud_rate, tx=Pin(tx_pin), rx=Pin(rx_pin), timeout=timeout)
        self.buffer = b""
        self.latitude = None
        self.longitude = None
        self.satellites = None
        self.altitude = None
        self.speed = None
        self.course = None
        self.time = None
        self.date = None
        self.parsed_gpgga = False
        self.parsed_gprmc = False
        #self.rtc = RTC()
        self.power_status = False
        if not self.is_gps_connected():
            print("[NEO6M] WARNUNG: GPS-Modul scheint nicht zu kommunizieren!")

    def is_gps_connected(self, timeout_ms=2000):
        """
        Prüft, ob das GPS-Modul verbunden ist und Daten sendet.

        Args:
            timeout_ms: Maximale Wartezeit in Millisekunden

        Returns:
            True wenn Daten empfangen werden, sonst False
        """
        start_time = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), start_time) < timeout_ms:
            if self.uart.any():
                return True
            time.sleep_ms(100)
        return False

    def _parse_gps_data(self, data):
        """Parse NMEA sentences from GPS module."""
        if data is None:
            return  # Früher Return, wenn data None ist

        for line in data.split('\r\n'):
            if line.startswith('$GPGGA'):  # Global Positioning System Fix Data
                self._parse_gpgga(line)
                print(f"[NEO6M] Parsed GPGGA sentence: {line}")
            elif line.startswith('$GPRMC'):  # Recommended Minimum Specific GPS/Transit Data
                self._parse_gprmc(line)
                print(f"[NEO6M] Parsed GPRMC sentence: {line}")


        if self.time is not None and self.date is not None:
            hours, minutes, seconds = self.time
            day, month, year = self.date
            #self.rtc.datetime((year, month, day, 0, hours, minutes, seconds, 0))

    def _parse_gpgga(self, nmea_sentence):
        """Parse the GPGGA sentence for position, altitude and fix data."""
        try:
            parts = nmea_sentence.split(',')

            if len(parts) < 15:
                return

            # Check if we have a fix (0 = no fix, 1 = GPS fix, 2 = DGPS fix)
            if parts[6] == '0':
                return

            # Parse time (HHMMSS.sss)
            if parts[1]:
                time_str = parts[1]
                hours = int(time_str[0:2])
                minutes = int(time_str[2:4])
                seconds = float(time_str[4:])
                self.time = (hours, minutes, seconds)

            # Parse latitude (DDMM.MMMM)
            if parts[2] and parts[3]:
                lat = float(parts[2])
                lat_degrees = int(lat / 100)
                lat_minutes = lat - (lat_degrees * 100)
                latitude = lat_degrees + (lat_minutes / 60)
                if parts[3] == 'S':  # South is negative
                    latitude = -latitude
                self.latitude = latitude

            # Parse longitude (DDDMM.MMMM)
            if parts[4] and parts[5]:
                lon = float(parts[4])
                lon_degrees = int(lon / 100)
                lon_minutes = lon - (lon_degrees * 100)
                longitude = lon_degrees + (lon_minutes / 60)
                if parts[5] == 'W':  # West is negative
                    longitude = -longitude
                self.longitude = longitude

            # Parse number of satellites
            if parts[7]:
                self.satellites = int(parts[7])

            # Parse altitude
            if parts[9] and parts[10]:
                self.altitude = float(parts[9])
            self.parsed_gpgga = True
        except (ValueError, IndexError) as e:
            print("Error parsing GPGGA:", e)

    def _parse_gprmc(self, nmea_sentence):
        """Parse the GPRMC sentence for date, speed and course information."""
        try:
            parts = nmea_sentence.split(',')

            if len(parts) < 12:
                return

            # Parse status (A = valid position, V = warning)
            if parts[2] != 'A':
                return

            # Parse date (DDMMYY)
            if parts[9]:
                date_str = parts[9]
                day = int(date_str[0:2])
                month = int(date_str[2:4])
                year = 2000 + int(date_str[4:6])  # Assumes 21st century
                self.date = (day, month, year)

            # Parse speed in knots, convert to km/h
            if parts[7]:
                self.speed = float(parts[7]) * 1.852  # Knots to km/h

            # Parse course/track angle in degrees
            if parts[8]:
                self.course = float(parts[8])
            self.parsed_gprmc = True
        except (ValueError, IndexError) as e:
            print("Error parsing GPRMC:", e)

    def update(self):
        """
        Aktualisiert GPS-Daten. Gibt True zurück, wenn neue Daten gelesen wurden.
        """
        if self.uart.any():
            try:
                # Daten als Bytes lesen
                received_bytes = self.uart.read(self.uart.any())

                # Sicherstellen, dass buffer ein bytestring ist
                if isinstance(self.buffer, str):
                    self.buffer = self.buffer.encode('ascii', 'ignore')

                # Empfangene Bytes zum Buffer hinzufügen
                self.buffer += received_bytes

                # Nach kompletten NMEA-Sätzen suchen
                if b'\r\n' in self.buffer:
                    lines = self.buffer.split(b'\r\n')
                    # Der letzte Teil könnte unvollständig sein
                    self.buffer = lines[-1]

                    # Verarbeite alle kompletten Sätze
                    if len(lines) > 1:  # Stellen Sie sicher, dass wir vollständige Zeilen haben
                        complete_data = b'\r\n'.join(lines[:-1])

                        # Sicher dekodieren
                        try:
                            decoded_data = complete_data.decode('ascii', 'ignore')
                            if decoded_data:  # Sicherstellen, dass wir Daten haben
                                self._parse_gps_data(decoded_data)
                                return True
                        except Exception as e:
                            print("Fehler bei der Dekodierung:", e)
                            # Bei Fehler nicht den Buffer zurücksetzen, sondern weitermachen
            except Exception as e:
                print("Fehler beim Lesen der GPS-Daten:", e)
                # Bei einem schwerwiegenden Fehler den Buffer zurücksetzen
                self.buffer = b""
        return False

    def _has_fix(self):
        """
        Gibt zurück, ob das GPS-Modul einen Fix hat.
        """
        return self.parsed_gpgga and self.parsed_gprmc

    def get_position(self, timeout=5_000):
        """
        Gibt die aktuelle Position als (Breitengrad, Längengrad) zurück.
        Blockiert so lange, bis ein Fix vom GPS-Modul verfügbar ist oder bis der Timeout erreicht wurde.

        Args:
            timeout (int): Timeout in Millisekunden. 0 bedeutet kein Timeout (wartet unbegrenzt).

        Returns:
            tuple[float, float] | None: (Breitengrad, Längengrad) bei Erfolg, sonst None.
        """
        start = time.ticks_ms()

        while not self._has_fix():
            if timeout > 0 and time.ticks_diff(time.ticks_ms(), start) > timeout:
                print("Timeout")
                break
            self.update()
            time.sleep_ms(100)
        return (self.latitude, self.longitude)

    def get_altitude(self):
        """
        Gibt die aktuelle Höhe in Metern zurück.
        Returns None, wenn kein Fix verfügbar ist.
        """
        if self._has_fix():
            return self.altitude
        return None

    def get_speed(self):
        """
        Gibt die aktuelle Geschwindigkeit in km/h zurück.
        Returns None, wenn kein Fix verfügbar ist.
        """
        if self._has_fix():
            return self.speed
        return None

    def get_datetime(self):
        """
        Gibt das aktuelle Datum und die Uhrzeit als ((Tag, Monat, Jahr), (Stunden, Minuten, Sekunden)) zurück.
        Returns None, wenn kein Fix verfügbar ist.
        """
        if self._has_fix() and self.date and self.time:
            return (self.date, self.time)
        return None

    def get_satellites(self):
        """
        Gibt die Anzahl der sichtbaren Satelliten zurück.
        """
        return self.satellites

    def set_power_mode(self, mode):
        """
        Setzt den Power Mode des GPS-Moduls.

        mode: 1 = Power Save Mode, 4 = Eco Mode, 0 = Maximum Performance Mode

        Hinweis: Power Save Mode ist nicht verfügbar mit NEO-6P, NEO-6T und NEO-6V.
        """
        # UBX-CFG-RXM message
        # Header: 0xB5 0x62
        # Class: 0x06, ID: 0x11
        # Length: 2 bytes
        # Payload: reserved1(1 byte), lpMode(1 byte)
        msg = bytearray([0xB5, 0x62, 0x06, 0x11, 0x02, 0x08, mode])

        # Berechne Checksum
        ck_a = 0
        ck_b = 0
        for i in range(2, len(msg)):
            ck_a = (ck_a + msg[i]) & 0xFF
            ck_b = (ck_b + ck_a) & 0xFF

        msg.append(ck_a)
        msg.append(ck_b)

        # Sende Nachricht an GPS
        self.uart.write(msg)
        print(f"[NEO6M] Wrote CFG-RXM message over UART: {msg}")

    def test_power_save_mode(self):
        """
        Testet, ob das GPS-Modul im Power-Save-Mode noch Daten sendet.
        Gibt True zurück, wenn Daten nach Umschaltung empfangen werden.
        """
        print("[NEO6M] Starte Test für Power Save Mode...")

        # 1. Setze Power Save Mode
        self.set_power_mode(NEO6M.POWER_SAVE_MODE)
        self.uart.flush()
        self.uart.read(self.uart.any())
        print("[NEO6M] Power Save Mode aktiviert. Warte 5 Sekunden...")

        # 2. Warte, damit der Modus greifen kann
        time.sleep(5)

        # 3. Prüfe ob noch Daten kommen
        print("[NEO6M] Prüfe, ob weiterhin GPS-Daten empfangen werden...")
        has_data = False
        start_time = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), start_time) < 5000:  # 5 Sekunden testen
            if self.update():
                has_data = True
                break
            time.sleep_ms(200)

        if has_data:
            print("[NEO6M] ✅ GPS sendet weiterhin Daten im Power Save Mode.")
        else:
            print("[NEO6M] ❌ Keine GPS-Daten im Power Save Mode empfangen.")

        return has_data
