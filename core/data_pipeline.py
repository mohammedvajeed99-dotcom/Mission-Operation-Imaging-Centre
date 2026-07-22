from pathlib import Path
from core.contact_parser import parse_contact_folder
from core.eclipse_parser import parse_eclipse_folder
from core.state_parser import parse_state_report

def run_pipeline(base_dir=None):
    base = Path(base_dir) if base_dir else Path(__file__).resolve().parents[1]
    raw = base / 'data' / 'raw'
    out = base / 'data' / 'processed'
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
