from pathlib import Path
import pandas as pd
REQUIRED_SHEETS=["Mission","Constellation","Orbit","Ground_Stations","Payload","Power"]
def load_mission_configuration(base_dir):
    path=Path(base_dir)/"config"/"Mission_Configuration.xlsx"
    xl=pd.ExcelFile(path)
    missing=[s for s in REQUIRED_SHEETS if s not in xl.sheet_names]
    if missing: raise ValueError("Missing sheets: "+", ".join(missing))
    out={"config_path":str(path)}
    for s in ["Mission","Constellation","Orbit","Payload","Power"]:
        df=pd.read_excel(path,sheet_name=s)
        out[s.lower()]={str(r["Parameter"]).strip():r["Value"] for _,r in df.iterrows() if pd.notna(r["Parameter"])}
        out[s.lower()+"_table"]=df
    out["ground_stations"]=pd.read_excel(path,sheet_name="Ground_Stations")
    return out
def validate_configuration(c):
    issues=[]
    try:
        x=c["constellation"]; p=int(x["Number of Planes"]); s=int(x["Satellites per Plane"]); t=int(x["Total Satellites"])
        if p*s!=t: issues.append(f"Constellation mismatch: {p} × {s} = {p*s}, but Total Satellites = {t}.")
    except Exception: issues.append("Constellation values must be numeric.")
    return issues
