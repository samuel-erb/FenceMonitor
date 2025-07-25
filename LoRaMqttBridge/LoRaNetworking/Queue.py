import _thread

import gc
import  asyncio
from collections import deque


class Queue:
    __slots__ = ('queue', 'thread_lock', 'async_lock', 'maxsize')
    def __init__(self, maxsize=100):
        self.queue = deque((), maxsize)
        self.thread_lock = _thread.allocate_lock()  # Für Datenstrukturen
        self.async_lock = asyncio.Lock()  # Für komplexe async Ops
        self.maxsize = maxsize

    def put_sync_left(self, item):
        self.queue.appendleft(item)

    def put_sync(self, item):
        """Schneller sync Zugriff"""
        with self.thread_lock:
            if len(self.queue) >= self.maxsize:
                self.queue.popleft()
                gc.collect()
                print("[Queue] Warning maximum size reached. Removed oldest item")
            self.queue.append(item)

    async def put_async(self, item):
        """Schneller async Zugriff"""
        with self.thread_lock:
            if len(self.queue) >= self.maxsize:
                self.queue.popleft()
                gc.collect()
                print("[Queue] Warning maximum size reached. Removed oldest item")
            self.queue.append(item)

    def pop_sync(self):
        if len(self.queue) == 0:
            return None
        with self.thread_lock:
            return self.queue.popleft()

    async def pop_async(self):
        if len(self.queue) == 0:
            return None
        with self.thread_lock:
            return self.queue.popleft()

    def __len__(self):
        return len(self.queue)
