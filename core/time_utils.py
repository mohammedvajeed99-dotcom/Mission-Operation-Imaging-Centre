"""Every timestamp this app produces (state/contact/eclipse reports, image
capture epochs, generated-report times) originates from GMAT's own
UTCGregorian report format -- it is always a UTC wall-clock value, even
though it frequently arrives here as a timezone-naive datetime/Timestamp
(state_parser/contact_parser/eclipse_parser attach no tzinfo when parsing
the raw text, and a naive value stays naive after a round-trip through the
processed/*.xlsx cache files, since the xlsx format itself has no timezone
concept to preserve).

`datetime.isoformat()` on a naive value omits any UTC designator (no "Z",
no "+00:00"), which is the actual bug this module exists to close: per the
ECMAScript date-time string spec, a JavaScript `new Date(...)` parses a
date-time string with NO offset as *local time in the browser's own
timezone*, not UTC -- so every such string silently mis-parses everywhere
except a browser whose own clock happens to be set to UTC+0. Use
`utc_iso()` at every point a timestamp is serialized to JSON so the string
that reaches the frontend is always explicit, and `new Date(...)` there
always resolves to the true UTC instant regardless of the viewer's own
timezone.
"""

from datetime import timezone


def utc_iso(dt):
    """ISO 8601 string for `dt` with an explicit UTC offset, treating a
    naive value as already being UTC (never as "unknown" or "local") --
    consistent with where every timestamp in this app actually comes from.
    Returns None for None, matching the ergonomics of `dt.isoformat()`
    guarded by an `is not None` check at most existing call sites.
    """
    if dt is None:
        return None
    if getattr(dt, "tzinfo", None) is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()
