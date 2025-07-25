import time

from machine import Pin, SPI

from config import hardware_config, lora_config
from lora import SX1262, RxPacket

LoRa_NSS = Pin(hardware_config.LoRa_NSS)
LoRa_SCK = Pin(hardware_config.LoRa_SCK)
LoRa_MOSI = Pin(hardware_config.LoRa_MOSI)
LoRa_MISO = Pin(hardware_config.LoRa_MISO)
LoRa_RST = Pin(hardware_config.LoRa_RST)
LoRa_BUSY = Pin(hardware_config.LoRa_BUSY)
DIO1 = Pin(hardware_config.DIO1)

spi = SPI(
    hardware_config.LoRa_SPI_Channel_ID,
    baudrate=hardware_config.LoRa_Baudrate,
    polarity=hardware_config.LoRa_Polarity,
    phase=hardware_config.LoRa_Phase,
    sck=LoRa_SCK,
    mosi=LoRa_MOSI,
    miso=LoRa_MISO
)

lora_cfg = {
    "freq_khz": lora_config.FREQ_KHZ,
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
    "rx_boost": lora_config.RX_BOOST,
    "syncword": lora_config.SYNCWORD,
}

driver = SX1262(
            spi=spi,
            cs=LoRa_NSS,
            busy=LoRa_BUSY,
            dio1=DIO1,
            reset=LoRa_RST,
            dio3_tcxo_millivolts=3300,
            lora_cfg=lora_cfg
        )

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
    except KeyboardInterrupt:
        pass

while True:
    lora_sender(driver)