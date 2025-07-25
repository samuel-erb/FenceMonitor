import time
import uasyncio as asyncio
from micropython import const

from LoRaNetworking import LoRaDataFrame, LoRaDataLink, LoRaTCP_Data, DATAFRAME_TYPE

_DEBUG = const(True)

def assert_equal(a, b, msg=""):
    if a != b:
        raise AssertionError(f"ASSERT FAILED: {a} != {b} {msg}")

def assert_true(cond, msg=""):
    if not cond:
        raise AssertionError(f"ASSERT FAILED: {msg}")

def test_lora_dataframe():
    print("\n[TEST] LoRaDataFrame basic tests")

    addr = b"\x01\x02\x03\x04\x05\x06"
    payload = b"hello"

    # Normal
    frame = LoRaDataFrame(addr, LoRaTCP_Data, payload)
    assert_equal(frame.address, addr)
    assert_equal(frame.payload, payload)
    assert_equal(frame.data_type, LoRaTCP_Data)

    # Too short address
    try:
        LoRaDataFrame(b"\x01\x02", LoRaTCP_Data, payload)
        raise AssertionError("Expected ValueError for short address")
    except ValueError:
        pass

    # Invalid type
    try:
        LoRaDataFrame(addr, 0xFF, payload)
        raise AssertionError("Expected ValueError for invalid data_type")
    except ValueError:
        pass

    # Too large payload
    try:
        LoRaDataFrame(addr, LoRaTCP_Data, b"x" * 300)
        raise AssertionError("Expected ValueError for large payload")
    except ValueError:
        pass

    # Round-trip serialize / deserialize
    bytes_data = frame.to_bytes()
    parsed_frame = LoRaDataFrame.from_bytes(bytes_data)
    assert_equal(parsed_frame.address, addr)
    assert_equal(parsed_frame.payload, payload)
    assert_equal(parsed_frame.data_type, LoRaTCP_Data)

    # Invalid deserialization
    try:
        LoRaDataFrame.from_bytes(b"\x00\x01")  # too short
        raise AssertionError("Expected ValueError for too short frame")
    except ValueError:
        pass

    try:
        LoRaDataFrame.from_bytes(addr + b"\xFF" + payload)  # invalid type
        raise AssertionError("Expected ValueError for unknown type")
    except ValueError:
        pass

    print("[OK] LoRaDataFrame tests passed")

async def test_lora_datalink():
    print("\n[TEST] LoRaDataLink queue + send/receive simulation")

    link = LoRaDataLink()

    # Check empty queues
    assert_true(link.is_sleep_ready(), "queues should be initially empty")

    # Enqueue data to send
    link.send_data(b"sensor-data-123")
    assert_true(len(link._transmitQueue) == 1, "transmit queue should have 1 item")

    # Simulate sending task by popping
    frame = link._transmitQueue.pop_sync()
    assert_equal(frame.payload, b"sensor-data-123")

    # Add to receive queue
    link._receiveQueue.put_sync(frame)
    received_frame = link.receive()
    assert_equal(received_frame.payload, b"sensor-data-123")

    # Check sleep readiness again
    assert_true(link.is_sleep_ready(), "queues should be empty after pop")

    print("[OK] LoRaDataLink basic send/receive queue test passed")

    # Now start asyncio tasks for receiver/sender (it uses dummy CAD & simulated waits)
    print("[INFO] Starting asyncio tasks for 2 seconds...")
    link.start()
    await asyncio.sleep(2)
    link._running = False  # to break loops
    await asyncio.sleep(0.5)

    print("[OK] LoRaDataLink async start/stop simulation complete")

def run_all_tests():
    test_lora_dataframe()
    asyncio.run(test_lora_datalink())

run_all_tests()