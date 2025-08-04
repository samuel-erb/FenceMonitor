import time

from GPS.NEO6M import NEO6M

class LocationService:
    def __init__(self):
        self.gps_module = NEO6M()

    def get_location(self) -> tuple[float, float]: # tuple(latitude, longitude)
        self.gps_module.set_power_mode(NEO6M.ECO_MODE)
        print("[LocationService] GPS fix detected")
        (latitude, longitude) = self.gps_module.get_position(10_000)
        print(f"[LocationService] Got location: latitude={latitude}, longitude={longitude}")
        #self.gps_module.set_power_mode(NEO6M.POWER_SAVE_MODE)
        return (latitude, longitude)

    def test(self):
        self.gps_module.test_power_save_mode()

