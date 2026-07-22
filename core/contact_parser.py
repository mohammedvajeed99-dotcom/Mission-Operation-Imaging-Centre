
from pathlib import Path
import re
import pandas as pd

DT = r"\d{2}\s+[A-Za-z]{3}\s+\d{4}\s+\d{2}:\d{2}:\d{2}\.\d+"
ROW = re.compile(rf"^\s*({DT})\s+({DT})\s+([0-9.]+)\s*$")

def parse_contact_file(path, link_type):
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    target = re.search(r"Target:\s*(.+)", text)
    observer = re.search(r"Observer:\s*(.+)", text)
    satellite = target.group(1).strip() if target else Path(path).stem
    ground_station = observer.group(1).strip() if observer else ""
    rows = []
    for line in text.splitlines():
        m = ROW.match(line)
        if m:
            start, stop, duration = m.groups()
            sdt = pd.to_datetime(start, format="%d %b %Y %H:%M:%S.%f")
            edt = pd.to_datetime(stop, format="%d %b %Y %H:%M:%S.%f")
            rows.append({
                "Satellite Name": satellite,
                "Ground Station": ground_station,
                "Link Type": link_type,
                "Start UTC": sdt,
                "Stop UTC": edt,
                "Start Date": sdt.date(),
                "Start Time": sdt.time(),
                "Stop Date": edt.date(),
                "Stop Time": edt.time(),
                "Duration (s)": float(duration),
                "Source File": Path(path).name,
            })
    return rows

def parse_contact_folder(folder, link_type):
    rows = []
    for path in sorted(Path(folder).glob("*.txt")):
        rows.extend(parse_contact_file(path, link_type))
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.drop_duplicates(
            subset=["Satellite Name","Ground Station","Link Type","Start UTC","Stop UTC"]
        ).sort_values(["Start UTC","Satellite Name"]).reset_index(drop=True)
        df.insert(0, "Sl No", range(1, len(df)+1))
    return df
