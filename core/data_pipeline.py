from pathlib import Path
import pandas as pd
from core.contact_parser import parse_contact_folder
from core.eclipse_parser import parse_eclipse_folder
from core.state_parser import parse_state_report


def read_processed_frame(path):
    """Read a processed .xlsx, via a binary side-cache.

    Parsing the 44k-row state workbook with openpyxl costs ~6 s and happens
    on every cold start. The pickle beside it reloads in milliseconds and is
    rebuilt automatically whenever the .xlsx is newer, so a pipeline refresh
    is picked up without any manual cache clearing.
    """
    path = Path(path)
    if not path.exists():
        return pd.DataFrame()

    cache = path.parent / ".cache" / f"{path.stem}.pkl"
    try:
        if cache.exists() and cache.stat().st_mtime >= path.stat().st_mtime:
            return pd.read_pickle(cache)
    except Exception:
        pass  # unreadable/stale cache is never fatal -- fall through to the xlsx

    df = pd.read_excel(path)
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        df.to_pickle(cache)
    except Exception:
        pass  # a read-only data directory just means no caching
    return df

def run_pipeline(base_dir=None, raw_dir=None, out_dir=None):
    base = Path(base_dir) if base_dir else Path(__file__).resolve().parents[1]
    raw = Path(raw_dir) if raw_dir else base / 'data' / 'raw'
    out = Path(out_dir) if out_dir else base / 'data' / 'processed'
    out.mkdir(parents=True, exist_ok=True)
    rf = parse_contact_folder(raw / 'contacts' / 'rf', 'RF')
    optical = parse_contact_folder(raw / 'contacts' / 'optical', 'Optical')
    eclipse = parse_eclipse_folder(raw / 'eclipse')
    state_path = raw / 'state' / 'StateReport.txt'
    if not state_path.exists():
        state_path = base / 'StateReport.txt'
    state = parse_state_report(state_path)
    outputs = {'RF_Contacts.xlsx': rf, 'Optical_Contacts.xlsx': optical,
               'All_Eclipse_Events.xlsx': eclipse, 'Satellite_State_History.xlsx': state}
    for filename, df in outputs.items(): df.to_excel(out / filename, index=False)
    return {'rf_events':len(rf),'optical_events':len(optical),'eclipse_rows':len(eclipse),
            'state_rows':len(state),'state_satellites':state['Satellite Name'].nunique() if not state.empty else 0}
