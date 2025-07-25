import micropython_time as time
from lora_gateway import LoRaGateway
from machine import Pin, SPI
from lora import RxPacket, SX1262
import configs.lora_config as lora_config

# LoRa Konfiguration
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

spi = SPI(0)
LoRa_NSS = Pin(21)  # CS/NSS pin
LoRa_RST = Pin(18)
LoRa_BUSY = Pin(20)
DIO1= Pin(16)

def init_lora():
    """Initialisiert das LoRa-Modem"""
    print("Initialisiere LoRa-Modem...")
    try:
        lora_modem = SX1262(
            spi=spi, cs=LoRa_NSS, busy=LoRa_BUSY, dio1=DIO1, reset=LoRa_RST,
            lora_cfg=lora_cfg
        )
        print("LoRa-Modem erfolgreich initialisiert!")
        return lora_modem
    except Exception as e:
        print(f"Fehler bei der Initialisierung: {e}")
        return None

def lora_sender(lora_modem):
    """Einfacher LoRa-Sender für Tests"""
    print("\n=== LoRa Sender Modus ===")
    counter = 0
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

lora_modem = init_lora()
lora_sender(lora_modem)