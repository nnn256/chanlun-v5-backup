"""Bounded immutable snapshots for already-computed stock result presentation."""
from collections import OrderedDict
import json
import threading

# Store encoded bytes so the budget reflects retained payloads and callers
# cannot trim periods or add export evidence to another request's result.
MAX_CACHE_BYTES = 24 * 1024 * 1024
MAX_ENTRY_BYTES = 8 * 1024 * 1024
MAX_ENTRIES = 12
CACHE = OrderedDict()
CACHE_BYTES = 0
FLIGHTS = {}
LOCK = threading.RLock()


class _Flight:
    def __init__(self):
        self.ready = threading.Event()
        self.raw = None
        self.error = None


def get_or_build(key, build, retain=None):
    """Return an isolated object, coalescing concurrent builds of one identity."""
    global CACHE_BYTES
    with LOCK:
        raw = CACHE.get(key)
        if raw is not None:
            CACHE.move_to_end(key)
            flight = None
            owner = False
        else:
            flight = FLIGHTS.get(key)
            owner = flight is None
            if owner:
                flight = _Flight()
                FLIGHTS[key] = flight
    # Large JSON decoding must not hold the shared cache lock and block an
    # unrelated stock's lookup or completion. Encoded bytes are immutable.
    if raw is not None:
        return json.loads(raw)
    if not owner:
        flight.ready.wait()
        if flight.error is not None:
            raise flight.error
        return json.loads(flight.raw)
    try:
        value = build()
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False,
                         separators=(',', ':')).encode('utf-8')
        with LOCK:
            flight.raw = raw
            if len(raw) <= min(MAX_ENTRY_BYTES, MAX_CACHE_BYTES) and (retain is None or retain()):
                CACHE[key] = raw
                CACHE_BYTES += len(raw)
                while CACHE_BYTES > MAX_CACHE_BYTES or len(CACHE) > MAX_ENTRIES:
                    _, removed = CACHE.popitem(last=False)
                    CACHE_BYTES -= len(removed)
        return value
    except BaseException as exc:
        flight.error = exc
        raise
    finally:
        with LOCK:
            FLIGHTS.pop(key, None)
            flight.ready.set()
