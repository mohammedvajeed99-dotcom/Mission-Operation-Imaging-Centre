"""A drop-in for functools.lru_cache that also closes the cold-cache
stampede: lru_cache does not serialize concurrent misses, so two requests
for the same still-uncached key (e.g. two people opening the same mission
within the same second) both run the expensive function body at once
instead of one computing it while the other waits. That doubles CPU and
peak memory at exactly the moment a small hosted instance is most likely to
run out of RAM.
"""

import threading
from collections import defaultdict
from functools import lru_cache, wraps


def locked_lru_cache(maxsize=8):
    """Like functools.lru_cache, but a second caller for a key that is not
    yet cached blocks until the first caller finishes (and then gets the
    cached result) instead of recomputing it in parallel."""

    def decorator(fn):
        cached = lru_cache(maxsize=maxsize)(fn)
        locks = defaultdict(threading.Lock)
        locks_guard = threading.Lock()

        @wraps(fn)
        def wrapper(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            with locks_guard:
                lock = locks[key]
            with lock:
                return cached(*args, **kwargs)

        wrapper.cache_clear = cached.cache_clear
        wrapper.cache_info = cached.cache_info
        return wrapper

    return decorator
