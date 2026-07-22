Edit config/Mission_Configuration.xlsx, save it, refresh Streamlit.\nRun: python -m streamlit run app.py\n

v0.6 additions:
- Dynamic Camera / Payload Module for any constellation size
- Camera geometry recalculated from configured orbit altitude
- K3 Payload Data & Onboard Storage Management
- No fabricated data rate, storage capacity, compression, or processing values
\n\nv0.7 additions:\n- Replaced rectangular Australia AOI trigger with Australia land-boundary approximation\n- K2/K3 use modeled camera swath intersection with Australia\n- Dynamic camera swath remains linked to configured altitude\n- Coverage logic is an engineering approximation, not an official GIS coverage solution\n

v0.8 additions:
- Australia Cumulative Coverage Analysis tab
- Grid-based cumulative coverage percentage
- Covered and uncovered analysis-cell map
- Per-satellite coverage contribution
- In-dashboard How Coverage Is Calculated explanation and formula
- Clear limitations and data-source classification


v0.9 additions:
- Australia Observation Duration Analysis
- Per-satellite total observation time and duty cycle
- Observation-window count, average window and longest window
- First and last observation timestamps
- Summed satellite observation time
- Unique constellation observation time
- Maximum simultaneous observing satellites
- Detailed observation-window table


v0.10 additions:
- K3 Data Generation Configuration
- Configurable raw data rate, bits per pixel, active bands and image size
- Configurable compression ratio, onboard storage capacity and processing rate
- Data volume linked to actual Australia observation duration
- Per-satellite raw/compressed data and storage utilization
- No assumed hardware values; unknowns remain Not Configured
- In-dashboard K3 formulas and traceability explanation
