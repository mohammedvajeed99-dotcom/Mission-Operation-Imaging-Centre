"""One-time import of the authoritative Country -> State -> District -> City
dataset from a supplied Excel workbook into data/location_dataset.json.

Run by hand, once, whenever the source workbook changes:

    python scripts/import_location_dataset.py "path/to/0-Locations of service (Australia & India).xlsx"

The output is checked into the repo as bundled, static data -- core.location_dataset
loads it at import time and never touches the source Excel file or the network
again. This replaces core.geocode's live Nominatim lookups as the primary
source (see the plan this script was built from for why).

--------------------------------------------------------------------------
Source workbook layout (reverse-engineered by direct cell inspection --
this is NOT a normal one-row-per-record table, see below)
--------------------------------------------------------------------------

One sheet. Three logically-independent tables sharing row-space:

1. India states summary: rows 4-31, columns B/C/D = No./State/Capital.
2. India union territories summary: rows 33-40, same columns.
3. India per-state district blocks: each state/UT's OWN row also carries a
   small table far to the right of the sheet -- a "District" (or "Island")
   header cell, followed rightward by some combination of "Headquarters",
   "Latitude"/"Approximate Latitude", "Longitude"/"Approximate Longitude"
   (block width varies: 3 or 4 columns depending on the state, so this is
   detected per-block, never assumed constant). Data rows follow directly
   below the header until a fully-empty row.

   One confirmed, real exception: Jammu & Kashmir (row 37) has NO block of
   its own -- both its own block and Ladakh's (row 38) are parked side by
   side on row 38, J&K's at the higher column number (further right, since
   blocks step left as you go down the sheet). Detected generically below
   (a 0-header row borrows the extra, higher-column header from the row
   below it), not hardcoded by name, though it's asserted by name too as a
   sanity check.

4. Australia: seven flat per-state tables stacked vertically, each preceded
   by a "<State> -- <count>" marker row and a sub-header row (No. / Council
   / Principal locality / Postcode / Latitude / Longitude). One row per
   council, count-checked against the marker's own stated total.
"""

import json
import re
import sys
from pathlib import Path

import openpyxl

BASE = Path(__file__).resolve().parent.parent
OUT_PATH = BASE / "data" / "location_dataset.json"

INDIA_STATE_ROWS = range(4, 32)   # 28 states
INDIA_UT_ROWS = range(33, 41)     # 8 union territories
MAX_SCAN_COL = 220

# Australian council-name suffixes stripped for the *display* district name
# only -- the raw council name is kept too. Longest-first so "City Council"
# doesn't leave a dangling "City" after a shorter match.
AU_SUFFIXES = [
    " Regional Council", " Municipal Council", " City Council",
    " Shire Council", " Town Council", " Council",
]


def _clean_council_name(raw):
    name = raw.strip()
    for suf in AU_SUFFIXES:
        if name.endswith(suf):
            return name[: -len(suf)].strip()
    return name


def _parse_degree(raw):
    """'18.08° N' / '82.67° E' (or a mangled-encoding variant of the
    degree symbol) -> signed float. Sign comes from the trailing hemisphere
    letter (S or W negate), never assumed from context."""
    if raw is None:
        return None
    s = str(raw).strip()
    m = re.match(r"^(-?\d+(?:\.\d+)?)", s)
    if not m:
        return None
    val = float(m.group(1))
    if re.search(r"[SW]\s*$", s, re.IGNORECASE):
        val = -abs(val)
    else:
        val = abs(val)
    return val


def _row_values(ws, row, col_start, col_end):
    return [ws.cell(row=row, column=c).value for c in range(col_start, col_end)]


def _find_header_cells(ws, row, max_col=MAX_SCAN_COL):
    """Every column in `row` whose value is exactly 'District' or 'Island'
    -- these mark the start of one location-data block."""
    hits = []
    for c in range(1, max_col):
        v = ws.cell(row=row, column=c).value
        if v in ("District", "Island"):
            hits.append(c)
    return hits


# The only strings that are ever legitimately a block's own column header.
# _block_labels must stop at the first cell whose value isn't one of these
# -- NOT merely at the first empty cell. A state's header row is very often
# ALSO a data row for some other, earlier-headed block parked further right
# in the same row (the staircase shares row-space), so "keep going while
# non-empty" silently swallows that neighbour's real data as fake labels.
# Confirmed concretely: Goa's header row (9) is simultaneously Chhattisgarh's
# first data row at a higher column, so a naive empty-cell scan absorbed
# "Balod", "Balod", "20.73 N", ... as if they were Goa's own column labels.
# Every Australian state's own sub-header spells the "Council" column
# differently (confirmed by direct inspection: NSW/QLD/SA/TAS/VIC say
# "Council", NT says "Local Government Area / Council", WA says just
# "Local Government") -- all are accepted and all map to the same field.
COUNCIL_LABELS = {"Council", "Local Government Area / Council", "Local Government"}

KNOWN_LABELS = {
    "District", "Island", "Headquarters",
    "Latitude", "Longitude", "Approximate Latitude", "Approximate Longitude",
    "No.", "#", "Principal locality", "Postcode",
} | COUNCIL_LABELS


BLOCK_START_LABELS = {"District", "Island"}


def _block_labels(ws, row, start_col):
    """Column labels for one block, scanning rightward from its header cell
    until either a cell whose value isn't a known header label, or a
    SECOND "District"/"Island" -- whichever comes first. Two things share
    row-space in this sheet: a state's header row is often also a data row
    for some other block parked further right (see KNOWN_LABELS' comment),
    and -- confirmed concretely on Ladakh's row, which carries its own
    4-column block immediately followed by Jammu & Kashmir's -- one row can
    carry two ADJACENT blocks' headers back to back. A block never repeats
    its own start label, so a second "District"/"Island" always marks the
    next block's header, not a continuation of this one.
    """
    labels = []
    c = start_col
    while True:
        v = ws.cell(row=row, column=c).value
        if v not in KNOWN_LABELS:
            break
        if v in BLOCK_START_LABELS and labels:
            break
        labels.append(str(v).strip())
        c += 1
    return labels


def _block_rows(ws, header_row, start_col, width):
    """Data rows for one block: starting at header_row+1, until a row with
    every cell in [start_col, start_col+width) empty."""
    rows = []
    r = header_row + 1
    while True:
        vals = _row_values(ws, r, start_col, start_col + width)
        if all(v is None for v in vals):
            break
        rows.append(vals)
        r += 1
        if r > header_row + 400:  # sanity backstop, never legitimately this long
            raise RuntimeError(f"Block at row {header_row} col {start_col} ran away past 400 rows")
    return rows


def _record_from_block(labels, vals, state):
    rec = {"state": state}
    for label, v in zip(labels, vals):
        low = label.lower()
        if low in ("district", "island"):
            rec["district"] = str(v).strip() if v is not None else None
        elif low == "headquarters":
            rec["city"] = str(v).strip() if v is not None else None
        elif "latitude" in low:
            rec["lat"] = _parse_degree(v)
        elif "longitude" in low:
            rec["lon"] = _parse_degree(v)
    if "city" not in rec:
        # 3-column blocks (Delhi's districts, Lakshadweep's islands) have no
        # separate headquarters -- the district/island name IS the place.
        rec["city"] = rec.get("district")
    return rec


def parse_india(ws):
    # 1. Read the two summary tables: row -> state/UT name.
    row_to_state = {}
    for r in INDIA_STATE_ROWS:
        name = ws.cell(row=r, column=3).value
        if name:
            row_to_state[r] = str(name).strip()
    for r in INDIA_UT_ROWS:
        name = ws.cell(row=r, column=3).value
        if name and name != "Union Territory":
            row_to_state[r] = str(name).strip()

    # 2. Find every block header in the union of those rows.
    headers_by_row = {}
    for r in row_to_state:
        hits = _find_header_cells(ws, r)
        if hits:
            headers_by_row[r] = sorted(hits)

    # 3. Rows with zero headers borrow the EXTRA (higher-column) header from
    # the next row down -- confirmed real case: Jammu & Kashmir (row 37, no
    # header) borrows the higher-column block parked on Ladakh's row (38).
    assignments = []  # (row_for_state_name, header_row, header_col)
    zero_header_rows = [r for r in row_to_state if r not in headers_by_row]
    for r in sorted(row_to_state):
        if r in headers_by_row:
            cols = headers_by_row[r]
            # The row's OWN block is its lowest-column header; any extra
            # (higher-column) header(s) belong to a zero-header row above.
            assignments.append((r, r, cols[0]))
            for extra_col in cols[1:]:
                donor_candidates = [z for z in zero_header_rows if z < r]
                if not donor_candidates:
                    raise RuntimeError(f"Extra block at row {r} col {extra_col} has no zero-header row above it to donate to")
                donor_row = max(donor_candidates)  # nearest row above with no block of its own
                assignments.append((donor_row, r, extra_col))

    unresolved = [r for r in zero_header_rows if r not in [a[0] for a in assignments]]
    if unresolved:
        raise RuntimeError(f"State/UT row(s) with no district block found: "
                            f"{[row_to_state[r] for r in unresolved]}")

    # Sanity-check the one specific pairing this logic is built to handle.
    jk_rows = [a for a in assignments if row_to_state.get(a[0]) == "Jammu and Kashmir"]
    if jk_rows and row_to_state.get(jk_rows[0][1]) != "Ladakh":
        raise RuntimeError("Expected Jammu & Kashmir's block to be parked on Ladakh's row; layout may have changed")

    # 4. Read every assigned block into records.
    records = []
    per_state_counts = {}
    for state_row, header_row, header_col in assignments:
        state = row_to_state[state_row]
        labels = _block_labels(ws, header_row, header_col)
        rows = _block_rows(ws, header_row, header_col, len(labels))
        for vals in rows:
            rec = _record_from_block(labels, vals, state)
            if rec.get("district") and rec.get("lat") is not None and rec.get("lon") is not None:
                records.append(rec)
        per_state_counts[state] = per_state_counts.get(state, 0) + len(rows)

    missing = [s for s in row_to_state.values() if per_state_counts.get(s, 0) == 0]
    if missing:
        raise RuntimeError(f"State/UT(s) with zero parsed districts: {missing}")

    return records, per_state_counts


def parse_australia(ws, max_row=1000):
    marker_re = re.compile(r"^(.+?)\s*[—\-]\s*(\d+)\s*$")
    records = []
    per_state_counts = {}
    r = 1
    while r <= max_row:
        v = ws.cell(row=r, column=2).value
        if isinstance(v, str):
            m = marker_re.match(v.strip())
            if m and ws.cell(row=r, column=3).value is None:
                state = m.group(1).strip()
                expected = int(m.group(2))
                header_row = r + 1
                labels = _block_labels(ws, header_row, 2)
                rows = _block_rows(ws, header_row, 2, len(labels))
                if len(rows) != expected:
                    raise RuntimeError(
                        f"{state}: header says {expected} councils, parsed {len(rows)}"
                    )
                for vals in rows:
                    rec = {"state": state}
                    for label, val in zip(labels, vals):
                        low = label.lower()
                        if label in COUNCIL_LABELS:
                            rec["districtRaw"] = str(val).strip() if val is not None else None
                            rec["district"] = _clean_council_name(str(val)) if val is not None else None
                        elif low == "principal locality":
                            rec["city"] = str(val).strip() if val is not None else None
                        elif low == "postcode":
                            rec["postcode"] = str(val).strip() if val is not None else None
                        elif low == "latitude":
                            rec["lat"] = float(val) if isinstance(val, (int, float)) else _parse_degree(val)
                        elif low == "longitude":
                            rec["lon"] = float(val) if isinstance(val, (int, float)) else _parse_degree(val)
                    if rec.get("district") and rec.get("lat") is not None and rec.get("lon") is not None:
                        records.append(rec)
                per_state_counts[state] = len(rows)
                r = header_row + len(rows) + 1
                continue
        r += 1
    return records, per_state_counts


def main():
    if len(sys.argv) != 2:
        print("Usage: python scripts/import_location_dataset.py <path to xlsx>")
        sys.exit(1)
    src = Path(sys.argv[1])
    wb = openpyxl.load_workbook(src, data_only=True)
    ws = wb["Sheet1"]

    india_records, india_counts = parse_india(ws)
    au_records, au_counts = parse_australia(ws)

    print("=== India: districts per state/UT ===")
    for state, count in india_counts.items():
        print(f"  {state}: {count}")
    print(f"India total: {len(india_records)} districts across {len(india_counts)} states/UTs")

    print("\n=== Australia: councils per state ===")
    for state, count in au_counts.items():
        print(f"  {state}: {count}")
    print(f"Australia total: {len(au_records)} councils across {len(au_counts)} states")

    if not (600 <= len(india_records) <= 900):
        raise RuntimeError(f"India district count {len(india_records)} outside sane range 600-900 -- check parsing")
    if len(au_records) < 500:
        raise RuntimeError(f"Australia council count {len(au_records)} looks too low -- check parsing")

    out = {
        "india": {"districts": india_records},
        "australia": {"districts": au_records},
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {OUT_PATH} ({len(india_records)} India + {len(au_records)} Australia records)")


if __name__ == "__main__":
    main()
