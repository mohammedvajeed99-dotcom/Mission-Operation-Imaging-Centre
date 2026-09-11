"""Live image-generation progress: what is happening right now, in this process.

Distinct from core.image_center.ProductRegistry (on disk, "what has already
been generated"): this is in-memory only and answers "how far along is the
generation that is in flight right now, and roughly how much longer will it
take" -- which the dashboard polls while a Generate button or batch is
running, so an operator watching a 2048 px request is never staring at a
bare spinner with no sense of whether it is stuck or seconds from done.

Keyed by mission_id rather than a single global slot: /generate is
deliberately sequential *within* a mission (see api_image_center.py and the
batch runner in src/imageCenter.jsx), but nothing stops two different
missions being generated from two browser tabs at once.

Duration history is kept per delivered pixel size (512/1024/2048 -- the
UI's own resolution tiers) so the estimate shown is this deployment's own
measured network performance, not a guess baked into the code. The seed
values below are only the very first estimate this process ever shows, for
a size that has not completed once yet; every completed generation replaces
them with a real running average, self-calibrating to this environment
(local machine, or a hosted deployment with its own network path to the
Sentinel-2 archive) rather than assuming any fixed number carries over.
"""

import threading
import time

_lock = threading.Lock()

_active = {}  # mission_id -> in-flight generation state

# Seed-only estimates (seconds), measured against the real Sentinel-2 STAC
# archive during development, before this process has completed a single
# generation of its own at that size. Replaced immediately once real timings
# exist -- see estimate_seconds().
_SEED_AVG_SECONDS = {512: 50.0, 1024: 70.0, 2048: 95.0}

_stats = {px: {"count": 0, "totalSec": 0.0} for px in _SEED_AVG_SECONDS}


def estimate_seconds(max_pixels):
    """Best current estimate for a generation at this delivered size."""
    with _lock:
        s = _stats.get(max_pixels)
        if s and s["count"] > 0:
            return s["totalSec"] / s["count"]
    nearest = min(_SEED_AVG_SECONDS, key=lambda k: abs(k - max_pixels))
    return _SEED_AVG_SECONDS[nearest]


def record_duration(max_pixels, seconds):
    with _lock:
        s = _stats.setdefault(max_pixels, {"count": 0, "totalSec": 0.0})
        s["count"] += 1
        s["totalSec"] += float(seconds)


def start(mission_id, image_id, max_pixels):
    # estimate_seconds() takes _lock itself -- must be computed before
    # entering the block below, not inside it: threading.Lock is not
    # reentrant, so calling it while _lock is already held here would
    # deadlock this thread against itself on every single generation.
    estimate = estimate_seconds(max_pixels)
    with _lock:
        _active[mission_id] = {
            "imageId": image_id,
            "maxPixels": int(max_pixels),
            "stage": "starting",
            "detail": None,
            "startedAt": time.time(),
            "estimateSeconds": estimate,
        }


def update(mission_id, stage, detail=None):
    with _lock:
        entry = _active.get(mission_id)
        if entry is not None:
            entry["stage"] = stage
            entry["detail"] = detail


def progress_callback(mission_id):
    """A (stage, detail) -> None callable bound to one mission, for passing
    into generate_product without every caller touching this module."""
    return lambda stage, detail=None: update(mission_id, stage, detail)


def finish(mission_id, record=True):
    """Clear the in-flight entry for `mission_id`. If `record`, folds its
    elapsed time into that size's running average before clearing."""
    with _lock:
        entry = _active.pop(mission_id, None)
    if entry is not None and record:
        record_duration(entry["maxPixels"], time.time() - entry["startedAt"])
    return entry


def snapshot(mission_id):
    """Current progress for `mission_id`, or {"active": False} if idle."""
    with _lock:
        entry = _active.get(mission_id)
        if entry is None:
            return {"active": False}
        entry = dict(entry)  # copy out before releasing the lock
    elapsed = time.time() - entry["startedAt"]
    est = entry["estimateSeconds"]
    remaining = max(est - elapsed, 0.0) if est else None
    return {
        "active": True,
        "imageId": entry["imageId"],
        "maxPixels": entry["maxPixels"],
        "stage": entry["stage"],
        "detail": entry["detail"],
        "elapsedSeconds": round(elapsed, 1),
        "estimateSeconds": round(est, 1) if est else None,
        "estimateRemainingSeconds": round(remaining, 1) if remaining is not None else None,
    }
