from LoRaNetworking.LoRaDataLink import LoRaDataLink, LoRaTCP_Data, LoRaTCP_Establish, LoRaTCP_Finalize

class DummyDriver:
    def __init__(self):
        self.sent_packets = []

    async def send(self, packet):
        self.sent_packets.append(packet)

    async def recv(self, timeout_ms):
        return None

async def test_loradatalink_send_queues():
    link = LoRaDataLink()
    link._driver = DummyDriver()  # override echten Driver

    # Test send_data
    link.send_data(b'foo')
    f = link._transmitQueue.pop_sync()
    assert f.data_type == LoRaTCP_Data
    assert f.payload == b'foo'

    # Test send_establish
    link.send_establish(b'bar')
    f = link._transmitQueue.pop_sync()
    assert f.data_type == LoRaTCP_Establish
    assert f.payload == b'bar'

    # Test send_finalize
    link.send_finalize(b'baz')
    f = link._transmitQueue.pop_sync()
    assert f.data_type == LoRaTCP_Finalize
    assert f.payload == b'baz'

async def test_loradatalink_receive():
    link = LoRaDataLink()
    # Simuliere Empfangsqueue
    frame = b'frame'
    link._receiveQueue.put_sync(frame)
    popped = link.receive()
    assert popped == frame

async def test_loradatalink_sleep_ready():
    link = LoRaDataLink()
    assert link.is_sleep_ready() == True
    link._transmitQueue.put_sync(b'123')
    assert link.is_sleep_ready() == False

async def test_loradatalink_woke_up_sends():
    link = LoRaDataLink()
    link._driver = DummyDriver()
    link._sender_task = type('DummyTask', (), {'cancel': lambda self: None})()
    await link.woke_up()
    assert len(link._driver.sent_packets) > 0
    assert link._driver.sent_packets[0].data_type == 0x00  # LoRaDataLink_Woke_Up

def test_loradatalink_start_starts_tasks():
    link = LoRaDataLink()
    link.start()
    assert link._receiver_task is not None
    assert link._sender_task is not None
