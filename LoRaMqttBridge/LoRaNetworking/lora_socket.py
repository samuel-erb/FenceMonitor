import time

from micropython import const

import LoRaNetworking

_DEBUG = const(True)


class LoRaTCPSocket:
    __slots__ = (
        '_lora', '_timeout', '_blocking', '_recv_buffer', 'send_buffer',
        '_closed', '_peer'
    )

    def __init__(self):
        self._lora = LoRaNetworking.LoRaTCP() # type: LoRaNetworking.LoRaTCP
        self._timeout = None
        self._blocking = True
        self._recv_buffer = bytearray()
        self.send_buffer = bytearray()
        self._closed = False
        self._peer = None

    def connect(self, address):
        self._peer = address
        self._lora.register(address[0], address[1], self)
        return 0

    def settimeout(self, timeout):
        if timeout is None:
            self._blocking = True
            self._timeout = None
        elif timeout == 0:
            self._blocking = False
            self._timeout = 0
        else:
            self._blocking = True
            self._timeout = timeout

    def setblocking(self, flag):
        self._blocking = bool(flag)
        if flag:
            self._timeout = None
        else:
            self._timeout = 0

    def write(self, data, size=None):
        if self._closed:
            raise OSError("Socket is closed")
        if self._peer is None:
            raise OSError("Socket is not connected")
        self.send_buffer.extend(data)
        if _DEBUG:
            print(f"[LoRaTCPSocket] Write data {data}")
        return len(data)

    def read(self, bufsize=242):
        if self._closed:
            raise OSError("Socket is closed")

        start_time = time.ticks_ms()
        while len(self._recv_buffer) < bufsize:
            if self._blocking:
                if self._timeout is not None:
                    elapsed = (time.ticks_ms() - start_time) / 1000
                    if elapsed >= self._timeout:
                        raise OSError(110)  # ETIMEDOUT
                time.sleep_ms(10)
            else:
                break

        data = self._recv_buffer[:bufsize]
        self._recv_buffer = self._recv_buffer[bufsize:]
        return data

    def close(self):
        self._closed = True
        self._lora.close(self)

    def _append_data(self, data):
        self._recv_buffer.extend(data)

    def fileno(self):
        return -1

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
