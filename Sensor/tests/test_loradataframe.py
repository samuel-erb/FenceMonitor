from LoRaNetworking.LoRaDataLink import LoRaDataFrame, LoRaTCP_Data, DataFrameMaxPayloadLength

def test_loradataframe_valid_construction():
    addr = b'\x01\x02\x03\x04\x05\x06'
    payload = b'Hello'
    frame = LoRaDataFrame(addr, LoRaTCP_Data, payload)
    assert frame.address == addr
    assert frame.data_type == LoRaTCP_Data
    assert frame.payload == payload

def test_loradataframe_invalid_address():
    try:
        LoRaDataFrame(b'\x01\x02\x03', LoRaTCP_Data, b'')
        assert False, "Expected ValueError for invalid address length"
    except ValueError:
        pass

def test_loradataframe_invalid_data_type():
    try:
        LoRaDataFrame(b'\x01\x02\x03\x04\x05\x06', 0x99, b'')
        assert False, "Expected ValueError for invalid data type"
    except ValueError:
        pass

def test_loradataframe_payload_too_large():
    try:
        LoRaDataFrame(b'\x01\x02\x03\x04\x05\x06', LoRaTCP_Data, b'A'*(DataFrameMaxPayloadLength+1))
        assert False, "Expected ValueError for payload too large"
    except ValueError:
        pass

def test_loradataframe_to_bytes_and_from_bytes():
    addr = b'\xAA\xBB\xCC\xDD\xEE\xFF'
    payload = b'PAYLOAD'
    frame = LoRaDataFrame(addr, LoRaTCP_Data, payload)
    data_bytes = frame.to_bytes()
    parsed = LoRaDataFrame.from_bytes(data_bytes)
    assert parsed.address == addr
    assert parsed.data_type == LoRaTCP_Data
    assert parsed.payload == payload

def test_loradataframe_repr():
    frame = LoRaDataFrame(b'\x01\x02\x03\x04\x05\x06', LoRaTCP_Data, b'data')
    s = repr(frame)
    assert 'LoRaDataFrame' in s
    assert 'LoRaTCP_Data' in s
