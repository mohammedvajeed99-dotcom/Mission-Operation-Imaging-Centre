from pathlib import Path
import re
import pandas as pd


def parse_state_report(path):
    path = Path(path)
    if not path.exists():
        return pd.DataFrame()
    lines = [ln.rstrip() for ln in path.read_text(encoding='utf-8', errors='ignore').splitlines() if ln.strip()]
    if len(lines) < 2:
        return pd.DataFrame()
    headers = re.split(r'\s{2,}', lines[0].strip())
    rows = []
    for line in lines[1:]:
        vals = re.split(r'\s{2,}', line.strip())
        if len(vals) == len(headers):
            rows.append(vals)
    wide = pd.DataFrame(rows, columns=headers)
    if wide.empty:
        return wide
    time_col = next((c for c in headers if c.endswith('.UTCGregorian')), None)
    if not time_col:
        return pd.DataFrame()
    wide['Timestamp'] = pd.to_datetime(wide[time_col], format='%d %b %Y %H:%M:%S.%f', errors='coerce')
    sats = sorted({c.split('.')[0] for c in headers if '.' in c})
    frames = []
    for sat in sats:
        data = {'Timestamp': wide['Timestamp'], 'Satellite Name': sat}
        for field in ['Latitude','Longitude','Altitude','RMAG','ECC']:
            col = f'{sat}.{field}'
            if col in wide.columns:
                data[field] = pd.to_numeric(wide[col], errors='coerce')
        frames.append(pd.DataFrame(data))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
