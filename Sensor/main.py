import asyncio
import time

import machine
from micropython import const

from App.ApplicationData import ApplicationData
from App.LightSleepManager import LightSleepManager
from App.LocationService import LocationService
from App.VoltageMeasurement import VoltageMeasurement
from umqtt.lora import LoRaMQTTClient

SENSOR_ID = int.from_bytes(machine.unique_id(), "big") & 0xFF
MQTT_TOPIC_MEASUREMENT = b'fence_sensor/measure/voltage'
MQTT_TOPIC_VOLTAGE_THRESHOLD = b'fence_sensor/measure/threshold'
MQTT_TOPIC_LOCATION_UPDATE = b'fence_sensor/update/location/' + str(SENSOR_ID).encode('utf-8')
SLEEP_DURATION_MILLISECONDS = const(300_000) # const(60_000) # 1 minute # const(300_000) # 5 minutes

threshold_voltage = 8_000 # Volt
location_should_update = True

def mqtt_callback(topic, msg):
    print(f"[App] MQTT callback called with topic {topic}")
    if topic not in [MQTT_TOPIC_VOLTAGE_THRESHOLD, MQTT_TOPIC_LOCATION_UPDATE]:
        return

    if topic == MQTT_TOPIC_VOLTAGE_THRESHOLD:
        threshold_byte = int.from_bytes(msg, "big")
        global threshold_voltage
        old_threshold_voltage = threshold_voltage
        threshold_voltage = VoltageMeasurement.VOLTAGE_MAP[threshold_byte]
        print(f"[App] Updated voltage threshold: {old_threshold_voltage} -> {threshold_voltage}")
    elif topic == MQTT_TOPIC_LOCATION_UPDATE:
        global location_should_update
        location_should_update = True
        print(f"[App] Location update requested")


async def main(mqtt_client: LoRaMQTTClient):
    print("[App] Starting")
    mqtt_client.set_callback(mqtt_callback)
    global location_should_update
    last_measurement_sent = None
    location_service = LocationService()
    sleep_manager = LightSleepManager(SLEEP_DURATION_MILLISECONDS)
    voltage_sensor = VoltageMeasurement()
    critical_voltage_before = True

    print("[App] Subscribing to topic " + MQTT_TOPIC_VOLTAGE_THRESHOLD.decode('utf-8'))
    mqtt_client.subscribe(MQTT_TOPIC_VOLTAGE_THRESHOLD)
    print("[App] Subscribing to topic " + MQTT_TOPIC_LOCATION_UPDATE.decode('utf-8'))
    mqtt_client.subscribe(MQTT_TOPIC_LOCATION_UPDATE)

    while True:
        print("[App] Measuring voltage...")
        voltage = voltage_sensor.get_voltage()
        print("[App] Voltage: %.1f kV" % (voltage / 1000))

        print("[App] Getting battery status...")
        battery = 1.0
        print(f"[App] Battery: {battery * 100}%")

        if location_should_update:
            print("[App] Getting location update...")
            location = location_service.get_location()
            print(f"[App] Location: lat={location[0]}, lon={location[1]}")
            data = ApplicationData(SENSOR_ID, voltage, battery, location[0], location[1])
            send_voltage_measurement(mqtt_client, data)
            last_measurement_sent = time.ticks_ms()
            location_should_update = False
            if voltage <= threshold_voltage:
                critical_voltage_before = True
        elif critical_voltage_before:
            data = ApplicationData(SENSOR_ID, voltage, battery)
            send_voltage_measurement(mqtt_client, data)
            last_measurement_sent = time.ticks_ms()
            critical_voltage_before = False
        elif voltage <= threshold_voltage:
            data = ApplicationData(SENSOR_ID, voltage, battery)
            send_voltage_measurement(mqtt_client, data)
            last_measurement_sent = time.ticks_ms()
            critical_voltage_before = True
        elif time.ticks_diff(last_measurement_sent, time.ticks_ms()) > 3_000_000: # 50 min
            data = ApplicationData(SENSOR_ID, voltage, battery)
            send_voltage_measurement(mqtt_client, data)
            last_measurement_sent = time.ticks_ms()
        else:
            critical_voltage_before = False
            print(f"[App] No location update requested, last measurement was sent within the last hour "
                  f"and the measured voltage is greater or equal the threshold {threshold_voltage} >= {voltage} "
                  f"-> going back to sleep without sending data to MQTT Broker")
        await asyncio.sleep(10)
        await sleep_manager.sleep()

def send_voltage_measurement(mqtt_client: LoRaMQTTClient, measurement: ApplicationData):
    print(f"[App] Sending measurement {measurement}")
    mqtt_client.publish(MQTT_TOPIC_MEASUREMENT, measurement.to_bytes(), False, 0)