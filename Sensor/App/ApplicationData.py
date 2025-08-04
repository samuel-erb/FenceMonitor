import struct

from micropython import const

from App.VoltageMeasurement import VoltageMeasurement


class ApplicationData:
    __slots__ = ('sensor_id', 'voltage', 'battery', 'latitude', 'longitude')

    # Bounding Box für Deutschland
    LATITUDE_MIN = const(47.0)
    LATITUDE_MAX = const(55.0)
    LONGITUDE_MIN = const(5.5)
    LONGITUDE_MAX = const(15.0)

    QUANT_MAX = const(65535)  # 2^16 - 1

    def __init__(self, sensor_id: int, voltage: int, battery: float, latitude: float = None, longitude: float = None):
        self.sensor_id = sensor_id
        self.voltage = next((k for k, v in VoltageMeasurement.VOLTAGE_MAP.items() if v == voltage), 0)   # 0–7 (3 Bit)
        self.battery = battery  # 0–31 (5 Bit)
        self.latitude = latitude  # in Grad, z.B. 52.123456
        self.longitude = longitude

    def to_bytes(self) -> bytes:
        # Byte 1: Sensor ID
        sensor_id_byte = self.sensor_id & 0xFF  # nur 1 Byte

        # Byte 2: 3 Bit voltage (oben), 5 Bit battery (unten)
        if not (0 <= self.voltage <= 7):
            raise ValueError(f"voltage must be in range 0–7, got {self.voltage}")
        if not (0 <= self.battery <= 1):
            raise ValueError(f"battery must be in range 0–1, got {self.battery}")

        battery_bits = min(round(self.battery * 31.0), 31) & 0b11111
        byte2 = (self.voltage << 5) | battery_bits

        if self.latitude is not None and self.longitude is not None:
            # Bytes 3–4: latitude, quantisiert auf 16 Bit
            lat_int = int(ApplicationData.quantize_coordinate(self.latitude, ApplicationData.LATITUDE_MIN,
                                                              ApplicationData.LATITUDE_MAX))
            lat_bytes = struct.pack('>H', lat_int)  # 2 Byte, Big Endian

            # Bytes 5–6: longitude, quantisiert auf 16 Bit
            lon_int = 0
            lon_int = int(ApplicationData.quantize_coordinate(self.longitude, ApplicationData.LONGITUDE_MIN,
                                                              ApplicationData.LONGITUDE_MAX))
            lon_bytes = struct.pack('>H', lon_int)  # 2 Byte, Big Endian
            return bytes([sensor_id_byte, byte2]) + lat_bytes + lon_bytes
        else:
            return bytes([sensor_id_byte, byte2])

    @staticmethod
    def quantize_coordinate(value: float, min_val: float, max_val: float) -> int:
        """Quantisiert eine Koordinate auf 16 Bit."""
        if value < min_val or value > max_val:
            raise ValueError(f"Wert {value} außerhalb des erlaubten Bereichs ({min_val}–{max_val})")
        q = int((value - min_val) / (max_val - min_val) * ApplicationData.QUANT_MAX)
        return min(max(q, 0), ApplicationData.QUANT_MAX)  # Sicherheit gegen Überlauf

    def __repr__(self):
        return "ApplicationData(sensor_id={}, battery={}, voltage={}, latitude={}, longitude={})".format(self.sensor_id, self.battery, self.voltage, self.latitude, self.longitude)
