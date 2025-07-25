import _thread
import threading

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
        self.running = False

    def set_tcp_active(self, socket_id, active):
        for tcp in LoRaTCP.INSTANCES:  # type: LoRaTCP
            if tcp.tcb.socket_id == socket_id:
                if active:
                    tcp.mark_active()
                else:
                    tcp.mark_inactive()

