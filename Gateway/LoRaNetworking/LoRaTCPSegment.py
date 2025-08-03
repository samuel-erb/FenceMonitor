import struct

from micropython import const

# 2^16 -> 65536, da wir 16-Bit-Sequenznummern verwenden (Wrap-around bei 65536)
SEQ_MOD = const(65536)

# SEQ_MOD // 2 -> 32768, zur Berechnung der Differenz mit Vorzeichen
SEQ_HALF = const(32768)

class Seq(int):
    def __lt__(self, other) -> bool:
        """
        Gibt True zurück, wenn diese Sequenznummer (self) kleiner ist als die andere (other).

        Dies berücksichtigt das Überlaufen des Sequenznummernraums ("Wrap-around").
        Typisch verwendet, um zu prüfen, ob ein Segment in der Zukunft liegt.

        Beispiel:
          Seq(10) < Seq(20)  -> True
          Seq(65530) < Seq(5) -> True (da Wrap-around)
        """
        return ((self - other) % SEQ_MOD) > SEQ_HALF

    def __le__(self, other) -> bool:
        """
        Gibt True zurück, wenn diese Sequenznummer kleiner oder gleich der anderen ist.

        Dies inkludiert den Gleichheitsfall und berücksichtigt ebenfalls den Wrap-around.

        Beispiel:
          Seq(10) <= Seq(10) -> True
          Seq(65530) <= Seq(5) -> True
        """
        return self == other or self < other

    def __gt__(self, other) -> bool:
        """
        Gibt True zurück, wenn diese Sequenznummer größer ist als die andere.

        Berücksichtigt den Sequenznummern-Überlauf.

        Beispiel:
          Seq(20) > Seq(10) -> True
          Seq(5) > Seq(65530) -> True
        """
        return ((other - self) % SEQ_MOD) > SEQ_HALF

    def __ge__(self, other) -> bool:
        """
        Gibt True zurück, wenn diese Sequenznummer größer oder gleich der anderen ist.

        Beispiel:
          Seq(20) >= Seq(20) -> True
          Seq(5) >= Seq(65530) -> True
        """
        return self == other or self > other

    def __add__(self, other) -> "Seq":
        """
        Addiert eine Ganzzahl (z.B. ein Offset) zur Sequenznummer und normalisiert das Ergebnis
        in den Sequenzraum mit Wrap-around.

        Gibt eine neue Sequenznummer zurück.

        Beispiel:
          Seq(65534) + 5 -> Seq(3)
        """
        return Seq((int(self) + int(other)) % SEQ_MOD)

    def __sub__(self, other) -> "Seq":
        """
        Berechnet die differenzierte Entfernung zwischen zwei Sequenznummern
        unter Berücksichtigung des Wrap-around.

        Gibt einen vorzeichenbehafteten Abstand zurück:
        - Positiv, wenn self nach other kommt
        - Negativ, wenn self vor other liegt

        Beispiel:
          Seq(5) - Seq(65530) -> 11
          Seq(65530) - Seq(5) -> -11
        """
        return Seq((int(self) - int(other) + SEQ_HALF) % SEQ_MOD - SEQ_HALF)

class LoRaTCPSegment:

    # Struct-Format: B (1 Byte Socket-ID and flags), H (2 Byte Seq), H (2 Byte Ack)
    _STRUCT_FORMAT = ">BHH"
    _HEADER_SIZE = struct.calcsize(_STRUCT_FORMAT)

    __slots__ = ('socket_id', 'syn_flag', 'ack_flag', 'fin_flag', 'rst_flag', 'seq', 'ack', 'payload')

    def __init__(self, socket_id: int, seq: Seq, ack: Seq = Seq(0x0), syn_flag: bool = False, ack_flag: bool = True,
                 fin_flag: bool = False, rst_flag: bool = False, payload: bytes = b''):
        if not (0 <= socket_id <= 15):
            raise ValueError("Socket-ID must be between 0 and 15")
        self.socket_id = socket_id
        self.syn_flag = syn_flag
        self.ack_flag = ack_flag
        self.fin_flag = fin_flag
        self.rst_flag = rst_flag
        self.seq = 0 if seq is None else Seq(seq)  # type: Seq
        self.ack = 0 if ack is None else Seq(ack)  # type: Seq
        if len(payload) > 243:
            raise ValueError("Payload must be less than 244 bytes")
        self.payload = payload

    @classmethod
    def from_bytes(cls, data: bytes) -> "LoRaTCPSegment":
        if len(data) < cls._HEADER_SIZE:
            raise ValueError("Segment too short")

        # Unpack Header (1B socket_id_flags, 2B seq, 2B ack)
        socket_id_flag_byte, seq, ack = struct.unpack(cls._STRUCT_FORMAT, data[:5])

        socket_id = (socket_id_flag_byte & 0xF0) >> 4
        flags_byte = socket_id_flag_byte & 0x0F

        # Extract flags
        syn_flag = bool(flags_byte & 0b0001)
        ack_flag = bool(flags_byte & 0b0010)
        fin_flag = bool(flags_byte & 0b0100)
        rst_flag = bool(flags_byte & 0b1000)

        # Payload
        payload = data[5:]

        return cls(socket_id, seq=Seq(seq), ack=Seq(ack),
                   syn_flag=syn_flag, ack_flag=ack_flag,
                   fin_flag=fin_flag, rst_flag=rst_flag,
                   payload=payload)

    def to_bytes(self) -> bytes:
        # Flags zusammenbauen
        flags = (self.syn_flag << 0) | (self.ack_flag << 1) | (self.fin_flag << 2) | (self.rst_flag << 3)
        socket_id_flag_byte = ((self.socket_id & 0x0F) << 4) | flags

        # Pack Header
        header = struct.pack(self._STRUCT_FORMAT, socket_id_flag_byte, int(self.seq), int(self.ack))

        return header + self.payload

    def __repr__(self):
        flags = []
        if self.syn_flag:
            flags.append("SYN")
        if self.ack_flag:
            flags.append("ACK")
        if self.fin_flag:
            flags.append("FIN")
        if self.rst_flag:
            flags.append("RST")
        flags_str = "|".join(flags) if flags else "NONE"

        return (f"<LoRaTCPSegment "
                f"socket_id=0x{self.socket_id}, "
                f"flags={flags_str}, "
                f"seq={self.seq}, "
                f"ack={self.ack}, "
                f"payload_len={len(self.payload)}>")