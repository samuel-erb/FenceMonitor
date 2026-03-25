# LoRaTCP Stack

Ein TCP-ähnlicher Protokoll-Stack implementiert über LoRa für zuverlässige Kommunikation zwischen IoT-Sensoren und Gateway.

## Überblick

Der LoRaTCP Stack implementiert ein vollständiges TCP-ähnliches Protokoll über LoRa-Funktechnik. Er ermöglicht zuverlässige, verbindungsorientierte Kommunikation zwischen Sensoren und einer Basisstation/Gateway mit Unterstützung für Verbindungsaufbau, Datenübertragung, Flusskontrolle und ordnungsgemäßem Verbindungsabbau.

## Architektur und Schichtenmodell

Der Stack besteht aus mehreren Schichten, die jeweils spezifische Funktionen übernehmen:

```
┌─────────────────────────────────┐
│        Anwendungsschicht        │  ← App Layer (main.py, boot.py)
├─────────────────────────────────┤
│         LoRaTCP (TCP)           │  ← Transport Layer
├─────────────────────────────────┤
│       LoRaDataLink (L2)         │  ← Data Link Layer
├─────────────────────────────────┤
│      SX1262 LoRa Modem          │  ← Physical Layer
└─────────────────────────────────┘
```

### 1. LoRaTCP (Transport Layer) - `LoRaTCP.py`

**Hauptfunktion**: Implementiert das TCP-Protokoll mit zuverlässiger, verbindungsorientierter Datenübertragung.

**Datenaustausch nach unten** (zu LoRaDataLink):
- Sendet TCP-Segmente als serialisierte Bytes über `self._data_link.add_to_send_queue(segment_bytes)`
- Empfängt LoRa-Dataframes über Callback `add_lora_dataframe_to_queue(lora_dataframe)`

**Datenaustausch nach oben** (zur Anwendung):
- Socket-API-kompatible Methoden: `read()`, `write()`, `send()`, `connect()`, `listen()`, `close()`
- Blocking/Non-blocking Modi über `settimeout()`, `setblocking()`
- Standard-Socket-Verhalten für nahtlose Integration

**TCP-Features**:
- **Zustandsmaschine**: Vollständige RFC 793 Implementation (CLOSED, LISTEN, SYN_SENT, ESTABLISHED, etc.)
- **Zuverlässigkeit**: Sequenznummern, ACKs, Retransmission mit exponential backoff
- **Verbindungsaufbau**: 3-Way Handshake (SYN → SYN-ACK → ACK)
- **Verbindungsabbau**: 4-Way Handshake mit FIN/ACK
- **Flusskontrolle**: Receive/Send Windows zur Überlastungsvermeidung
- **Segmentierung**: Automatische Aufteilung großer Daten in übertragbare Segmente

### 2. LoRaTCPSegment - `LoRaTCPSegment.py`

**Hauptfunktion**: Definition und Serialisierung der TCP-Segment-Struktur.

**Segment-Format**:
```
┌──────────────┬─────────────┬─────────────┬─────────────┐
│  Socket_ID   │    Flags    │  Seq_Num    │  ACK_Num    │
│   (4 bit)    │  (4 bit)    │  (16 bit)   │  (16 bit)   │
├──────────────┴─────────────┴─────────────┴─────────────┤
│                   Payload (0-243 bytes)                │
└────────────────────────────────────────────────────────┘
```

**Flags**: SYN, ACK, FIN, RST für Protokollsteuerung
**Sequenznummern**: 16-bit mit Wraparound-Arithmetik (Seq-Klasse)

### 3. TCB (Transmission Control Block) - `TCB.py`

**Hauptfunktion**: Speichert den Zustand einer TCP-Verbindung.

**Wichtige Zustandsvariablen**:
- **Sequenznummern**: `snd_una`, `snd_nxt`, `rcv_nxt`, `iss`, `irs`
- **Puffer**: `send_buffer`, `receive_buffer`, `reassembled_data`
- **Warteschlangen**: `retransmission_queue` für unbestätigte Segmente
- **Timer**: Retransmission, Time-Wait, Close-Wait Timer
- **Fenster**: `snd_wnd`, `rcv_wnd` für Flusskontrolle

### 4. LoRaDataLink (Data Link Layer) - `LoRaDataLink.py`

**Hauptfunktion**: Abstraktion der LoRa-Hardware und Frame-Management.

**Datenaustausch nach oben** (zu LoRaTCP):
- Empfängt TCP-Segmente über `add_to_send_queue(data: bytes)`
- Liefert empfangene Frames über `socket.add_lora_dataframe_to_queue(lora_dataframe)`

**Datenaustausch nach unten** (zu LoRa Hardware):
- Verwendet SX1262 Driver für `send()` und `start_recv()`
- Kontinuierlicher Empfang mit Poll-basierter Verarbeitung

**Frame-Format (LoRaDataFrame)**:
```
┌─────────────────┬─────────────┬─────────────────────────┐
│  Sensor_Address │    Type     │       Payload           │
│    (6 bytes)    │  (1 byte)   │    (max 249 bytes)      │
└─────────────────┴─────────────┴─────────────────────────┘
```

**Erweiterte Features**:
- **Duty Cycle Management**: 1%/10% Duty Cycle Einhaltung je nach Frequenzband
- **Channel Activity Detection (CAD)**: Kollisionsvermeidung vor Sendung
- **Sensor State Management**: Tracking aktiver/inaktiver Sensoren (Gateway-Mode)
- **Adressierung**: 6-Byte eindeutige Sensor-Adressen
- **Frame-Typen**: `LoRaTCP_Segment`, `LoRaDataLink_Woke_Up`

### 5. LoRaNetworking (Management Layer) - `LoRaNetworking.py`

**Hauptfunktion**: Thread-Management und Koordination der Schichten.

**Threading**:
- Startet separaten Networking-Thread für `LoRaTCP.run()` und `LoRaDataLink.run()`
- Kontinuierliche Verarbeitung aller aktiven TCP-Verbindungen
- Graceful Shutdown mit Verbindungsabbau

## Datenflussbeschreibung

### Senden (Application → LoRa)

1. **Anwendung** ruft `socket.write(data)` auf
2. **LoRaTCP** puffert Daten in `send_buffer`, segmentiert bei `run()`
3. **TCP-Segment** wird erstellt mit Seq/ACK-Nummern und Flags
4. **Serialisierung** zu Bytes und Übergabe an `_data_link.add_to_send_queue()`
5. **LoRaDataFrame** wird erstellt mit Sensor-Adresse und TCP-Payload
6. **CAD** prüft Kanal, **SX1262** sendet Frame über LoRa

### Empfangen (LoRa → Application)

1. **SX1262** empfängt LoRa-Frame kontinuierlich
2. **LoRaDataFrame** wird deserialisiert und validiert
3. **Socket-Routing** basierend auf Socket-ID im TCP-Header
4. **TCP-Zustandsmaschine** verarbeitet Segment (ACK-Handling, State-Transitions)
5. **Datenreassemblierung** in `receive_buffer` → `reassembled_data`
6. **Anwendung** liest Daten über `socket.read()`

## Energieeffizienz-Features

### Power Management
- **Sensor Sleep**: Automatisches Schlafen bei Duty Cycle Überschreitung
- **Wake-up Protokoll**: Sensor signalisiert Erwachen mit speziellem Frame
- **Timer Pause**: TCP-Timer pausieren während Sensor-Inaktivität

### LoRa-Optimierungen
- **Kontinuierlicher Empfang**: Minimiert Setup-Overhead
- **CAD**: Reduziert Kollisionen und Re-transmissions
- **Payload-Optimierung**: Maximale Nutzung des 256-Byte LoRa-Frames

## Weitere Features
- **Gleicher Code**: Der Code des Protokoll-Stapels kann auf dem Gateway und dem Sensor verwendet werden.
- **Vermittlung**: Gateway verwaltet die IP-Sessions. Der Sensor MUSS die Verbindung aufbauen (sock.connect) und das Gateway MUSS lauschen (sock.listen).

## Beispiel-Verwendung

```python
# Sensor (Client)
from LoRaNetworking import LoRaNetworking
from LoRaNetworking.LoRaTCP import LoRaTCP

networking = LoRaNetworking()
sock = LoRaTCP()
sock.connect(("192.168.1.1", 8080))
sock.write(b"Hello Gateway")
response = sock.read(100)
sock.close()

# Gateway (Server)
sock = LoRaTCP()
sock.listen()  # Wartet auf eingehende Verbindungen
peer = sock.getpeername()
logger.info(f"New LoRa connection from Sensor: {peer}") # Beispiel Ausgabe: "New LoRa connection from Sensor: ('192.168.1.1', 8080)"
data = sock.read(100)
sock.write(b"Hello Sensor")
sock.close()
```

## Technische Spezifikationen

- **LoRa-Modulation**: SX1262 LoRa Transceiver
- **Frequenzbänder**: 434 MHz (10% DC) / 868 MHz (1% DC)
- **Max. Frame-Size**: 256 Bytes
- **Max. TCP-Payload**: 243 Bytes pro Segment
- **Sequenznummern**: 16-bit mit Wraparound
- **Retransmission**: 3.5s Timeout, max. 25 Versuche
- **Time-Wait**: 30s für ordnungsgemäße Verbindungsbeendigung

# Known issues
- Verbindungsabbau zwischen Sensor und Basisstation funktioniert nicht 100% zuverlässig

# Ausblick
- **Überprüfung der Änderungen aus RFC 9293**: Das vorliegende Protokoll zunächst überprüfen und die Änderungen aus RFC 9293 einpflegen. 
- **Untersuchung und Implementierung**: Nagle Algorithmus vs. Delayed ACKs – Viele kleine Segmente erzeugen großen Overhead. Es muss eine Entscheidung getroffen werden, um diesem Problem entgegenzuwirken.
- **LoRaUDP**: Kommunikation über LoRa-Datagramme. Das LoRaDataFrame Feld "Type" bietet ausreichend Platz für Erweiterungen. Volle Kompatibilität mit der MicroPython Socket-API muss sichergestellt werden. 

Der LoRaTCP Stack kombiniert die Zuverlässigkeit von TCP mit der Energieeffizienz und Reichweite von LoRa, ideal für batteriebetriebene IoT-Sensornetzwerke mit gelegentlicher Datenübertragung.