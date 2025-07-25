import asyncio
import json
import time
import struct

#from paho.mqtt.client import Client, MQTTMessage, MQTTv5, Properties
import paho.mqtt.client as mqtt


MQTT_BROKER = "192.168.1.125"
MQTT_PORT = 1883
MQTT_TOPIC_SENSOR_MEASUREMENT = "sensor/measurement"
MQTT_TOPIC_SENSOR_COMMAND = "sensor/command"

# === LoRa-Schnittstelle (Mock) ===
class MockLoRaInterface:
    def __init__(self):
        self._receive_queue = asyncio.Queue()

    async def receive(self) -> str:
        return await self._receive_queue.get()

    async def send(self, data: str):
        print(f"[LoRa] → Gesendet: {data}")

    # Simulation: externe Nachricht empfangen
    async def simulate_incoming_message(self, data: str):
        await self._receive_queue.put(data)

# === LoRa-Paket ===

class LoraPacket:
    def __init__(self, deviceId: int, batteryPercentage: int, voltage: int, latitude: float, longitude: float):
        self.deviceId = deviceId
        self.batteryPercentage = batteryPercentage
        self.voltage = voltage
        self.latitude = latitude
        self.longitude = longitude

    @staticmethod
    def from_bytes(data: bytes) -> "LoraPacket":
        if len(data) != 11:
            raise ValueError("Ungültige Datenlänge für LoraPacket")

        device_id = data[0]
        battery = data[1]
        voltage = data[2]
        latitude, longitude = struct.unpack(">ii", data[3:11])

        return LoraPacket(device_id, battery, voltage, latitude / 1e6, longitude / 1e6)

# === MQTT-Client ===

class MQTTBridge:
    def __init__(self, lora_interface, broker=MQTT_BROKER, port=MQTT_PORT, retry_interval=5):
        self.lora = lora_interface
        self.broker = broker
        self.port = port
        self.retry_interval = retry_interval
        self.loop = asyncio.get_event_loop()

        self.client = mqtt.Client(
            protocol=mqtt.MQTTv5,
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2
        )
        self.client.on_connect = self.on_connect_v5
        self.client.on_message = self.on_message_v5

    def on_connect_v5(self, client, userdata, flags, reason_code, properties: mqtt.Properties):
        print(f"[MQTT] Verbunden mit {self.broker}:{self.port} – Grund: {reason_code}")
        client.subscribe(MQTT_TOPIC_SENSOR_COMMAND)

    def on_message_v5(self, client, userdata, msg: mqtt.MQTTMessage):
        payload = msg.payload.decode()
        print(f"[MQTT] → Nachricht empfangen: {payload}")
        asyncio.run_coroutine_threadsafe(self.lora.send(payload), self.loop)

    def start(self):
        connected = False
        while not connected:
            try:
                print(f"[MQTT] Versuche Verbindung zu {self.broker}:{self.port} ...")
                self.client.connect(self.broker, self.port, clean_start=True)
                self.client.loop_start()
                connected = True
                print(f"Connected: {self.broker}:{self.port}")
            except (ConnectionRefusedError) as e:
                print(f"[MQTT] Verbindung fehlgeschlagen: {e}. Neuer Versuch in {self.retry_interval}s ...")
                time.sleep(self.retry_interval)

# === Main Loop ===

async def lora_to_mqtt_loop(lora: MockLoRaInterface, mqtt_client: mqtt.Client):
    while True:
        message = await lora.receive()
        print(f"[LoRa] ← Empfangen: {message}")
        mqtt_client.publish(MQTT_TOPIC_SENSOR_MEASUREMENT, message)

async def main():
    lora = MockLoRaInterface()
    mqtt_bridge = MQTTBridge(lora)
    mqtt_bridge.start()

    asyncio.create_task(lora_to_mqtt_loop(lora, mqtt_bridge.client))

    # Simuliere eingehende LoRa-Nachricht alle 10 Sekunden
    while True:
        await asyncio.sleep(10)
        #raw_data = bytes([1, 85, 33]) + struct.pack(">ii", 52559174, 12559905)
        #packet = LoraPacket.from_bytes(raw_data)
        packet = LoraPacket(1, 85, 60000, 52559174, 12559905)
        #print(packet.deviceId, packet.latitude, packet.longitude)
        await lora.simulate_incoming_message(json.dumps(packet.__dict__))

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Beende...")



# ------------------

# SPI und Pins konfigurieren
import micropython_time as time
import logging
import RPi.GPIO as GPIO

import lora.lora_socket
from LoRaMQTTBridge import LoRaMQTTBridge

import configs.lora_config as lora_config
from lora import SX1276, RxPacket
from machine import Pin, SPI

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("LoRaMQTTBridge Runner")

MQTT_BROKER = "192.168.1.125"
MQTT_PORT = 1883
MQTT_TOPIC_SENSOR_MEASUREMENT = "sensor/measurement"
MQTT_TOPIC_SENSOR_COMMAND = "sensor/command"

lora_cfg = {
    "freq_khz": lora_config.FREQ_KHZ,
    "auto_image_cal": lora_config.AUTO_IMAGE_CAL,
    "tx_ant": lora_config.TX_ANT,
    "output_power": lora_config.OUTPUT_POWER,
    "pa_ramp_us": lora_config.PA_RAMP_US,
    "bw": lora_config.BW,
    "coding_rate": lora_config.CODING_RATE,
    "implicit_header": lora_config.IMPLICIT_HEADER,
    "sf": lora_config.SF,
    "crc_en": lora_config.CRC_EN,
    "invert_iq_rx": lora_config.INVERT_IQ_RX,
    "invert_iq_tx": lora_config.INVERT_IQ_TX,
    "preamble_len": lora_config.PREAMBLE_LEN,
    "lna_gain": lora_config.LNA_GAIN,
    "rx_boost": lora_config.RX_BOOST,
    "syncword": lora_config.SYNCWORD,
    "lna_boost_hf": lora_config.LNA_BOOST_HF
}

def lora_receiver(lora_modem):
    """Einfacher LoRa-Empfänger für Tests"""
    print("\n=== LoRa Empfänger Modus ===")
    while True:
        print("Warte auf Nachricht...")
        packet = lora_modem.recv(timeout_ms=5000)  # 5 Sekunden Timeout

        if packet:
            message = packet.decode('utf-8', 'ignore')
            print(f"Empfangen: {message}")
            print(f"RSSI: {packet.rssi} dBm")
            print(f"SNR: {packet.snr / 4:.2f} dB")
            print(f"CRC OK: {packet.valid_crc}")
            print("-" * 30)
        else:
            print("Timeout - keine Nachricht empfangen")

def lora_sender(lora_modem):
    """Einfacher LoRa-Sender für Tests"""
    print("\n=== LoRa Sender Modus ===")
    counter = 0
    try:
        while True:
            message = f"Test Nachricht #{counter}"
            packet = RxPacket(message.encode())
            print(f"Sende: {message}")

            start_time = time.ticks_ms()
            result = lora_modem.send(packet)
            end_time = time.ticks_ms()

            print(f"Gesendet in {time.ticks_diff(end_time, start_time)}ms")
            counter += 1
            time.sleep(2)
    except KeyboardInterrupt:(
        logger.info("Beenden durch Benutzer"))
    finally:
        GPIO.cleanup()


# Beispiel für die Verwendung
if __name__ == "__main__":
    # SX1276 zu Raspberry Pi Pin-Verbindungen:
    #
    # SX1276 Pin | Raspberry Pi Pin          | GPIO Number | Beschreibung
    # -----------|---------------------------|-------------|-------------------
    # VCC        | Pin 1 oder 17             | 3.3V        | Stromversorgung (3.3V!)
    # GND        | Pin 6,9,14,20,25,30,34,39 | GND         | Masse
    # SCK/SCLK   | Pin 23                    | GPIO 11     | SPI Clock
    # MISO       | Pin 21                    | GPIO 9      | Master In Slave Out
    # MOSI       | Pin 19                    | GPIO 10     | Master Out Slave In
    # NSS/CS     | Pin 24                    | GPIO 8 (CE0)| Chip Select
    # RESET      | Pin 16                    | GPIO 23     | Reset Pin
    # DIO0       | Pin 11                    | GPIO 17     | Digital I/O 0 (IRQ)
    # DIO1       | Pin 13                    | GPIO 27     | Digital I/O
    try:
        # Modem initialisieren (passe die Pin-Nummern an deine Verkabelung an)
        #spi=SPI(1, baudrate=1000000, polarity=0, phase=0,sck=Pin(9), mosi=Pin(10), miso=Pin(11))
        spi = SPI(0)
        #cs = Pin(8, Pin.OUT, value=1)  # CS pin, start high (deselected)
        reset = Pin(23, Pin.OUT, value=1)  # Reset pin, start high
        dio0 = Pin(17, Pin.IN)  # DIO0/IRQ pin for interrupts
        dio1 = Pin(27, Pin.IN)  # BUSY/DIO1 pin

        print("Resetting LoRa module...")
        reset.value(0)
        time.sleep(0.01)  # 10ms
        reset.value(1)
        time.sleep(0.01)  # 10ms
        #lora_modem = SX1276(spi=spi, cs_pin=25, reset_pin=24, dio0_pin=22, lora_cfg=lora_cfg)
        lora_modem = SX1276(spi=spi, dio0=dio0, dio1=dio1, reset=reset, lora_cfg=lora_cfg)

        # Print module settings
        print(f"LoRa module initialized at {lora_cfg['freq_khz'] / 1000} MHz")
        print(f"Bandwidth: {lora_cfg['bw']} kHz")
        print(f"Spreading factor: SF{lora_cfg['sf']}")
        print(f"Coding rate: 4/{lora_cfg['coding_rate']}")

        # Perform image calibration
        print("Starting calibration...")
        lora_modem.calibrate()
        print("Calibration complete")

        lora_sender(lora_modem)

        # Bridge initialisieren und starten
        bridge = LoRaMQTTBridge(
            lora_modem,
            mqtt_broker="localhost",
            mqtt_port=1883,
            local_addr=0x01,
            base_topic="sensors/"
        )

        if bridge.start():
            logger.info("Bridge gestartet. Zum Beenden Strg+C drücken.")

            # Bridge am Laufen halten
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                logger.info("Beenden durch Benutzer")
            finally:
                bridge.stop()

    except Exception as e:
        logger.error(f"Fehler bei der Initialisierung: {e}", exc_info=True)