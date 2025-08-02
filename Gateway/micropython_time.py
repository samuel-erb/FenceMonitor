"""
MicroPython time module compatibility layer for standard Python
Maps MicroPython time functions to standard Python equivalents
"""

import time as _standard_time
import math

# Re-export all standard time module contents
from time import *

# MicroPython specific functions that need implementation or mapping

def ticks_ms():
    """
    Returns an increasing millisecond counter with an arbitrary reference point.
    Works like MicroPython's ticks_ms()
    """
    return int(_standard_time.time() * 1000) & 0x7FFFFFFF

def ticks_us():
    """
    Returns an increasing microsecond counter with an arbitrary reference point.
    Works like MicroPython's ticks_us()
    """
    return int(_standard_time.time() * 1000000) & 0x7FFFFFFF

def ticks_cpu():
    """
    Returns an increasing counter of CPU cycles.
    Approximated using perf_counter_ns() in standard Python
    """
    return int(_standard_time.perf_counter_ns()) & 0x7FFFFFFF

def ticks_add(ticks, delta):
    """
    Add a delta to a ticks value, handling overflow.
    Works like MicroPython's ticks_add()
    """
    return (ticks + delta) & 0x7FFFFFFF

def ticks_diff(ticks1, ticks2):
    """
    Compute the difference between two ticks values.
    Works like MicroPython's ticks_diff()
    """
    diff = (ticks1 - ticks2) & 0x7FFFFFFF
    if diff > 0x3FFFFFFF:
        diff -= 0x80000000
    return diff

def sleep_ms(ms):
    """
    Sleep for given number of milliseconds.
    Works like MicroPython's sleep_ms()
    """
    _standard_time.sleep(ms / 1000.0)

def sleep_us(us):
    """
    Sleep for given number of microseconds.
    Works like MicroPython's sleep_us()
    """
    _standard_time.sleep(us / 1000000.0)

# MicroPython's time_ns is called ticks_ns in some versions
def ticks_ns():
    """
    Returns current time in nanoseconds.
    Maps to standard Python's time_ns()
    """
    return _standard_time.time_ns()

# MicroPython may have these constants with different names
def time_pulse_us(pin, pulse_level, timeout_us=1000000):
    """
    Time a pulse on a pin (not directly available in standard Python).
    This is a stub implementation.
    """
    raise NotImplementedError("time_pulse_us is hardware-specific and not available in standard Python")

# Ensure all standard time constants are available
# These are usually present in both MicroPython and standard Python
CLOCK_MONOTONIC = getattr(_standard_time, 'CLOCK_MONOTONIC', 1)
CLOCK_REALTIME = getattr(_standard_time, 'CLOCK_REALTIME', 0)

# MicroPython may have different epoch
# Standard Python uses 1970-01-01, MicroPython might use 2000-01-01
# This constant can be used to convert between epochs if needed
MICROPY_EPOCH_OFFSET = 946684800  # Seconds between 1970-01-01 and 2000-01-01

def micropython_time():
    """
    Get time in MicroPython format (seconds since 2000-01-01)
    Some MicroPython ports use this epoch instead of Unix epoch
    """
    return _standard_time.time() - MICROPY_EPOCH_OFFSET

# Alias for common MicroPython usage patterns
localtime = _standard_time.localtime
gmtime = _standard_time.gmtime
mktime = _standard_time.mktime
sleep = _standard_time.sleep
time = _standard_time.time

# For debugging and compatibility checking
def is_micropython():
    """
    Returns False as this is the compatibility layer for standard Python
    """
    return False

__all__ = [
    # Standard time module exports
    'asctime', 'ctime', 'gmtime', 'localtime', 'mktime', 'sleep',
    'strftime', 'strptime', 'time', 'time_ns', 'struct_time',
    'timezone', 'altzone', 'daylight', 'tzname',
    'CLOCK_MONOTONIC', 'CLOCK_REALTIME', 'monotonic', 'perf_counter',
    'process_time', 'thread_time',
    # MicroPython specific
    'ticks_ms', 'ticks_us', 'ticks_cpu', 'ticks_add', 'ticks_diff',
    'sleep_ms', 'sleep_us', 'ticks_ns', 'micropython_time',
    'is_micropython', 'MICROPY_EPOCH_OFFSET'
]