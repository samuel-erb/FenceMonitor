from __future__ import annotations
import spidev
from typing import Optional, Tuple, Final
from . import PinLike, AnyReadableBuf, AnyWritableBuf

class SPI:
    """
    Kompatibilitätsschicht für MicroPython SPI-Klasse auf Raspberry Pi mit spidev
    """

    # Konstanten für Bit-Reihenfolge
    LSB: Final[int] = 1
    MSB: Final[int] = 0

    # Konstante für Controller/Peripheral (Master/Slave)
    CONTROLLER: Final[int] = 0

    def __init__(
            self,
            id: int,
            /,
            baudrate: int = 1_000_000,
            *,
            polarity: int = 0,
            phase: int = 0,
            bits: int = 8,
            firstbit: int = MSB,
            sck: Optional[PinLike] = None,
            mosi: Optional[PinLike] = None,
            miso: Optional[PinLike] = None,
            pins: Optional[Tuple[PinLike, PinLike, PinLike]] = None,
    ):
        """
        Konstruiert ein SPI-Objekt auf dem gegebenen Bus

        Args:
            id: SPI-Bus-Nummer (0, 1, etc.)
            baudrate: SCK Clock-Rate in Hz
            polarity: Clock-Polarität (0 oder 1)
            phase: Clock-Phase (0 oder 1)
            bits: Anzahl der Bits pro Transfer (normalerweise 8)
            firstbit: MSB oder LSB zuerst
            sck: Pin für Clock-Signal (wird in spidev automatisch zugewiesen)
            mosi: Pin für Master-Out-Slave-In (wird in spidev automatisch zugewiesen)
            miso: Pin für Master-In-Slave-Out (wird in spidev automatisch zugewiesen)
            pins: Alternative Pin-Spezifikation als Tupel
        """
        self._spi = spidev.SpiDev()
        self._id = id
        self._baudrate = baudrate
        self._polarity = polarity
        self._phase = phase
        self._bits = bits
        self._firstbit = firstbit

        # Hinweis: spidev verwendet feste Pins für Hardware-SPI,
        # daher werden die Pin-Parameter ignoriert
        self._sck = sck
        self._mosi = mosi
        self._miso = miso

        # Bus öffnen und initialisieren
        try:
            # Raspberry Pi hat normalerweise SPI Bus 0 mit mehreren Chip-Select-Leitungen
            # id wird als Chip-Select interpretiert
            self._spi.open(0, id)  # Bus 0, Device id
            self.init(baudrate=baudrate, polarity=polarity, phase=phase,
                      bits=bits, firstbit=firstbit)
        except FileNotFoundError:
            # Wenn id > 1, versuche es als Bus-Nummer
            try:
                self._spi.open(id, 0)  # Bus id, Device 0
                self.init(baudrate=baudrate, polarity=polarity, phase=phase,
                          bits=bits, firstbit=firstbit)
            except:
                raise ValueError(f"SPI bus {id} not available")

    def init(
            self,
            baudrate: int = 1_000_000,
            *,
            polarity: int = 0,
            phase: int = 0,
            bits: int = 8,
            firstbit: int = MSB,
            sck: Optional[PinLike] = None,
            mosi: Optional[PinLike] = None,
            miso: Optional[PinLike] = None,
            pins: Optional[Tuple[PinLike, PinLike, PinLike]] = None,
    ) -> None:
        """
        Initialisiert den SPI-Bus mit den gegebenen Parametern
        """
        # Baudrate setzen
        self._baudrate = baudrate
        self._spi.max_speed_hz = baudrate

        # SPI-Mode setzen (Kombination aus Polarität und Phase)
        # Mode 0: CPOL=0, CPHA=0
        # Mode 1: CPOL=0, CPHA=1
        # Mode 2: CPOL=1, CPHA=0
        # Mode 3: CPOL=1, CPHA=1
        self._polarity = polarity
        self._phase = phase
        self._spi.mode = (polarity << 1) | phase

        # Bits pro Wort setzen (spidev unterstützt nur 8 Bit)
        self._bits = bits
        if bits != 8:
            print(f"Warning: spidev only supports 8-bit transfers, requested {bits} bits")
        self._spi.bits_per_word = 8

        # Bit-Reihenfolge setzen
        self._firstbit = firstbit
        self._spi.lsbfirst = (firstbit == self.LSB)

        # Pins werden von spidev nicht konfiguriert (Hardware-SPI verwendet feste Pins)
        if sck or mosi or miso or pins:
            print("Warning: Pin configuration is handled by the system for hardware SPI")

    def deinit(self) -> None:
        """
        Schaltet den SPI-Bus ab
        """
        if self._spi:
            self._spi.close()
            self._spi = None

    def write(self, buf: AnyReadableBuf, /) -> Optional[int]:
        """
        Schreibt die Bytes aus buf
        Gibt None zurück (oder Anzahl der geschriebenen Bytes auf WiPy)
        """
        if not self._spi:
            raise RuntimeError("SPI bus not initialized")

        # Konvertiere zu Liste für spidev
        if isinstance(buf, (bytes, bytearray)):
            data = list(buf)
        else:
            data = list(bytes(buf))

        self._spi.writebytes(data)
        return len(data)  # Kompatibilität mit WiPy

    def read(self, nbytes: int, write: int = 0x00, /) -> bytes:
        """
        Liest nbytes Bytes, während kontinuierlich write gesendet wird
        Gibt ein bytes-Objekt mit den gelesenen Daten zurück
        """
        if not self._spi:
            raise RuntimeError("SPI bus not initialized")

        # Erstelle Liste mit write-Werten
        write_data = [write] * nbytes

        # Führe Transfer durch
        read_data = self._spi.xfer(write_data)

        return bytes(read_data)

    def readinto(self, buf: AnyWritableBuf, write: int = 0x00, /) -> Optional[int]:
        """
        Liest in den spezifizierten Puffer, während kontinuierlich write gesendet wird
        Gibt None zurück (oder Anzahl der gelesenen Bytes auf WiPy)
        """
        if not self._spi:
            raise RuntimeError("SPI bus not initialized")

        nbytes = len(buf)

        # Erstelle Liste mit write-Werten
        write_data = [write] * nbytes

        # Führe Transfer durch
        read_data = self._spi.xfer(write_data)

        # Kopiere Daten in den Puffer
        for i, byte in enumerate(read_data):
            buf[i] = byte

        return nbytes  # Kompatibilität mit WiPy

    def write_readinto(self, write_buf: AnyReadableBuf, read_buf: AnyWritableBuf, /) -> Optional[int]:
        """
        Schreibt Bytes aus write_buf während des Lesens in read_buf
        Die Puffer können gleich oder verschieden sein, müssen aber die gleiche Länge haben
        Gibt None zurück (oder Anzahl der Bytes auf WiPy)
        """
        if not self._spi:
            raise RuntimeError("SPI bus not initialized")

        if len(write_buf) != len(read_buf):
            raise ValueError("write_buf and read_buf must have the same length")

        # Konvertiere write_buf zu Liste
        if isinstance(write_buf, (bytes, bytearray)):
            write_data = list(write_buf)
        else:
            write_data = list(bytes(write_buf))

        # Führe Transfer durch
        read_data = self._spi.xfer(write_data)

        # Kopiere Daten in read_buf
        for i, byte in enumerate(read_data):
            read_buf[i] = byte

        return len(write_buf)  # Kompatibilität mit WiPy

    def __repr__(self) -> str:
        """
        String-Repräsentation des SPI-Objekts
        """
        if not self._spi:
            return f"SPI({self._id}, deinitialized)"

        mode = (self._polarity << 1) | self._phase
        return (f"SPI({self._id}, baudrate={self._baudrate}, polarity={self._polarity}, "
                f"phase={self._phase}, bits={self._bits}, firstbit={'LSB' if self._firstbit else 'MSB'}, "
                f"mode={mode})")

    def __del__(self):
        """
        Destruktor - schließt SPI-Verbindung
        """
        self.deinit()


# SoftSPI-Klasse als Alias (verwendet die gleiche Implementation)
class SoftSPI(SPI):
    """
    Software-SPI-Implementation (auf Raspberry Pi gleich wie Hardware-SPI)
    """
    pass