"""
SX1276/77/78/79 LoRa Configuration Parameters
Based on Semtech SX1276/77/78/79 Datasheet Rev 7

This file contains the configuration parameters for the SX1276/77/78/79 LoRa modem.
"""
from micropython import const

from machine import Pin, SPI

from config import hardware_config
from lora import SX1262

# Frequency settings (in kHz)
# Valid ranges per band:
# Band 1 (HF): 862-1020 MHz (779-960 MHz for SX1279)
# Band 2 (LF): 410-525 MHz (410-480 MHz for SX1279)
# Band 3 (LF): 137-175 MHz (137-160 MHz for SX1279)
FREQ_KHZ = 434000  # 868 MHz

# Image calibration settings
# Controls the automatic image calibration mechanism
# False = Calibration of the receiver depending on temperature is disabled
# True = Calibration of the receiver depending on temperature enabled
AUTO_IMAGE_CAL = True

# Transmit antenna selection
# Options:
# "RFO" = Use RFO pin for output powers up to +14 dBm
# "PA_BOOST" = Use PA_BOOST pin for output powers up to +20 dBm
TX_ANT = "PA_BOOST"

# Output power in dBm
# Range depends on TX_ANT:
# If TX_ANT = "RFO": -4 to +15 dBm
# If TX_ANT = "PA_BOOST": +2 to +17 dBm (up to +20 dBm with special settings)
OUTPUT_POWER = 22

# PA ramp time in microseconds
# Controls the rise/fall time of ramp up/down in FSK
# Options: 3400, 2000, 1000, 500, 250, 125, 100, 62, 50, 40, 31, 25, 20, 15, 12, 10 μs
PA_RAMP_US = 40

# Signal bandwidth in kHz
# Available bandwidths: 7.8, 10.4, 15.6, 20.8, 31.25, 41.7, 62.5, 125, 250, 500 kHz
# Note: In the lower band (169 MHz), 250 kHz and 500 kHz are not supported
BW = 125

# Error coding rate (forward error correction)
# Options:
# 5 = 4/5 (1 error checking bit for every 4 data bits)
# 6 = 4/6 (2 error checking bits for every 4 data bits)
# 7 = 4/7 (3 error checking bits for every 4 data bits)
# 8 = 4/8 (4 error checking bits for every 4 data bits)
CODING_RATE = 5

# Header mode
# False = Explicit header mode (header with payload length, coding rate, and CRC presence)
# True = Implicit header mode (fixed payload length, no header, SF6 requires implicit mode)
IMPLICIT_HEADER = False

# Spreading factor
# Options: 6, 7, 8, 9, 10, 11, 12
# Higher SF = longer range, lower data rate, higher sensitivity
# Note: SF6 requires implicit header mode
SF = 12

# CRC generation on payload
# True = Enable CRC generation and check on payload
# False = Disable CRC generation and check on payload
CRC_EN = True

# Invert I and Q signals in RX path
# False = Normal mode
# True = I and Q signals are inverted
INVERT_IQ_RX = False

# Invert I and Q signals in TX path
# False = Normal mode
# True = I and Q signals are inverted
INVERT_IQ_TX = False

# Preamble length in symbols
# Default is 8, which gives a total of 8 + 4.25 = 12.25 symbols of preamble
# Longer preambles improve receiver sensitivity but increase airtime
PREAMBLE_LEN = 10

# LNA gain setting (receiver gain)
# None = Auto gain (AGC controls gain)
# 1 = Highest gain (G1)
# 2 = G2 (-6dB from max)
# 3 = G3 (-12dB from max)
# 4 = G4 (-24dB from max)
# 5 = G5 (-36dB from max)
# 6 = G6 (-48dB from max)
LNA_GAIN = None

# Enable RX boost for HF signals (improves sensitivity)
# True = Boost on, 150% LNA current
# False = Default LNA current
RX_BOOST = True

# LNA Boost for High Frequency (RFI_HF) LNA current adjustment
# Used for band 1 (high frequency operation)
# Options:
# 0 = Default LNA current
# 3 = Boost on, 150% LNA current
# Higher values improve sensitivity at the cost of increased current consumption
LNA_BOOST_HF = 0

# Sync word for LoRa network identification
# Default is 0x12
# Value 0x34 is reserved for LoRaWAN networks
SYNCWORD = 0x12

def configure_modem() -> SX1262:
    # Konfiguration für den LoRa-Treiber (Spreading Factor, Bandbreite, etc.)
    # Diese Parameter bestimmen das Verhalten auf der Bitübertragungsschicht (Physical Layer).
    lora_cfg = {
        "freq_khz": FREQ_KHZ,
        "tx_ant": TX_ANT,
        "output_power": OUTPUT_POWER,
        "pa_ramp_us": PA_RAMP_US,
        "bw": BW,
        "coding_rate": CODING_RATE,
        "implicit_header": IMPLICIT_HEADER,
        "sf": SF,
        "crc_en": CRC_EN,
        "invert_iq_rx": INVERT_IQ_RX,
        "invert_iq_tx": INVERT_IQ_TX,
        "preamble_len": PREAMBLE_LEN,
        "rx_boost": RX_BOOST,
        "syncword": SYNCWORD,
    }

    # Initialisierung der SPI- und GPIO-Schnittstellen für den SX1262
    LoRa_NSS = Pin(hardware_config.LoRa_NSS)
    LoRa_SCK = Pin(hardware_config.LoRa_SCK)
    LoRa_MOSI = Pin(hardware_config.LoRa_MOSI)
    LoRa_MISO = Pin(hardware_config.LoRa_MISO)
    LoRa_RST = Pin(hardware_config.LoRa_RST)
    LoRa_BUSY = Pin(hardware_config.LoRa_BUSY)
    DIO1 = Pin(hardware_config.DIO1)

    CAD_ON_1_SYMB = const(0x00) # Verwende 1 Symbol für Channel Activity Detection
    CAD_ON_2_SYMB = const(0x01) # Verwende 2 Symbol für Channel Activity Detection
    CAD_ON_4_SYMB = const(0x02) # Verwende 4 Symbol für Channel Activity Detection
    CAD_ON_8_SYMB = const(0x03) # Verwende 8 Symbol für Channel Activity Detection
    CAD_ON_16_SYMB = const(0x04)# Verwende 6 Symbol für Channel Activity Detection

    spi = SPI(
        hardware_config.LoRa_SPI_Channel_ID,
        baudrate=hardware_config.LoRa_Baudrate,
        polarity=hardware_config.LoRa_Polarity,
        phase=hardware_config.LoRa_Phase,
        sck=LoRa_SCK,
        mosi=LoRa_MOSI,
        miso=LoRa_MISO
    )
    
    modem = SX1262(
        spi=spi,
        cs=LoRa_NSS,
        busy=LoRa_BUSY,
        dio1=DIO1,
        reset=LoRa_RST,
        dio3_tcxo_millivolts=3300,
        lora_cfg=lora_cfg
    )

    modem.configure_cad(
        cad_symbol_num=CAD_ON_2_SYMB,    # 2 Symbole für Detection
        cad_detect_peak=22,  # Peak-Schwelle
        cad_detect_min=10,   # Min-Schwelle
        cad_exit_mode=1      # Nach CAD zu Receive
    )

    return modem

def diagnose_lora(lora_modem: SX1262):
    """
    Führt eine Diagnose des SX1262 LoRa-Modems durch
    """
    # SX1262 Register
    REG_LSYNCRH = 0x740
    REG_LSYNCRL = 0x741
    REG_RX_GAIN = 0x08AC
    print("\n=== SX1262 LoRa Modem Diagnose ===")

    # Status abfragen
    try:
        status = lora_modem._get_status()
        mode, cmd_status = status
        print(f"Status Mode: {mode} (2=STDBY_RC, 3=STDBY_HSE32, 5=RX, 6=TX)")
        print(f"Command Status: {cmd_status}")
    except Exception as e:
        print(f"Fehler beim Status-Abruf: {e}")

    # Fehler abfragen
    try:
        error_status = lora_modem._check_error()
        print(f"Error Status: {error_status} (Keine Fehler wenn kein Fehler geworfen wurde)")
    except Exception as e:
        print(f"Aktuelle Fehler: {e}")

    # Frequenz (aus gespeichertem Wert)
    freq_mhz = lora_modem._rf_freq_hz / 1_000_000
    print(f"Konfigurierte Frequenz: {freq_mhz:.3f} MHz")

    # Spreading Factor
    print(f"Spreading Factor: {lora_modem._sf}")

    # Bandwidth
    print(f"Bandwidth: {lora_modem._bw} kHz")

    # Coding Rate
    print(f"Coding Rate: 4/{lora_modem._coding_rate}")

    # Preamble
    print(f"Preamble Länge: {lora_modem._preamble_len}")

    # Output Power
    print(f"Output Power: {lora_modem._output_power} dBm")

    # CRC
    print(f"CRC: {'Aktiviert' if lora_modem._crc_en else 'Deaktiviert'}")

    # Implicit Header
    print(f"Header Mode: {'Implicit' if lora_modem._implicit_header else 'Explicit'}")

    # IQ Einstellungen
    print(f"IQ RX Invert: {lora_modem._invert_iq[0]}")
    print(f"IQ TX Invert: {lora_modem._invert_iq[1]}")

    # Sync Word Register lesen
    try:
        sync_h = lora_modem._reg_read(REG_LSYNCRH)
        sync_l = lora_modem._reg_read(REG_LSYNCRL)
        syncword = (sync_h << 8) | sync_l
        print(f"Sync Word: 0x{syncword:04X}")
    except Exception as e:
        print(f"Fehler beim Sync Word Lesen: {e}")

    # RX Gain Register
    try:
        rx_gain = lora_modem._reg_read(REG_RX_GAIN)
        print(f"RX Gain: 0x{rx_gain:02X} ({'Boost' if rx_gain == 0x96 else 'Normal'})")
    except Exception as e:
        print(f"Fehler beim RX Gain Lesen: {e}")

    print("=== Diagnose abgeschlossen ===\n")