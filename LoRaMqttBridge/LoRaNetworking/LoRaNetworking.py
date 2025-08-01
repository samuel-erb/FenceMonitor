import _thread
import threading

import time

from .LoRaDataLink import LoRaDataLink
from .LoRaTCP import LoRaTCP
from Singleton import Singleton

class LoRaNetworking(Singleton):
    def _init_once(self, *args, **kwargs):
        self.data_link = LoRaDataLink()
        self.networking_thread = _thread.start_new_thread(self._networking_worker, (self,))
        self.running = True


    def _networking_worker(self, _):
        print("[LoRaNetworking] Networking thread started")
        while self.running:
            for tcp in LoRaTCP.INSTANCES: # type: LoRaTCP
                tcp.run()
            self.data_link.run()
        print("[LoRaNetworking] Networking thread stopped")

    def stop(self):
        print("[LoRaNetworking] Gracefully stopping networking thread")
        for tcp in LoRaTCP.INSTANCES:  # type: LoRaTCP
            tcp.stop()
        time.sleep(10)
        self.running = False

