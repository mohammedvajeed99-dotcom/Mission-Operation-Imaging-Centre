
from pathlib import Path
import re
import pandas as pd

DT = r"\d{2}\s+[A-Za-z]{3}\s+\d{4}\s+\d{2}:\d{2}:\d{2}\.\d+"
ROW = re.compile(
    rf"^\s*({DT})\s+({DT})\s+([0-9.]+)\s+(\S+)\s+(\S+)\s+(\d+)\s+([0-9.]+)\s*$"
)

def parse_eclipse_file(path):
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    sc = re.search(r"Spacecraft:\s*(.+)", text)
    satellite = sc.group(1).strip() if sc else Path(path).stem
    rows = []
    for line in text.splitlines():
        m = ROW.match(line)
        if m:
            start, stop, duration, body, etype, event_no, total_duration = m.groups()
            sdt = pd.to_datetime(start, format="%d %b %Y %H:%M:%S.%f")
            edt = pd.to_datetime(stop, format="%d %b %Y %H:%M:%S.%f")
            rows.append({
                "Satellite Name": satellite,
                "Eclipse Type": etype,
                "Occulting Body": body,
                "Event Number": int(event_no),
                "Start UTC": sdt,
                "Stop UTC": edt,
                "Start Date": sdt.date(),
                "Start Time": sdt.time(),
                "Stop Date": edt.date(),
                "Stop Time": edt.time(),
                "Duration (s)": float(duration),
                "Total Event Duration (s)": float(total_duration),
                "Source File": Path(path).name,
            })
    return rows

def parse_eclipse_folder(folder):
    rows = []
    for path in sorted(Path(folder).glob("*.txt")):
        rows.extend(parse_eclipse_file(path))
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.drop_duplicates(
            subset=["Satellite Name","Eclipse Type","Start UTC","Stop UTC"]
        ).sort_values(["Start UTC","Satellite Name"]).reset_index(drop=True)
        df.insert(0, "Sl No", range(1, len(df)+1))
    return df
