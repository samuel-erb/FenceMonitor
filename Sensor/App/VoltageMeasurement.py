import random
import time


class VoltageMeasurement:
    def __init__(self):
        self.counter = 0
        self.simulated_voltage = [4, 0, 3]

    VOLTAGE_MAP = {
        0: 0,
        1: 2500,
        2: 4000,
        3: 6000,
        4: 8000
    }

    def get_voltage(self):
        print(f"[VoltageMeasurement] Starting mock measurement voltage. Sleeping for 5 seconds...")
        time.sleep(5)
        # voltage = random.randint(0, 4)
        ## For presentation video
        voltage = self.simulated_voltage[self.counter]
        self.counter = self.counter + 1 if self.counter < len(self.simulated_voltage) - 1 else 0
        ## For presentation video end
        print(f"[VoltageMeasurement] Mock measurement voltage: {voltage} -> {VoltageMeasurement.VOLTAGE_MAP[voltage]}")
        return VoltageMeasurement.VOLTAGE_MAP[voltage]
