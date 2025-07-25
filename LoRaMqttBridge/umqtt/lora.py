from LoRaNetworking import LoRaTCP
from umqtt.simple import MQTTException, MQTTClient

# Modifizierte MQTTClient, die LoRaSocket verwendet
class LoRaMQTTClient(MQTTClient):
    def __init__(
            self,
            client_id,
            server,
            keepalive=0,
    ):
        super().__init__(
            client_id=client_id,
            server=server,
            keepalive=keepalive,
            ssl=None,
        )

    def connect(self, clean_session=True, timeout=60):  # Standard-Timeout auf 60 Sekunden gesetzt
        # Anstatt einen TCP-Socket zu erstellen, erstellen wir einen LoRaSocket
        self.sock = LoRaTCP()
        self.sock.settimeout(timeout)

        # Verbindung zum Remote-Server über LoRa simulieren
        self.sock.connect((self.server, self.port))

        # Der Rest ist gleich wie in der ursprünglichen MQTTClient.connect-Methode
        # Ab hier wird das MQTT-Protokoll über den LoRaSocket abgewickelt
        premsg = bytearray(b"\x10\0\0\0\0\0")
        msg = bytearray(b"\x04MQTT\x04\x02\0\0")

        sz = 10 + 2 + len(self.client_id)
        msg[6] = clean_session << 1
        if self.user:
            sz += 2 + len(self.user) + 2 + len(self.pswd)
            msg[6] |= 0xC0
        if self.keepalive:
            assert self.keepalive < 65536
            msg[7] |= self.keepalive >> 8
            msg[8] |= self.keepalive & 0x00FF
        if self.lw_topic:
            sz += 2 + len(self.lw_topic) + 2 + len(self.lw_msg)
            msg[6] |= 0x4 | (self.lw_qos & 0x1) << 3 | (self.lw_qos & 0x2) << 3
            msg[6] |= self.lw_retain << 5

        i = 1
        while sz > 0x7F:
            premsg[i] = (sz & 0x7F) | 0x80
            sz >>= 7
            i += 1
        premsg[i] = sz

        self.sock.write(premsg, i + 2)
        self.sock.write(msg)
        # print(hex(len(msg)), hexlify(msg, ":"))
        self._send_str(self.client_id)
        if self.lw_topic:
            self._send_str(self.lw_topic)
            self._send_str(self.lw_msg)
        if self.user:
            self._send_str(self.user)
            self._send_str(self.pswd)
        try:
            resp = self.sock.read(4)
            if not resp:
                raise MQTTException("Keine Antwort vom Server erhalten")
            if len(resp) < 4:
                raise MQTTException(f"Unvollständige Antwort erhalten: {resp.hex()}")

            # Jetzt können wir sicher auf die Indizes zugreifen
            assert resp[0] == 0x20 and resp[1] == 0x02, f"Unerwartetes Antwortformat: {resp.hex()}"
            if resp[3] != 0:
                raise MQTTException(resp[3])
            return resp[2] & 1
        except OSError as e:
            raise MQTTException(f"Socket-Fehler: {e}")