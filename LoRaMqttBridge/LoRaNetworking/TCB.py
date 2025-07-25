import _thread
import gc
import random
import micropython_time as time

from collections import deque
from micropython import const

from LoRaNetworking.LoRaTCPSegment import Seq

# DataFrameMaxPayloadLength - (2 + 2 + 2 + 1) -> 241, Socket_ID, Flags, Seq_Number, ACK_Number
LoRaTCP_MAX_PAYLOAD_SIZE = const(241)

LOGLEVEL_DEBUG = const(0)
LOGLEVEL_INFO = const(1)
LOGLEVEL_WARNING = const(2)
LOGLEVEL_ERROR = const(3)

TCP_LOG_LEVEL = const(LOGLEVEL_DEBUG)


def _log(message: str, loglevel=LOGLEVEL_DEBUG):
    if loglevel == LOGLEVEL_DEBUG and TCP_LOG_LEVEL == LOGLEVEL_DEBUG:
        print(f"[TCB] \033[37mDebug: {message}\033[0m")
    elif loglevel == LOGLEVEL_INFO and TCP_LOG_LEVEL <= LOGLEVEL_INFO:
        print(f"[TCB] \033[92mInfo: {message}\033[0m")
    elif loglevel == LOGLEVEL_WARNING and TCP_LOG_LEVEL <= LOGLEVEL_WARNING:
        print(f"[TCB] \033[33mWarning: {message}\033[0m")
    elif loglevel == LOGLEVEL_ERROR and TCP_LOG_LEVEL <= LOGLEVEL_ERROR:
        print(f"[TCB] \033[31mError: {message}\033[0m")

class TCB:
    # TODO __slots__
    INSTANCES = list()
    SOCKET_ID_COUNTER = 0

    STATE_CLOSED = 0
    STATE_LISTEN = 1
    STATE_SYN_RCVD = 2
    STATE_SYN_SENT = 3
    STATE_ESTAB = 4
    STATE_FIN_WAIT_1 = 5
    STATE_CLOSE_WAIT = 6
    STATE_FIN_WAIT_2 = 7
    STATE_CLOSING = 8
    STATE_LAST_ACK = 9
    STATE_TIME_WAIT = 10

    RETRANSMISSION_TIMEOUT_MS = 1_500
    TIME_WAIT_TIMEOUT_MS = 1_000

    __slots__ = ('remote_ip', 'remote_port', 'socket_id', 'active_open', 'time_wait_timer', 'user_timeout_timer',
                 'retransmission_timeout_timer', 'snd_wnd', 'rcv_wnd', 'state', 'retransmission_queue',
                 'reassembled_data_lock',
                 'receive_buffer', 'reassembled_data', 'send_buffer', 'send_buffer_lock', 'MSL_TIMEOUT_MS', 'fin_seq',
                 'snd_una', 'snd_nxt',
                 'rcv_nxt', 'iss', 'irs'
                 )

    def __init__(self, remote_ip, remote_port):
        self.remote_ip = remote_ip
        self.remote_port = remote_port
        self.socket_id = TCB.SOCKET_ID_COUNTER
        TCB.SOCKET_ID_COUNTER += 1
        self.active_open = True

        # TIMEOUTS
        self.time_wait_timer = None
        self.user_timeout_timer = None
        self.retransmission_timeout_timer = None

        self.snd_wnd = LoRaTCP_MAX_PAYLOAD_SIZE  # Aktuelle größe des Sende-Fensters
        self.rcv_wnd = LoRaTCP_MAX_PAYLOAD_SIZE  # Aktuelle größe des Empfangs-Fensters

        self.state = TCB.STATE_CLOSED

        # Sende-Puffer für Daten die noch auf ein ACK warten
        self.retransmission_queue = deque(maxlen=20)  # type: Deque[LoRaTCPSegment]
        # Empfangs-Puffer für Daten die noch nicht an die Anwendung übergeben wurden
        self.receive_buffer = {}  # type: Dict[Seq, bytes]
        # Ein zusammenhängender Stream an Daten die für die Anwendung bestimmt sind und aus dem receive_buffer kommen
        self.reassembled_data = bytes()  # type: bytes
        self.reassembled_data_lock = _thread.allocate_lock()
        # Ein zusammenhängender Stream an Daten, die noch nicht gesendet wurden. Müssen nach Versand als Segment in die retransmission_queue kopiert werden
        self.send_buffer = bytes()
        self.send_buffer_lock = _thread.allocate_lock()

        self.MSL_TIMEOUT_MS = None

        self.fin_seq = None  # type: Seq

        self.snd_una = None  # type: Seq
        """
        SND.UNA: kleinste noch nicht bestätigte Sequenznummer
        The sender of data keeps track of the oldest unacknowledged sequence number in the variable SND.UNA
        When the data sender receives an acknowledgment it advances SND.UNA.
        [Source: RFC 793 pp. 40]
        """

        self.snd_nxt = None  # type: Seq
        """
        SND.NXT: nächste zu sendende Sequenznummer
        The sender of data keeps track of the next sequence number to use in the variable SND.NXT
        [Source: RFC 793 pp. 40]
        """

        self.rcv_nxt = None  # type: Seq
        """
        RCV.NXT: nächste erwartete Sequenznummer
        The receiver of data keeps track of the next sequence number to expect in the variable RCV.NXT
        When the receiver accepts a segment it advances RCV.NXT and sends an acknowledgment.
        [Source: RFC 793 pp. 40]
        Bei Empfang von Segment: Segment.Sequenznummer -> RCV.NXT
        """

        self.iss = Seq(random.getrandbits(16))  # type: Seq
        self.irs = None  # type: Seq
        TCB.INSTANCES.append(self)

    def remove_acknowledged_segments_from_retransmission_queue(self):
        segments_to_remove = []
        for seg in self.retransmission_queue:
            seg = seg  # type: LoRaTCPSegment
            if TCB.acknowledge_segment_in_retransmission_queue(seg.seq, len(seg.payload), self.snd_una):
                segments_to_remove.append(seg)
        self.retransmission_queue = deque([
            seg for seg in self.retransmission_queue
            if seg not in segments_to_remove
        ], 20)
        if len(segments_to_remove) > 0:
            del segments_to_remove
            _log(f"Removed acknowledged segments up to {self.snd_una} for socket {self.socket_id}")

    def is_ack_acceptable(self, ack: Seq) -> bool:
        return Seq(self.snd_una) < Seq(ack) <= Seq(self.snd_nxt)

    @staticmethod
    def acknowledge_segment_in_retransmission_queue(seg_seq: int, seg_len: int, incoming_ack: int) -> bool:
        """
        A segment on the retransmission queue is fully acknowledged
        if the sum of its sequence number and length is less or equal than the acknowledgment value in the incoming segment.
        :param seg_seq: Sequence number
        :param seg_len: Segment length
        :param incoming_ack: Acknowledgment value in the incoming segment
        :return: True if the segment was acknowledged, False otherwise
        """
        return (Seq(seg_seq) + Seq(seg_len)) <= incoming_ack

    @staticmethod
    def create_or_get_existing(address: str, port: int) -> "TCB":
        for tcb in TCB.INSTANCES:
            if tcb.remote_ip == address and tcb.remote_port == port:
                return tcb
        return TCB(address, port)

    @staticmethod
    def get_existing(socket_id: int) -> "TCB":
        for tcb in TCB.INSTANCES:
            if tcb.socket_id == socket_id:
                return tcb
        return None

    def start_time_wait_timer(self):
        self.time_wait_timer = time.ticks_ms()

    def start_retransmission_timeout_timer(self):
        self.retransmission_timeout_timer = time.ticks_ms()

    def cancel_all_timers(self):
        self.retransmission_timeout_timer = None
        self.user_timeout_timer = None
        self.time_wait_timer = None

    def delete(self):
        self.retransmission_timeout_timer = None
        self.user_timeout_timer = None
        self.time_wait_timer = None
        self.iss = Seq(random.getrandbits(16))  # type: Seq
        self.irs = None  # type: Seq
        self.remote_ip = None
        self.remote_port = None
        self.socket_id = None
        self.active_open = True
        self.time_wait_timer = None
        self.user_timeout_timer = None
        self.retransmission_timeout_timer = None
        self.snd_wnd = LoRaTCP_MAX_PAYLOAD_SIZE  # Aktuelle größe des Sende-Fensters
        self.rcv_wnd = LoRaTCP_MAX_PAYLOAD_SIZE  # Aktuelle größe des Empfangs-Fensters
        self.state = TCB.STATE_CLOSED
        self.retransmission_queue = deque(maxlen=20)  # type: Deque[LoRaTCPSegment]
        self.receive_buffer = {}  # type: Dict[Seq, bytes]
        self.reassembled_data = bytes()  # type: bytes
        self.send_buffer = bytes()
        self.MSL_TIMEOUT_MS = None
        self.fin_seq = None  # type: Seq
        self.snd_una = None  # type: Seq
        self.snd_nxt = None  # type: Seq
        self.rcv_nxt = None  # type: Seq
        gc.collect()