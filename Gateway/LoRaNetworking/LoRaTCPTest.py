import threading

import time

from .LoRaTCP import LoRaTCP
from .TCPDataLink import TCPDataLink


class LoRaTCPTest(LoRaTCP):

    def __init__(self, gateway: bool, server_host='127.0.0.1', server_port=8080):
        super().__init__()
        self._data_link = TCPDataLink(server_port=server_port, server_host=server_host, listen=gateway)