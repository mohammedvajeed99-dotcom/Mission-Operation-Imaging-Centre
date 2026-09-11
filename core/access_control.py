"""Per-section access control for the mission dashboard.

Every navigable dashboard section is protected by its own access code, issued
by the project owner. Enforcement is server-side: the data belonging to a
locked section is stripped from the API response before it is sent, so a
locked section cannot be reached by bypassing the UI and calling the API
directly.

Design notes:

  * The SECTIONS registry below is the single source of truth for what data
    each section needs. It was built from an audit of what each React view
    actually dereferences -- if a view starts reading a new payload key, its
    entry here must be updated or that section will render with missing data.

  * Codes live in config/access_codes.json (generated on first run, owner
    editable). The HMAC signing secret lives in config/.access_secret. Both
    are git-ignored so codes never reach the repository.

  * Tokens are signed with HMAC-SHA256 using stdlib only -- no new
    dependencies. A token carries the set of sections the holder has
    unlocked plus an expiry, and is verified on every request.
"""

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from pathlib import Path

from core.missions import DEFAULT_MISSION, MISSIONS

BASE = Path(__file__).resolve().parent.parent
CODES_PATH = BASE / "config" / "access_codes.json"
SECRET_PATH = BASE / "config" / ".access_secret"

DEFAULT_SESSION_HOURS = 12

# Missions that need no code to switch into. All four of the project's real,
# in-scope missions (asc074_6x8 -- the default a first-time visitor lands on
# -- asc074_3x1, asc080_1x3, asc080_6x4) are public: switching mission never
# needs a code, only the per-section codes below gate the actual data. A
# mission added later would still need its own code, the same way a locked
# section needs its own code to open, unless also added here.
PUBLIC_MISSIONS = {DEFAULT_MISSION, "asc074_3x1", "asc080_1x3", "asc080_6x4"} & set(MISSIONS)
NON_DEFAULT_MISSIONS = sorted(mid for mid in MISSIONS if mid not in PUBLIC_MISSIONS)

# Chrome-level keys always returned regardless of unlocked sections, so the
# application shell (header/title) can render and identify itself. Contains
# mission name/type/AOI/epoch only -- no analytics, coverage or telemetry.
ALWAYS_KEYS = {"mission"}


def _section(label, group, keys=(), analytics=(), state=False, public=False):
    return {
        "label": label,
        "group": group,
        "keys": set(keys),
        "analytics": set(analytics),
        "state": bool(state),
        # A public section needs no code and is always open. Reserved for
        # pages that carry no mission data of their own.
        "public": bool(public),
    }


# Section id -> what it needs from the API.
#   keys      = top-level /api/dashboard keys the view dereferences
#   analytics = sub-keys of the "analytics" object it dereferences
#   state     = whether the view needs /api/state telemetry
SECTIONS = {
    # ---------------------------------------------------------------- Mission
    "overview": _section("Mission Overview", "Mission",
                         keys=["metrics", "constellation", "charts", "configuration", "camera"],
                         state=True),
    "explorer": _section("State Explorer", "Mission", state=True),
    "coverage": _section("Coverage Map", "Mission",
                         keys=["coverage", "constellation"]),
    "imaging": _section("Payload & Imaging", "Mission",
                        keys=["camera", "imaging", "constellation"]),
    "global": _section("Global Coverage", "Mission",
                       keys=["globalCoverage", "constellation"], state=True),
    # The Data & Config view also drives the consolidated PDF/Excel report,
    # which embeds figures from most analytics blocks -- hence the wide need.
    "data": _section("Data & Config", "Mission",
                     keys=["metrics", "constellation", "configuration", "tables", "coverage"],
                     analytics=["summary", "gapAnalysis", "revisit", "simulationDetails",
                                "groundStations", "satelliteContributions"]),
    # Always open: this is the help page that explains what every metric
    # means. It contains only definitions -- no mission data -- and locking
    # the instructions would defeat their purpose.
    "guide": _section("How to Read This Dashboard", "Mission", public=True),

    # ------------------------------------------------ Constellation Analytics
    "summary": _section("Constellation Summary", "Constellation Analytics",
                        keys=["constellation"], analytics=["summary"]),
    "revisit": _section("Revisit Analytics", "Constellation Analytics",
                        analytics=["revisit"]),
    "gap-analysis": _section("Coverage Gap Analysis", "Constellation Analytics",
                             analytics=["gapAnalysis"]),
    "ground-stations": _section("Ground Station Analysis", "Constellation Analytics",
                                analytics=["groundStations"]),
    "sat-contribution": _section("Satellite Contribution", "Constellation Analytics",
                                 analytics=["satelliteContributions"]),
    "heatmaps": _section("Constellation Heatmaps", "Constellation Analytics",
                         analytics=["heatmaps"]),
    "aoi-analytics": _section("AOI Analytics", "Constellation Analytics",
                              analytics=["aoi"]),
    "sim-details": _section("Simulation Details", "Constellation Analytics",
                            analytics=["simulationDetails"]),
    "constellation-anim": _section("Constellation Animation", "Constellation Analytics",
                                   state=True),
    "mission-analytics": _section("Mission Analytics", "Constellation Analytics",
                                  analytics=["missionHealth"]),
    "comparison": _section("Mission Comparison", "Constellation Analytics"),

    # ---------------------------------------------------- Mission Image Center
    "ic-catalog": _section("Image Catalog", "Mission Image Center"),
    "ic-gallery": _section("Image Gallery", "Mission Image Center"),
    "ic-location": _section("Global Location Explorer", "Mission Image Center"),

    # ------------------------------------------- Duty cycle Phase 1 (K1 -- K5)
    "k1": _section("K1 · Constellation Transit", "Duty cycle · Phase 1",
                   keys=["constellation", "charts"], state=True),
    "k2": _section("K2 · Sensor Power Gating", "Duty cycle · Phase 1",
                   keys=["duty", "constellation"]),
    "k3": _section("K3 · Store & Downlink", "Duty cycle · Phase 1",
                   keys=["duty", "metrics", "tables", "charts", "constellation"]),
    "k4": _section("K4 · Ground Station Downlink", "Duty cycle · Phase 1",
                   keys=["metrics", "charts"]),
    "k5": _section("K5 · Command Uplink", "Duty cycle · Phase 1",
                   keys=["tables", "metrics", "constellation"]),

    # ------------------------------------------ Duty cycle Phase 2 (K6 -- K10)
    "k6": _section("K6 · AOI Active Coverage", "Duty cycle · Phase 2",
                   keys=["coverage", "constellation"]),
    "k7": _section("K7 · Power Duty Budget", "Duty cycle · Phase 2",
                   keys=["metrics", "duty", "charts"]),
    "k8": _section("K8 · Onboard Processing", "Duty cycle · Phase 2",
                   keys=["duty", "metrics", "coverage", "constellation"], state=True),
    "k9": _section("K9 · Downlink Pipeline", "Duty cycle · Phase 2",
                   keys=["tables", "coverage", "constellation"]),
    "k10": _section("K10 · Orbit Management", "Duty cycle · Phase 2",
                    keys=["metrics", "tables", "charts", "constellation"], state=True),

    # Legacy API surface with no frontend caller (/api/scenes, /api/products,
    # /api/intelligence, /api/plan/*, /api/analytics/aoi/*). Kept reachable for
    # tooling but locked by default so it cannot be used to sidestep the gates
    # on the sections above.
    "legacy-tools": _section("Legacy API Tools", "Legacy"),
}

# Sections whose views consume /api/state. The state report is a single
# indivisible satellite time-series, so unlocking any one of these grants the
# telemetry the others also read -- documented rather than silently ignored.
STATE_SECTIONS = {sid for sid, meta in SECTIONS.items() if meta["state"]}

# Sections that need no code at all.
PUBLIC_SECTIONS = {sid for sid, meta in SECTIONS.items() if meta["public"]}

# Sections a code is actually issued for.
CODED_SECTIONS = {sid for sid in SECTIONS if sid not in PUBLIC_SECTIONS}


# --------------------------------------------------------------------------
# Codes and signing secret
# --------------------------------------------------------------------------


# Length of the random part of an access code, in hex characters.
#
# This was 4 (65,536 combinations), which is fine on a trusted LAN but is
# enumerable in minutes once the server is reachable from the internet. 10
# hex characters is ~1.1 x 10^12 combinations, which together with the
# throttle on the unlock endpoint puts brute force out of reach.
CODE_RANDOM_HEX = 10


def _random_code(section_id):
    tag = re.sub(r"[^A-Z0-9]", "", section_id.upper())[:8] or "SECTION"
    body = secrets.token_hex(CODE_RANDOM_HEX // 2).upper()
    # Grouped for legibility when read aloud or copied by hand.
    grouped = "-".join(body[i:i + 5] for i in range(0, len(body), 5))
    return f"ASC074-{tag}-{grouped}"


def _master_code():
    tag = "ALLACCESS"
    body = secrets.token_hex(CODE_RANDOM_HEX // 2).upper()
    grouped = "-".join(body[i:i + 5] for i in range(0, len(body), 5))
    return f"ASC074-{tag}-{grouped}"


def _default_codes():
    return {
        "_comment": (
            "Access codes for the ASC_074 dashboard. Give a person the code for each "
            "section they should be able to open. Edit any value to set your own code; "
            "several sections may share the same code if you want to group them. "
            "sessionHours controls how long an unlock lasts before it must be re-entered. "
            "masterCode opens every section, mission AND download at once -- keep it for "
            "people who need the whole dashboard (e.g. a reviewer or the CEO) rather "
            "than handing it out routinely. missionCodes gates switching to a "
            "non-default mission (e.g. the 3x1 constellation) the same way a section "
            "code gates a section -- the default mission needs no code. downloadCodes are "
            "separate from the viewing codes above: a person can view a section with its "
            "own code and still be asked a second, different code before a report or file "
            "from that section actually downloads -- give a person the download code only "
            "if they should be able to take data out of the dashboard, not just see it."
        ),
        "sessionHours": DEFAULT_SESSION_HOURS,
        "masterCode": _master_code(),
        "codes": {sid: _random_code(sid) for sid in sorted(CODED_SECTIONS)},
        "missionCodes": {mid: _random_code(f"MISSION-{mid}") for mid in NON_DEFAULT_MISSIONS},
        "downloadCodes": {sid: _random_code(f"DL-{sid}") for sid in sorted(CODED_SECTIONS)},
    }


def load_codes():
    """Load the codes, from the environment if set, else the local file.

    A hosted deployment has an ephemeral filesystem: every restart or redeploy
    wipes the container, so a generated codes file would produce *new codes
    each time* and silently break every code already handed out. Setting
    ASC074_ACCESS_CODES (the JSON contents of config/access_codes.json) pins
    them, so the codes you distribute keep working across restarts.
    """
    env_codes = os.environ.get("ASC074_ACCESS_CODES")
    if env_codes:
        try:
            data = json.loads(env_codes)
            codes = data.get("codes", data)  # accept the whole file or just the mapping
            return {
                "sessionHours": float(data.get("sessionHours", DEFAULT_SESSION_HOURS)
                                      if isinstance(data, dict) else DEFAULT_SESSION_HOURS),
                "codes": codes,
                "masterCode": data.get("masterCode") if isinstance(data, dict) else None,
                "missionCodes": data.get("missionCodes", {}) if isinstance(data, dict) else {},
                "downloadCodes": data.get("downloadCodes", {}) if isinstance(data, dict) else {},
            }
        except Exception:
            pass  # malformed env var must not lock the operator out; fall through

    if not CODES_PATH.exists():
        CODES_PATH.parent.mkdir(parents=True, exist_ok=True)
        CODES_PATH.write_text(json.dumps(_default_codes(), indent=2), encoding="utf-8")

    try:
        data = json.loads(CODES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"sessionHours": DEFAULT_SESSION_HOURS, "codes": {}}

    codes = data.get("codes", {})
    # A section added to the registry after the file was written gets a fresh
    # code appended rather than silently becoming unprotected-or-unopenable.
    missing = {sid: _random_code(sid) for sid in CODED_SECTIONS if sid not in codes}
    # A section that has since become public keeps no code -- leaving a dead
    # entry behind would look like a code that grants something.
    stale = [sid for sid in codes if sid not in CODED_SECTIONS]
    # An installation created before the master code existed gets one added,
    # same as a missing section code above.
    master = data.get("masterCode") or _master_code()
    mission_codes = data.get("missionCodes") or {}
    missing_missions = {mid: _random_code(f"MISSION-{mid}") for mid in NON_DEFAULT_MISSIONS if mid not in mission_codes}
    stale_missions = [mid for mid in mission_codes if mid not in NON_DEFAULT_MISSIONS]
    download_codes = data.get("downloadCodes") or {}
    missing_downloads = {sid: _random_code(f"DL-{sid}") for sid in CODED_SECTIONS if sid not in download_codes}
    stale_downloads = [sid for sid in download_codes if sid not in CODED_SECTIONS]
    if (missing or stale or missing_missions or stale_missions or missing_downloads or stale_downloads
            or not data.get("masterCode")):
        codes.update(missing)
        for sid in stale:
            codes.pop(sid, None)
        mission_codes.update(missing_missions)
        for mid in stale_missions:
            mission_codes.pop(mid, None)
        download_codes.update(missing_downloads)
        for sid in stale_downloads:
            download_codes.pop(sid, None)
        data["codes"] = codes
        data["masterCode"] = master
        data["missionCodes"] = mission_codes
        data["downloadCodes"] = download_codes
        CODES_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")

    return {
        "sessionHours": float(data.get("sessionHours", DEFAULT_SESSION_HOURS) or DEFAULT_SESSION_HOURS),
        "codes": codes,
        "masterCode": master,
        "missionCodes": mission_codes,
        "downloadCodes": download_codes,
    }


def _secret():
    """Token signing key, from the environment if set, else the local file.

    On a hosted deployment this must come from the environment: a generated
    file would be recreated on every restart, invalidating every issued token
    and logging everyone out unpredictably.
    """
    env_secret = os.environ.get("ASC074_ACCESS_SECRET")
    if env_secret:
        return env_secret.strip().encode("utf-8")

    if not SECRET_PATH.exists():
        SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
        SECRET_PATH.write_text(secrets.token_hex(32), encoding="utf-8")
    return SECRET_PATH.read_text(encoding="utf-8").strip().encode("utf-8")


# --------------------------------------------------------------------------
# Brute-force throttle
# --------------------------------------------------------------------------
# Guessing is the only attack against a code, so the defence is to make
# guesses expensive. Failures per client are counted in memory; once the
# allowance is spent, attempts are refused for a cooling-off period. Counters
# reset on restart, which is acceptable: the window only needs to outlast a
# scripted run, and nothing is persisted that could wrongly lock out a
# legitimate user forever.

FAILURE_ALLOWANCE = 8          # failures before the client is made to wait
LOCKOUT_SECONDS = 300          # how long the cooling-off period lasts
FAILURE_WINDOW_SECONDS = 900   # failures older than this stop counting

_failures = {}


def _client_key(request):
    # X-Forwarded-For matters behind a tunnel or reverse proxy, where the
    # socket address is the proxy rather than the caller.
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.remote_addr or "unknown"


def throttle_state(request):
    """(allowed, seconds_to_wait) for this client's next unlock attempt."""
    key = _client_key(request)
    now = time.time()
    hits = [t for t in _failures.get(key, []) if now - t < FAILURE_WINDOW_SECONDS]
    _failures[key] = hits
    if len(hits) < FAILURE_ALLOWANCE:
        return True, 0
    wait = int(LOCKOUT_SECONDS - (now - hits[-1]))
    if wait <= 0:
        _failures[key] = []      # cooling-off served; start fresh
        return True, 0
    return False, wait


def record_failure(request):
    _failures.setdefault(_client_key(request), []).append(time.time())


def clear_failures(request):
    _failures.pop(_client_key(request), None)


def verify_code(section_id, code):
    """True if `code` is the configured code for `section_id`."""
    if section_id in PUBLIC_SECTIONS:
        return True  # nothing to verify -- always open
    if section_id not in SECTIONS or not code:
        return False
    configured = load_codes()["codes"].get(section_id)
    if not configured:
        return False
    return hmac.compare_digest(str(configured).strip(), str(code).strip())


def verify_master_code(code):
    """True if `code` is the configured master code, which opens every section.

    Separate from the per-section codes: those stay the normal path for
    someone who should see specific sections, this is for someone (developer,
    reviewer, leadership) who needs the whole dashboard without unlocking
    each section one at a time.
    """
    if not code:
        return False
    configured = load_codes().get("masterCode")
    if not configured:
        return False
    return hmac.compare_digest(str(configured).strip(), str(code).strip())


def verify_mission_code(mission_id, code):
    """True if `code` is the configured code for switching into `mission_id`.

    Public missions (see PUBLIC_MISSIONS) need no code. Any other mission
    needs its own code to switch into, the same way a section needs its own
    code to open.
    """
    if mission_id in PUBLIC_MISSIONS or mission_id not in MISSIONS:
        return True
    if not code:
        return False
    configured = load_codes().get("missionCodes", {}).get(mission_id)
    if not configured:
        return False
    return hmac.compare_digest(str(configured).strip(), str(code).strip())


def verify_download_code(section_id, code):
    """True if `code` is the configured download code for `section_id`.

    Separate from the code that unlocks the section for viewing: a person
    can hold the view code and see a section's data on screen, and still be
    asked a second, different code before that data is allowed to actually
    leave the dashboard as a downloaded file. Public sections carry no
    download code -- there is no view-gate to duplicate.
    """
    if section_id in PUBLIC_SECTIONS:
        return True
    if section_id not in SECTIONS or not code:
        return False
    configured = load_codes().get("downloadCodes", {}).get(section_id)
    if not configured:
        return False
    return hmac.compare_digest(str(configured).strip(), str(code).strip())


# --------------------------------------------------------------------------
# Tokens
# --------------------------------------------------------------------------


def _b64e(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text):
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def issue_token(sections, missions=(), downloads=(), session_hours=None):
    """Sign a token carrying the unlocked section ids, unlocked mission ids
    (beyond the always-open default mission), unlocked download-section ids,
    and an expiry.

    Download grants are intentionally separate from section grants: holding
    a section's view code does not imply holding its download code, so a
    caller must have gone through /api/access/unlock with downloadSection=
    at least once for that section to appear here.
    """
    hours = session_hours if session_hours is not None else load_codes()["sessionHours"]
    body = json.dumps(
        {
            "s": sorted(set(sections)),
            "m": sorted(set(missions) - PUBLIC_MISSIONS),
            "d": sorted(set(downloads) - PUBLIC_SECTIONS),
            "exp": int(time.time() + hours * 3600),
        },
        separators=(",", ":"),
    ).encode("utf-8")
    sig = hmac.new(_secret(), body, hashlib.sha256).digest()
    return f"{_b64e(body)}.{_b64e(sig)}"


def _decode_token(token):
    """Verified token payload dict, or None if missing/forged/expired."""
    if not token or "." not in str(token):
        return None
    try:
        body_b64, sig_b64 = str(token).split(".", 1)
        body = _b64d(body_b64)
        expected = hmac.new(_secret(), body, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64d(sig_b64)):
            return None
        payload = json.loads(body.decode("utf-8"))
        if int(payload.get("exp", 0)) < time.time():
            return None
        return payload
    except Exception:
        return None


def verify_token(token):
    """Return the set of section ids a token grants.

    Public sections are always included, so a caller with no token at all
    still reaches them.
    """
    payload = _decode_token(token)
    if payload is None:
        return set(PUBLIC_SECTIONS)
    granted = {s for s in payload.get("s", []) if s in SECTIONS}
    return granted | PUBLIC_SECTIONS


def verify_mission_token(token):
    """Return the set of mission ids a token grants beyond the public ones.

    Public missions need no code and are always included, mirroring how
    public sections are always included regardless of the token.
    """
    payload = _decode_token(token)
    if payload is None:
        return set(PUBLIC_MISSIONS)
    granted = {m for m in payload.get("m", []) if m in MISSIONS}
    return granted | PUBLIC_MISSIONS


def verify_download_token(token):
    """Return the set of section ids this token may download from.

    Unlike sections and missions, there is no free grant here beyond public
    sections -- viewing a section (even holding its own view code) does not
    by itself unlock downloading from it.
    """
    payload = _decode_token(token)
    if payload is None:
        return set(PUBLIC_SECTIONS)
    granted = {s for s in payload.get("d", []) if s in SECTIONS}
    return granted | PUBLIC_SECTIONS


def unlocked_sections(request):
    """Sections unlocked for this request.

    The token normally arrives in the X-Access-Token header. Browser-native
    GETs that cannot carry a header -- <img src>, <a href> downloads and
    window.open -- fall back to an `access` query parameter.
    """
    token = request.headers.get("X-Access-Token") or request.args.get("access")
    return verify_token(token)


def unlocked_missions(request):
    """Mission ids unlocked for this request (always includes the default)."""
    token = request.headers.get("X-Access-Token") or request.args.get("access")
    return verify_mission_token(token)


def unlocked_downloads(request):
    """Section ids this request may download from (public sections only, by default)."""
    token = request.headers.get("X-Access-Token") or request.args.get("access")
    return verify_download_token(token)


# --------------------------------------------------------------------------
# Payload filtering
# --------------------------------------------------------------------------


def required_keys(unlocked):
    """Union of the payload keys and analytics sub-keys the unlocked sections need."""
    keys = set(ALWAYS_KEYS)
    analytics = set()
    for sid in unlocked:
        meta = SECTIONS.get(sid)
        if not meta:
            continue
        keys |= meta["keys"]
        analytics |= meta["analytics"]
    if analytics:
        keys.add("analytics")
    return keys, analytics


def filter_dashboard_payload(payload, unlocked):
    """Shallow-copy `payload` keeping only what the unlocked sections need.

    The source payload is the shared @lru_cache'd object, so this must never
    mutate it or any nested container -- only build new top-level containers.
    """
    keys, analytics = required_keys(unlocked)

    out = {k: v for k, v in payload.items() if k in keys}
    if "analytics" in out:
        out["analytics"] = {
            k: v for k, v in payload.get("analytics", {}).items() if k in analytics
        }

    out["unlockedSections"] = sorted(unlocked)
    out["lockedSections"] = sorted(set(SECTIONS) - set(unlocked))
    return out


def section_listing(unlocked):
    """Every section with its lock state. Never includes the codes themselves."""
    return [
        {
            "id": sid,
            "label": meta["label"],
            "group": meta["group"],
            "unlocked": sid in unlocked or meta["public"],
            "public": meta["public"],
        }
        for sid, meta in SECTIONS.items()
    ]


def mission_listing(unlocked_mission_ids):
    """Every mission with its lock state. Never includes the codes themselves."""
    return [
        {
            "id": mid,
            "label": meta["label"],
            "unlocked": mid in unlocked_mission_ids or mid in PUBLIC_MISSIONS,
            "public": mid in PUBLIC_MISSIONS,
        }
        for mid, meta in MISSIONS.items()
    ]


def download_listing(unlocked_download_ids):
    """Every coded section's download-lock state, keyed separately from its
    view-lock state (section_listing above) -- a section can be unlocked
    for viewing and still show downloadUnlocked: false here."""
    return [
        {
            "id": sid,
            "label": meta["label"],
            "unlocked": sid in unlocked_download_ids or sid in PUBLIC_SECTIONS,
            "public": sid in PUBLIC_SECTIONS,
        }
        for sid, meta in SECTIONS.items()
    ]
