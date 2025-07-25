import random


class VoltageMeasurement:
    VOLTAGE_MAP = {
        0: 0,
        1: 2500,
        2: 4000,
        3: 6000,
        4: 8000
    }

    def get_voltage(self):
        voltage = random.randint(0, 4)
        print(f"[VoltageMeasurement] Mock measurement voltage: {voltage} -> {VoltageMeasurement.VOLTAGE_MAP[voltage]}")
        return VoltageMeasurement.VOLTAGE_MAP[voltage]
