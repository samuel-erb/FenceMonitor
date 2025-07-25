from __future__ import annotations
from typing import Union

# Type aliases für Buffer
AnyReadableBuf = Union[bytes, bytearray, memoryview]
AnyWritableBuf = Union[bytearray, memoryview]

from .pin import *
# Alias für PinLike
PinLike = Pin  # Normalerweise Pin-Objekt
from .spi import *
import micropython_time as time

def idle():
    time.sleep(0.01)

def unique_id():
    return 0xFF