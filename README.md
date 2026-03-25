# FenceMonitor

Ein LoRaWAN-basiertes Zaunüberwachungssystem für die Erkennung von Spannungsabfällen an Elektrozäunen mit GPS-Lokalisierung und Telegram-Bot-Integration.

[Dokumentation Netzwerk-Stack](./Sensor/LoRaNetworking/README.md)

[Masterarbeit](Erb_Samuel_556350_Angewandte%20Informatik.pdf)

## Überblick

Das FenceMonitor-System besteht aus drei Hauptkomponenten:
- **Sensor**: MicroPython-Code für ESP32-basierte Sensoren zur Zaunspannungsmessung
- **Gateway**: Python-Anwendung für Raspberry Pi mit LoRa-Kommunikation über MQTT
- **Node-RED Flow**: Vollständige Monitoring-Lösung mit InfluxDB-Speicherung und Telegram-Bot

## Hardware-Anforderungen

### Gateway (Raspberry Pi)
- Raspberry Pi (3B+ oder neuer empfohlen)
- **WaveShare SX1262 LoRaWAN Node Module Expansion Board 433MHz**
- SPI-Verbindung zum LoRa-Modul
- Internet-Verbindung für MQTT

### Sensor (ESP32)
- ESP32-Mikrocontroller
- SX1262 LoRa-Modul
- GPS-Modul (NEO-6M)
- Spannungsmessschaltung für Elektrozaun
- Batterie-/Solarpanel-Stromversorgung

## Installation

### Gateway Setup (Raspberry Pi)

1. **Abhängigkeiten installieren**:
```bash
cd Gateway
pip install -r requirements.txt
```

2. **Hardware-Konfiguration anpassen**:
```bash
# Bearbeite config/hardware_config.py für deine SPI-Pins
# Bearbeite config/lora_config.py für LoRa-Parameter
```

3. **Gateway starten**:
```bash
python main.py
```

### Sensor Setup (ESP32)

1. **MicroPython installieren**:
   - MicroPython Firmware auf ESP32 flashen
   - Alle Python-Dateien aus dem `Sensor/`-Ordner übertragen

2. **Hardware-Konfiguration**:
   - `config/hardware_config.py` für deine Pin-Belegung anpassen
   - `config/lora_config.py` für LoRa-Parameter anpassen

3. **Automatischer Start**:
   - Der Sensor startet automatisch durch `boot.py` und `main.py`

### Node-RED und Services Setup

1. **MQTT Broker installieren**:
```bash
sudo apt install mosquitto mosquitto-clients
sudo systemctl enable mosquitto
```

2. **InfluxDB installieren**:
```bash
# InfluxDB 2.0 für Zeitreihendaten
curl -fsSL https://repos.influxdata.com/influxdb.key | sudo apt-key add -
echo "deb https://repos.influxdata.com/debian $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/influxdb.list
sudo apt update && sudo apt install influxdb2
```

3. **Node-RED Flow importieren**:
   - Node-RED starten
   - `node-red-flow.json` importieren
   - Telegram-Bot Token konfigurieren
   - InfluxDB-Verbindung einrichten

## Projektstruktur

```
FenceMonitor/
├── Gateway/                 # Raspberry Pi Gateway-Code
│   ├── LoRaNetworking/     # LoRa-Netzwerkprotokoll-Stack
│   ├── config/             # Hardware- und LoRa-Konfiguration
│   ├── lora/               # SX1262 LoRa-Treiber
│   ├── machine/            # Hardware-Abstraktionsschicht
│   ├── micropython_time.py # Hardware-Abstraktionsschicht
│   ├── micropython.py      # Hardware-Abstraktionsschicht
│   ├── main.py             # Gateway-Hauptprogramm
│   ├── lora_gateway.py     # Gateway-Logik
│   └── requirements.txt    # Python-Abhängigkeiten
├── Sensor/                 # ESP32 Sensor-Code (MicroPython)
│   ├── App/                # Anwendungslogik
│   │   ├── LocationService.py      # GPS-Dienst
│   │   ├── VoltageMeasurement.py   # Spannungsmessung
│   │   └── LightSleepManager.py    # Energieverwaltung
│   ├── GPS/                # GPS-Modul-Treiber
│   ├── LoRaNetworking/     # LoRa-Netzwerkprotokoll
│   ├── config/             # Sensor-Konfiguration
│   ├── lora/               # LoRa-Treiber für ESP32
│   ├── umqtt/              # MQTT über LoRa-Client
│   ├── boot.py             # MicroPython Boot-Skript
│   └── main.py             # Sensor-Hauptprogramm
└── node-red-flow.json      # Node-RED Flow mit vollständiger Monitoring-Lösung
```

## Funktionen

### Kernsystem
- ✅ LoRa-Kommunikation (433 MHz) zwischen Sensor und Gateway
- ✅ Zaunspannungsmessung mit konfigurierbaren Schwellwerten
- ✅ GPS-Lokalisierung der Sensoren
- ✅ MQTT-Integration für Datenweiterleitung
- ✅ Energieeffiziente Sleep-Modi für Batteriebetrieb

### Node-RED Integration
- ✅ **InfluxDB-Speicherung**: Zeitreihendaten für historische Analyse
- ✅ **Telegram-Bot**: Vollständige Benutzerinteraktion
  - `/start` - Bot initialisieren
  - `/overview` - Sensorübersicht anzeigen
  - `/rename` - Sensoren umbenennen
  - `/threshold` - Schwellwerte konfigurieren
  - `/location` - GPS-Standorte anzeigen
- ✅ **Automatische Benachrichtigungen**: Warnungen und Entwarnungen
- ✅ **Multi-User-Support**: Mehrere Telegram-Chats unterstützt
- ✅ **Persistente Konfiguration**: CSV-basierte Sensor-Verwaltung

## Konfiguration

### LoRa-Parameter
Beide Geräte müssen identische LoRa-Parameter verwenden:
- **Frequenz**: 433 MHz
- **Spreading Factor**: 12
- **Bandwidth**: 125 kHz
- **Coding Rate**: 4/5

### MQTT-Topics
- `fence_sensor/measure/voltage` - Spannungs- und Batteriedaten
- `fence_sensor/measure/threshold` - Schwellwertüberschreitungen
- `fence_sensor/update/location/{sensor_id}` - GPS-Updates

### Telegram-Bot Setup
1. Bot bei @BotFather erstellen
2. Bot-Token in Node-RED konfigurieren
3. Chat-ID durch ersten Kontakt mit Bot erhalten

## Verwendung

### Grundbetrieb
1. **Gateway starten**: Überwacht kontinuierlich LoRa-Nachrichten
2. **Sensor-Betrieb**: Misst alle 5 Minuten Zaunspannung und Batterie
3. **Automatische Speicherung**: Daten werden in InfluxDB gespeichert

### Telegram-Bot Interaktion
- **Sensor-Übersicht**: `/overview` zeigt alle aktiven Sensoren
- **Schwellwert setzen**: `/threshold` für individuelle Warngrenzen
- **Sensor umbenennen**: `/rename` für benutzerfreundliche Namen
- **Standorte anzeigen**: `/location` mit GPS-Koordinaten
- **Automatische Warnungen**: Bei Spannungsabfall unter Schwellwert

### Datenvisualisierung
- InfluxDB-Daten können mit Grafana visualisiert werden
- Historische Trends und Muster erkennbar
- Export für weitere Analysen möglich

## Entwicklung

### Tests ausführen
```bash
# Gateway-Tests (falls vorhanden)
cd Gateway
python -m pytest

# Sensor-Tests auf ESP32-Hardware erforderlich
```

### Node-RED Entwicklung
- Flow-Editor für Anpassungen verwenden
- Debug-Nodes für Fehlersuche aktivieren
- Backup des Flows vor Änderungen erstellen

## Troubleshooting

### Häufige Probleme
- **Keine LoRa-Verbindung**: Antennenverbindung und Frequenz prüfen
- **SPI-Fehler**: Pin-Belegung in `hardware_config.py` kontrollieren
- **MQTT-Verbindung**: Broker-Status und Netzwerk überprüfen
- **Telegram-Bot reagiert nicht**: Token und Chat-ID validieren
- **InfluxDB-Fehler**: Datenbankverbindung und -konfiguration prüfen

### Debug-Modi
```bash
# Gateway mit Debug-Ausgabe
python main.py --debug

# MQTT-Messages überwachen
mosquitto_sub -t "fence_sensor/#" -v

# InfluxDB-Verbindung testen
influx auth list
```

## Hardware-Spezifikationen

### WaveShare SX1262 LoRaWAN Board
- **Frequenzbereich**: 410-525 MHz (433 MHz konfiguriert)
- **Interface**: SPI über GPIO-Pins
- **Reichweite**: Bis zu 15 km (Line-of-Sight)
- **Kompatibilität**: Raspberry Pi 3B+/4

### Systemanforderungen
- **Raspberry Pi**: Min. 1GB RAM für Node-RED + InfluxDB
- **SD-Karte**: Min. 32GB für Datenspeicherung
- **Netzwerk**: Ethernet oder WiFi für MQTT/Internet

## Architektur

```
[ESP32 Sensoren] --[LoRa 433MHz]--> [Pi Gateway] --[MQTT]--> [Node-RED]
                                                                  |
                                                             [InfluxDB]
                                                                  |
                                                           [Telegram Bot]
```

## Lizenz

Dieses Projekt ist für Forschungs- und Bildungszwecke entwickelt.

## Support

Bei Fragen oder Problemen:
- Hardware-Konfigurationsdateien überprüfen
- Debug-Ausgaben und Logs konsultieren  
- LoRa-Verbindung zwischen Gateway und Sensor testen
- MQTT- und InfluxDB-Verbindungen validieren

---

*Entwickelt als Teil einer Masterarbeit für IoT-basierte Zaunüberwachung mit LoRa-Kommunikation*