"""Small resource guards shared by the public portal and localhost UI."""
import collections
import threading
import time
from http.server import ThreadingHTTPServer


class SlidingWindowLimiter:
    """In-process per-client rate limiter with bounded bookkeeping."""
    def __init__(self, window_seconds=60, max_clients=10000):
        self.window = max(1, int(window_seconds))
        self.max_clients = max(100, int(max_clients))
        self._events = {}
        self._lock = threading.Lock()

    def allow(self, key, limit):
        now = time.monotonic()
        cutoff = now - self.window
        with self._lock:
            events = self._events.setdefault(key, collections.deque())
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                return False
            events.append(now)
            if len(self._events) > self.max_clients:
                stale = [k for k, q in self._events.items() if not q or q[-1] <= cutoff]
                for old in stale:
                    self._events.pop(old, None)
                    if len(self._events) <= self.max_clients:
                        break
                # A flood of fresh spoofed identities must not make bookkeeping unbounded. Evict
                # the least recently active keys if no stale window is available yet.
                if len(self._events) > self.max_clients:
                    oldest = [old for old in sorted(
                        self._events, key=lambda k: self._events[k][-1]) if old != key]
                    for old in oldest[:len(self._events) - self.max_clients]:
                        self._events.pop(old, None)
            return True


class BoundedThreadingHTTPServer(ThreadingHTTPServer):
    """Threading server with a hard worker cap and per-connection read timeout."""
    daemon_threads = True
    request_queue_size = 64

    def __init__(self, address, handler, max_workers=32, socket_timeout=30):
        self._worker_slots = threading.BoundedSemaphore(max(1, int(max_workers)))
        self._socket_timeout = max(1, int(socket_timeout))
        super().__init__(address, handler)

    def get_request(self):
        request, address = super().get_request()
        request.settimeout(self._socket_timeout)
        return request, address

    def process_request(self, request, client_address):
        if not self._worker_slots.acquire(False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._worker_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._worker_slots.release()
