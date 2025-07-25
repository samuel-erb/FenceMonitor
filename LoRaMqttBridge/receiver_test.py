from config import lora_config, hardware_config
from lora import SX1262
from machine import Pin, SPI


def lora_receiver(lora_modem):
    """Einfacher LoRa-Empfänger für Tests"""
    print("\n=== LoRa Empfänger Modus ===")
    while True:
        packet = lora_modem.recv(timeout_ms=100)  # 5 Sekunden Timeout

        if packet:
            #message = packet.decode('utf-8', 'ignore')
            print(f"Empfangen: {packet}")
            print(f"RSSI: {packet.rssi} dBm")
            print(f"SNR: {packet.snr / 4:.2f} dB")
            print(f"CRC OK: {packet.valid_crc}")
            print("-" * 30)

# Konfiguration für den LoRa-Treiber (Spreading Factor, Bandbreite, etc.)
# Diese Parameter bestimmen das Verhalten auf der Bitübertragungsschicht (Physical Layer).
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

# Initialisierung der SPI- und GPIO-Schnittstellen für den SX1262
LoRa_NSS = Pin(21)  # CS/NSS pin
LoRa_RST = Pin(18)
LoRa_BUSY = Pin(20)
DIO1= Pin(16)

spi = SPI(0)

modem = SX1262(
            spi=spi, cs=LoRa_NSS, busy=LoRa_BUSY, dio1=DIO1, reset=LoRa_RST,
            lora_cfg=lora_cfg
        )

if __name__ == "__main__":
    while True:
        lora_receiver(modem)

