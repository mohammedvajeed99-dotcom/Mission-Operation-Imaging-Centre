from pathlib import Path
import re
import pandas as pd

# A GMAT UTCGregorian value is itself "DD Mon YYYY HH:MM:SS.mmm" -- four
# whitespace-separated tokens for one column's value.
DATE_TOKEN_COUNT = 4


def parse_state_report(path):
    path = Path(path)
    if not path.exists():
        return pd.DataFrame()
    lines = [ln.rstrip() for ln in path.read_text(encoding='utf-8', errors='ignore').splitlines() if ln.strip()]
    if len(lines) < 2:
        return pd.DataFrame()

    # GMAT ReportFile exports come in two spacing conventions: columns
    # padded/aligned with 2+ spaces between them, or a single space. A
    # header name never contains an internal space, so splitting on 2+
    # spaces is unambiguous for detecting which convention this file uses.
    headers = re.split(r'\s{2,}', lines[0].strip())
    aligned = len(headers) > 1
    if not aligned:
        headers = re.split(r'\s+', lines[0].strip())

    time_col = next((c for c in headers if c.endswith('.UTCGregorian')), None)
    if not time_col:
        return pd.DataFrame()

    if aligned:
        rows = []
        for line in lines[1:]:
            vals = re.split(r'\s{2,}', line.strip())
            if len(vals) == len(headers):
                rows.append(vals)
        wide = pd.DataFrame(rows, columns=headers)
    else:
        # Single-space format: a data row can't be split on whitespace
        # directly, since a UTCGregorian value spans 4 whitespace tokens
        # while every other field is exactly 1. Walk the header list in
        # order, consuming the right number of raw tokens per column.
        rows = []
        for line in lines[1:]:
            tokens = re.split(r'\s+', line.strip())
            vals = []
            i = 0
            ok = True
            for h in headers:
                width = DATE_TOKEN_COUNT if h.endswith('.UTCGregorian') else 1
                if i + width > len(tokens):
                    ok = False
                    break
                vals.append(' '.join(tokens[i:i + width]))
                i += width
            if ok and i == len(tokens):
                rows.append(vals)
        wide = pd.DataFrame(rows, columns=headers)

    if wide.empty:
        return wide
    wide['Timestamp'] = pd.to_datetime(wide[time_col], format='%d %b %Y %H:%M:%S.%f', errors='coerce')
    sats = sorted({c.split('.')[0] for c in headers if '.' in c})
    frames = []
    for sat in sats:
        data = {'Timestamp': wide['Timestamp'], 'Satellite Name': sat}
        for field in ['Latitude','Longitude','Altitude','RMAG','ECC']:
            # Field columns are usually "Sat.Field" but some GMAT reports insert
            # a body segment, e.g. "Sat.Earth.Field" -- match either.
            col = next(
                (c for c in headers
                 if c == f'{sat}.{field}' or re.match(rf'^{re.escape(sat)}\.\w+\.{field}$', c)),
                None,
            )
            if col:
                data[field] = pd.to_numeric(wide[col], errors='coerce')
        frames.append(pd.DataFrame(data))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
