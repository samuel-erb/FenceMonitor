import asyncio

import machine
import time

from LoRaNetworking.LoRaNetworking import LoRaNetworking


class LightSleepManager:
    def __init__(self, sleep_duration_milliseconds = 300_000):
        self.last_bedtime = None  # :)
        self.lora_networking = LoRaNetworking()
        self.sleep_duration_ms = sleep_duration_milliseconds

    def _check_if_we_can_go_to_bed(self):
        return self.lora_networking.is_sleep_ready()

    async def sleep(self, time_ms: int = -1, force=False):
        sleep_ms = self.sleep_duration_ms if time_ms == -1 else time_ms
        if force:
            print("[LightSleepManager] Going to bed... 💤")
            for pin in range(0, 46):
                try:
                    p = machine.Pin(pin, machine.Pin.IN, machine.Pin.PULL_DOWN)
                except:
                    pass
            time.sleep(10)
            machine.deepsleep(sleep_ms)
        else:
            print("[LightSleepManager] Checking if we can go to bed...")
            while not self._check_if_we_can_go_to_bed():
                await asyncio.sleep_ms(100)
            print("[LightSleepManager] Going to bed... 💤")
            self.lora_networking.prepare_for_sleep()
            for pin in range(0, 46):
                try:
                    p = machine.Pin(pin, machine.Pin.IN, machine.Pin.PULL_DOWN)
                except:
                    pass
            time.sleep(10)
            machine.deepsleep(sleep_ms)
        print("[LightSleepManager] Woke up... 🥱")
        self.lora_networking.send_woke_up_msg()
