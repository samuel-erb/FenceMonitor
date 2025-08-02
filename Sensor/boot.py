import gc
import machine
import uasyncio as asyncio

from LoRaNetworking.LoRaNetworking import LoRaNetworking
from umqtt.lora import LoRaMQTTClient

async def check_msg(mqtt_client: LoRaMQTTClient):
    while True:
        try:
            mqtt_client.check_msg()
        except OSError as e:
            machine.reset()
        await asyncio.sleep(1)

async def collect_garbage():
    while True:
        gc.collect()
        await asyncio.sleep(10)

async def main():
    try:
        gc.enable()
        LoRaNetworking()
        await asyncio.sleep(2)
        mqtt_client = LoRaMQTTClient(client_id=machine.unique_id().hex(), server="192.168.1.125", keepalive=60 * 6)
        try:
            mqtt_client.connect(clean_session=False)
        except Exception:
            print("Failed to connect to MQTT broker. Resetting machine...")
            machine.reset()
        print("MQTT connected")

        asyncio.create_task(check_msg(mqtt_client))
        asyncio.create_task(collect_garbage())

        print("Launching main.py")
        try:
            import main
            asyncio.create_task(main.main(mqtt_client))
        except Exception as e:
            print(f"main.py import error: {e}")
        while True:
            await asyncio.sleep(10)
    except KeyboardInterrupt:
        LoRaNetworking().stop()
        machine.reset()

asyncio.run(main())