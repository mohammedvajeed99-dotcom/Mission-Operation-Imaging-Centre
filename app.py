from html import escape
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from core.australia_coverage import footprint_intersects_australia
from core.camera_model import build_camera_model, build_camera_modules
from core.config_loader import load_mission_configuration, validate_configuration
from core.cumulative_coverage import cumulative_australia_coverage
from core.data_pipeline import run_pipeline
from core.k3_data_model import (
    calculate_k3_from_observation,
    default_k3_config,
    derive_pushbroom_data_model,
)
from core.observation_duration import observation_duration_analysis


BASE = Path(__file__).resolve().parent
PROCESSED = BASE / "data" / "processed"
PLOT_TEMPLATE = "plotly_white"
ACCENT = "#2f6df6"
GREEN = "#22a06b"
AMBER = "#d9822b"
RED = "#c9372c"
INK = "#172033"


st.set_page_config(
    page_title="Mission Operations Center",
    page_icon=":satellite:",
    layout="wide",
    initial_sidebar_state="expanded",
)


st.markdown(
    """
<style>
:root {
  --bg: #f5f7fb;
  --surface: #ffffff;
  --surface-2: #eef3fb;
  --ink: #172033;
  --muted: #64748b;
  --line: #d8e1ef;
  --accent: #2f6df6;
  --accent-2: #18a6a6;
  --green: #22a06b;
  --amber: #d9822b;
  --red: #c9372c;
}

html, body, [data-testid="stAppViewContainer"] {
  background: var(--bg);
  color: var(--ink);
}

[data-testid="stHeader"] {
  background: rgba(245, 247, 251, 0.86);
  backdrop-filter: blur(10px);
}

.block-container {
  max-width: 1500px;
  padding: 1.1rem 2.1rem 2.5rem;
}

[data-testid="stSidebar"] {
  background: #111827;
  border-right: 1px solid rgba(255,255,255,.08);
}

[data-testid="stSidebar"] * {
  color: #f8fafc;
}

[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
[data-testid="stSidebar"] .stCaptionContainer {
  color: rgba(248,250,252,.72);
}

[data-testid="stSidebar"] .stButton button {
  border: 0;
  background: #ffffff;
  color: #111827;
  font-weight: 700;
  border-radius: 8px;
  min-height: 2.8rem;
}

h1, h2, h3 {
  color: var(--ink);
  letter-spacing: 0;
}

h1 {
  font-size: 2.05rem;
  line-height: 1.08;
  margin-bottom: .35rem;
}

h2, h3 {
  margin-top: .35rem;
}

.hero {
  position: relative;
  overflow: hidden;
  border: 1px solid var(--line);
  background:
    linear-gradient(135deg, rgba(23,32,51,.96), rgba(28,58,92,.94)),
    radial-gradient(circle at 85% 20%, rgba(24,166,166,.20), transparent 30%);
  border-radius: 8px;
  padding: 1.45rem 1.5rem;
  margin-bottom: 1.05rem;
  color: #ffffff;
}

.hero:after {
  content: "";
  position: absolute;
  inset: auto -70px -110px auto;
  width: 360px;
  height: 360px;
  border: 1px solid rgba(255,255,255,.13);
  border-radius: 50%;
}

.hero-eyebrow {
  color: rgba(255,255,255,.70);
  font-size: .78rem;
  font-weight: 700;
  letter-spacing: .11rem;
  text-transform: uppercase;
  margin-bottom: .5rem;
}

.hero-title {
  color: #ffffff;
  font-size: clamp(1.7rem, 2.4vw, 2.55rem);
  line-height: 1.04;
  font-weight: 800;
  letter-spacing: 0;
  max-width: 820px;
  margin: 0;
}

.hero-copy {
  color: rgba(255,255,255,.76);
  margin: .75rem 0 0;
  max-width: 920px;
  font-size: .98rem;
}

.section-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: .75rem;
  margin: .35rem 0 .75rem;
}

.section-title h2 {
  font-size: 1.08rem;
  margin: 0;
}

.section-title p {
  color: var(--muted);
  margin: .15rem 0 0;
  font-size: .9rem;
}

.metric-card {
  min-height: 118px;
  border: 1px solid var(--line);
  background: var(--surface);
  border-radius: 8px;
  padding: 1rem;
  box-shadow: 0 10px 28px rgba(15, 23, 42, .055);
}

.metric-label {
  color: var(--muted);
  font-size: .78rem;
  font-weight: 700;
  letter-spacing: .035rem;
  text-transform: uppercase;
  white-space: normal;
}

.metric-value {
  color: var(--ink);
  font-size: 1.62rem;
  line-height: 1.1;
  font-weight: 800;
  margin-top: .52rem;
  overflow-wrap: anywhere;
}

.metric-note {
  color: var(--muted);
  font-size: .82rem;
  margin-top: .36rem;
  overflow-wrap: anywhere;
}

.panel {
  border: 1px solid var(--line);
  background: var(--surface);
  border-radius: 8px;
  padding: 1rem;
  box-shadow: 0 10px 28px rgba(15, 23, 42, .045);
}

.panel.slim {
  padding: .85rem;
}

.status-row {
  display: flex;
  flex-wrap: wrap;
  gap: .5rem;
  margin: .75rem 0 1rem;
}

.pill {
  display: inline-flex;
  align-items: center;
  gap: .35rem;
  border-radius: 999px;
  padding: .36rem .62rem;
  font-size: .78rem;
  font-weight: 750;
  border: 1px solid transparent;
}

.pill.ok {
  color: #176b49;
  background: rgba(34,160,107,.12);
  border-color: rgba(34,160,107,.22);
}

.pill.warn {
  color: #995c1c;
  background: rgba(217,130,43,.14);
  border-color: rgba(217,130,43,.24);
}

.pill.info {
  color: #254fb8;
  background: rgba(47,109,246,.12);
  border-color: rgba(47,109,246,.22);
}

.sidebar-brand {
  border-bottom: 1px solid rgba(255,255,255,.12);
  padding-bottom: 1rem;
  margin-bottom: 1rem;
}

.sidebar-brand .name {
  color: #ffffff;
  font-size: 1.05rem;
  font-weight: 800;
  line-height: 1.2;
}

.sidebar-brand .sub {
  color: rgba(248,250,252,.66);
  font-size: .84rem;
  margin-top: .35rem;
}

.sidebar-stat {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: .75rem;
  padding: .62rem 0;
  border-bottom: 1px solid rgba(255,255,255,.08);
}

.sidebar-stat span {
  color: rgba(248,250,252,.62);
  font-size: .8rem;
}

.sidebar-stat strong {
  color: #ffffff;
  font-size: .88rem;
}

div[data-testid="stMetric"] {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: .85rem .9rem;
  background: #ffffff;
  box-shadow: 0 8px 22px rgba(15, 23, 42, .04);
}

div[data-testid="stMetricLabel"] {
  color: var(--muted);
  font-weight: 700;
}

div[data-testid="stTabs"] button {
  border-radius: 7px 7px 0 0;
  font-weight: 700;
}

.stDataFrame {
  border: 1px solid var(--line);
  border-radius: 8px;
  overflow: hidden;
}

.stAlert {
  border-radius: 8px;
}

button[kind="primary"] {
  border-radius: 8px;
  font-weight: 750;
}

@media (max-width: 820px) {
  .block-container {
    padding-left: 1rem;
    padding-right: 1rem;
  }
  .metric-card {
    min-height: auto;
  }
}
</style>
""",
    unsafe_allow_html=True,
)


def read_processed(name: str) -> pd.DataFrame:
    path = PROCESSED / name
    if not path.exists():
        return pd.DataFrame()
    return pd.read_excel(path)


def safe_sum(df: pd.DataFrame, col: str) -> float:
    if col not in df.columns:
        return 0.0
    return float(pd.to_numeric(df[col], errors="coerce").fillna(0).sum())


def safe_nunique(df: pd.DataFrame, col: str) -> int:
    if df.empty or col not in df.columns:
        return 0
    return int(df[col].dropna().astype(str).nunique())


def fmt_num(value, decimals: int = 0, suffix: str = "") -> str:
    try:
        n = float(value)
    except Exception:
        return "Not available"
    if pd.isna(n):
        return "Not available"
    if decimals == 0:
        text = f"{n:,.0f}"
    else:
        text = f"{n:,.{decimals}f}"
    return f"{text}{suffix}"


def fmt_duration(seconds: float) -> str:
    seconds = max(float(seconds or 0), 0.0)
    days = int(seconds // 86400)
    seconds %= 86400
    hours = int(seconds // 3600)
    seconds %= 3600
    minutes = int(seconds // 60)
    if days:
        return f"{days}d {hours:02d}h {minutes:02d}m"
    return f"{hours:02d}h {minutes:02d}m"


def metric_card(label: str, value, note: str = ""):
    st.markdown(
        f"""
<div class="metric-card">
  <div class="metric-label">{escape(str(label))}</div>
  <div class="metric-value">{escape(str(value))}</div>
  <div class="metric-note">{escape(str(note))}</div>
</div>
""",
        unsafe_allow_html=True,
    )


def section(title: str, caption: str = ""):
    st.markdown(
        f"""
<div class="section-title">
  <div>
    <h2>{escape(title)}</h2>
    <p>{escape(caption)}</p>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def status_pill(label: str, state: str = "info"):
    st.markdown(
        f'<span class="pill {escape(state)}">{escape(label)}</span>',
        unsafe_allow_html=True,
    )


def display_table(frame: pd.DataFrame, *, hide_index: bool = True):
    table = frame.copy()
    for col in table.columns:
        if table[col].dtype == "object":
            table[col] = table[col].map(lambda value: "" if pd.isna(value) else str(value))
    st.dataframe(table, width="stretch", hide_index=hide_index)


def tune_fig(fig: go.Figure, height: int = 420, show_legend: bool = True) -> go.Figure:
    fig.update_layout(
        template=PLOT_TEMPLATE,
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=34, b=10),
        font=dict(family="Inter, system-ui, -apple-system, BlinkMacSystemFont, sans-serif", color=INK),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        showlegend=show_legend,
    )
    fig.update_xaxes(showgrid=False, zeroline=False)
    fig.update_yaxes(gridcolor="#e6edf7", zeroline=False)
    return fig


def event_summary(label: str, df: pd.DataFrame, color: str) -> pd.DataFrame:
    if df.empty or "Satellite Name" not in df.columns:
        return pd.DataFrame(columns=["Satellite Name", "Events", "Data Type", "Color"])
    out = df.groupby("Satellite Name").size().reset_index(name="Events")
    out["Data Type"] = label
    out["Color"] = color
    return out


def prepare_latest_state(state_df: pd.DataFrame) -> tuple[pd.DataFrame, object]:
    if state_df.empty or "Timestamp" not in state_df.columns:
        return pd.DataFrame(), pd.NaT
    state_work = state_df.copy()
    state_work["Timestamp"] = pd.to_datetime(state_work["Timestamp"], errors="coerce")
    latest_time = state_work["Timestamp"].max()
    if pd.isna(latest_time):
        return pd.DataFrame(), pd.NaT
    return state_work[state_work["Timestamp"].eq(latest_time)].copy(), latest_time


@st.cache_data(show_spinner=False)
def load_processed_data():
    return {
        "rf": read_processed("RF_Contacts.xlsx"),
        "optical": read_processed("Optical_Contacts.xlsx"),
        "eclipse": read_processed("All_Eclipse_Events.xlsx"),
        "state": read_processed("Satellite_State_History.xlsx"),
    }


@st.cache_data(show_spinner=False)
def cached_coverage(state_df: pd.DataFrame, swath_km: float, resolution_deg: float):
    return cumulative_australia_coverage(state_df, swath_km, resolution_deg=resolution_deg)


@st.cache_data(show_spinner=False)
def cached_observation(state_df: pd.DataFrame, swath_km: float):
    return observation_duration_analysis(state_df, swath_km)


try:
    config = load_mission_configuration(BASE)
except Exception as exc:
    st.error("Mission configuration could not be loaded.")
    st.exception(exc)
    st.stop()

data = load_processed_data()
rf = data["rf"]
optical = data["optical"]
eclipse = data["eclipse"]
state = data["state"]

mission = config["mission"]
constellation = config["constellation"]
orbit = config["orbit"]
payload_cfg = config.get("payload", {}) if isinstance(config.get("payload", {}), dict) else {}

mission_name = str(mission.get("Mission Name", "Mission"))
mission_type = str(mission.get("Mission Type", "Not configured"))
aoi = str(mission.get("Area of Interest", "Not configured"))
configured_sats = int(float(constellation.get("Total Satellites", 0) or 0))
planes = int(float(constellation.get("Number of Planes", 0) or 0))
sats_per_plane = int(float(constellation.get("Satellites per Plane", 0) or 0))
altitude = orbit.get("Altitude", "Not configured")
inclination = orbit.get("Inclination", "Not configured")

detected_satellites = set()
for frame in (rf, optical, eclipse, state):
    if not frame.empty and "Satellite Name" in frame.columns:
        detected_satellites.update(frame["Satellite Name"].dropna().astype(str).unique())
detected_count = len(detected_satellites)

camera_model = build_camera_model(altitude, payload_cfg)
if not state.empty and "Satellite Name" in state.columns:
    camera_satellites = sorted(state["Satellite Name"].dropna().astype(str).unique())
else:
    camera_satellites = [f"SAT_{i:03d}" for i in range(1, configured_sats + 1)]
camera_modules = build_camera_modules(camera_satellites, camera_model)

latest_state, latest_epoch = prepare_latest_state(state)
fleet_pct = (detected_count / configured_sats * 100.0) if configured_sats else 0.0
total_rf_seconds = safe_sum(rf, "Duration (s)")
total_optical_seconds = safe_sum(optical, "Duration (s)")
total_eclipse_seconds = safe_sum(eclipse, "Duration (s)")


with st.sidebar:
    st.markdown(
        f"""
<div class="sidebar-brand">
  <div class="name">{escape(mission_name)}</div>
  <div class="sub">Mission Operations Center</div>
</div>
""",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
<div class="sidebar-stat"><span>Mission Type</span><strong>{escape(mission_type)}</strong></div>
<div class="sidebar-stat"><span>Area of Interest</span><strong>{escape(aoi)}</strong></div>
<div class="sidebar-stat"><span>Constellation</span><strong>{planes} x {sats_per_plane}</strong></div>
<div class="sidebar-stat"><span>Configured Fleet</span><strong>{configured_sats}</strong></div>
<div class="sidebar-stat"><span>Detected Fleet</span><strong>{detected_count}</strong></div>
<div class="sidebar-stat"><span>Altitude</span><strong>{escape(str(altitude))} km</strong></div>
<div class="sidebar-stat"><span>Inclination</span><strong>{escape(str(inclination))} deg</strong></div>
""",
        unsafe_allow_html=True,
    )
    st.write("")
    if st.button("Refresh GMAT data", type="primary", width="stretch"):
        try:
            result = run_pipeline(BASE)
            load_processed_data.clear()
            cached_coverage.clear()
            cached_observation.clear()
            st.success(
                "Pipeline refreshed: "
                f"{result.get('rf_events', 0)} RF, "
                f"{result.get('optical_events', 0)} optical, "
                f"{result.get('eclipse_rows', 0)} eclipse rows, "
                f"{result.get('state_rows', 0)} state rows."
            )
            st.rerun()
        except Exception as exc:
            st.exception(exc)
    st.caption("Source: config/Mission_Configuration.xlsx")


st.markdown(
    f"""
<div class="hero">
  <div class="hero-eyebrow">Configuration-driven GMAT analytics</div>
  <div class="hero-title">{escape(mission_name)} Mission Operations Center</div>
  <div class="hero-copy">
    Live operational view for constellation state, communications windows, eclipse exposure,
    Australia observation coverage, payload duty cycle, and onboard data generation.
  </div>
</div>
""",
    unsafe_allow_html=True,
)

issues = validate_configuration(config)
if issues:
    for issue in issues:
        st.warning(issue)

cols = st.columns(5)
with cols[0]:
    metric_card("Configured Satellites", configured_sats, f"{planes} orbital planes")
with cols[1]:
    metric_card("Detected in Data", detected_count, f"{fleet_pct:.1f}% of configured fleet")
with cols[2]:
    metric_card("State Samples", f"{len(state):,}", f"{safe_nunique(state, 'Satellite Name')} satellites")
with cols[3]:
    metric_card("Camera Swath", fmt_num(camera_model["Ground Swath (km)"], 2, " km"), "modeled ground width")
with cols[4]:
    latest_text = latest_epoch.strftime("%d %b %Y %H:%M") if pd.notna(latest_epoch) else "Not available"
    metric_card("Latest Epoch", latest_text, "from state history")

st.markdown('<div class="status-row">', unsafe_allow_html=True)
scols = st.columns(4)
with scols[0]:
    status_pill(f"RF contacts: {len(rf):,} rows", "ok" if not rf.empty else "warn")
with scols[1]:
    status_pill(f"Optical contacts: {len(optical):,} rows", "ok" if not optical.empty else "warn")
with scols[2]:
    status_pill(f"Eclipse events: {len(eclipse):,} rows", "ok" if not eclipse.empty else "warn")
with scols[3]:
    status_pill(f"State history: {len(state):,} rows", "ok" if not state.empty else "warn")
st.markdown("</div>", unsafe_allow_html=True)


overview_tab, fleet_tab, duty_tab, camera_tab, coverage_tab, k3_tab, config_tab, data_tab = st.tabs(
    [
        "Overview",
        "Fleet Ops",
        "Duty Cycle",
        "Payload",
        "Coverage",
        "Data Storage",
        "Configuration",
        "Processed Data",
    ]
)


with overview_tab:
    section("Mission Snapshot", "Top-level operational volume and data health.")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("RF Contact Events", f"{len(rf):,}", fmt_duration(total_rf_seconds))
    k2.metric("Optical Contact Events", f"{len(optical):,}", fmt_duration(total_optical_seconds))
    k3.metric("Eclipse Events", f"{len(eclipse):,}", fmt_duration(total_eclipse_seconds))
    k4.metric("Fleet Data Coverage", f"{fleet_pct:.1f}%", f"{detected_count} detected")

    left, right = st.columns([1.08, 1])
    with left:
        section("Events by Satellite", "RF, optical, and eclipse rows grouped by spacecraft.")
        frames = [
            event_summary("RF", rf, ACCENT),
            event_summary("Optical", optical, GREEN),
            event_summary("Eclipse", eclipse, AMBER),
        ]
        sat_events = pd.concat([f for f in frames if not f.empty], ignore_index=True)
        if sat_events.empty:
            st.info("No event data is available.")
        else:
            fig = px.bar(
                sat_events,
                x="Satellite Name",
                y="Events",
                color="Data Type",
                color_discrete_map={"RF": ACCENT, "Optical": GREEN, "Eclipse": AMBER},
                barmode="group",
            )
            fig.update_layout(xaxis_tickangle=-55)
            st.plotly_chart(tune_fig(fig, 450), width="stretch")

    with right:
        section("Operational Mix", "Communication events and eclipse type distribution.")
        comm = pd.DataFrame(
            {
                "Link Type": ["RF", "Optical"],
                "Events": [len(rf), len(optical)],
            }
        )
        fig = px.bar(
            comm,
            x="Link Type",
            y="Events",
            text="Events",
            color="Link Type",
            color_discrete_map={"RF": ACCENT, "Optical": GREEN},
        )
        fig.update_traces(textposition="outside", cliponaxis=False)
        st.plotly_chart(tune_fig(fig, 250, show_legend=False), width="stretch")

        if not eclipse.empty and "Eclipse Type" in eclipse.columns:
            ec = eclipse["Eclipse Type"].fillna("Unknown").value_counts().reset_index()
            ec.columns = ["Eclipse Type", "Events"]
            fig = px.pie(
                ec,
                names="Eclipse Type",
                values="Events",
                hole=0.58,
                color_discrete_sequence=[ACCENT, AMBER, RED, GREEN],
            )
            fig.update_traces(textposition="inside", textinfo="percent+label")
            st.plotly_chart(tune_fig(fig, 250), width="stretch")
        else:
            st.info("No eclipse type data is available.")

    section("Dataset Readiness", "Processed GMAT data loaded from data/processed.")
    d1, d2, d3, d4 = st.columns(4)
    d1.metric("RF Rows", f"{len(rf):,}")
    d2.metric("Optical Rows", f"{len(optical):,}")
    d3.metric("Eclipse Rows", f"{len(eclipse):,}")
    d4.metric("State Rows", f"{len(state):,}")


with fleet_tab:
    section("Constellation Operations", "Latest state, orbit quality, and per-satellite history.")
    if state.empty:
        st.warning("No processed StateReport data is available. Use Refresh GMAT data after raw data is present.")
    else:
        state_work = state.copy()
        state_work["Timestamp"] = pd.to_datetime(state_work["Timestamp"], errors="coerce")
        latest = latest_state.copy()
        if "Altitude" in latest.columns:
            latest["Altitude"] = pd.to_numeric(latest["Altitude"], errors="coerce")
        if "ECC" in latest.columns:
            latest["ECC"] = pd.to_numeric(latest["ECC"], errors="coerce")

        a, b, c, d, e = st.columns(5)
        a.metric("Satellites Detected", safe_nunique(state_work, "Satellite Name"))
        b.metric("State Samples", f"{len(state_work):,}")
        c.metric("Latest Epoch", latest_epoch.strftime("%d %b %Y %H:%M:%S") if pd.notna(latest_epoch) else "Not available")
        d.metric("Mean Altitude", fmt_num(latest.get("Altitude", pd.Series(dtype=float)).mean(), 2, " km") if "Altitude" in latest else "Not available")
        e.metric("Mean Eccentricity", fmt_num(latest.get("ECC", pd.Series(dtype=float)).mean(), 6) if "ECC" in latest else "Not available")

        left, right = st.columns([1.05, 1])
        with left:
            section("Latest Fleet Position")
            if {"Latitude", "Longitude"}.issubset(latest.columns):
                fig = px.scatter_geo(
                    latest,
                    lat="Latitude",
                    lon="Longitude",
                    hover_name="Satellite Name",
                    color_discrete_sequence=[ACCENT],
                    projection="natural earth",
                )
                fig.update_traces(marker=dict(size=8, line=dict(width=1, color="#ffffff")))
                fig.update_geos(showland=True, landcolor="#eef3fb", showcountries=True, coastlinecolor="#94a3b8")
                st.plotly_chart(tune_fig(fig, 470, show_legend=False), width="stretch")
            else:
                st.info("Latitude and longitude columns are not available.")

        with right:
            section("Latest Altitude")
            if "Altitude" in latest.columns:
                fig = px.bar(
                    latest.sort_values("Satellite Name"),
                    x="Satellite Name",
                    y="Altitude",
                    color_discrete_sequence=[GREEN],
                )
                fig.update_layout(xaxis_tickangle=-60, yaxis_title="Altitude (km)")
                st.plotly_chart(tune_fig(fig, 470, show_legend=False), width="stretch")
            else:
                st.info("Altitude column is not available.")

        section("Satellite State Explorer")
        satellites = sorted(state_work["Satellite Name"].dropna().astype(str).unique())
        selected_sat = st.selectbox("Satellite", satellites, key="fleet_sat")
        sat_df = state_work[state_work["Satellite Name"].astype(str).eq(selected_sat)].sort_values("Timestamp")
        if "Altitude" in sat_df.columns:
            sat_df["Altitude"] = pd.to_numeric(sat_df["Altitude"], errors="coerce")
            fig = px.line(sat_df, x="Timestamp", y="Altitude", color_discrete_sequence=[ACCENT])
            st.plotly_chart(tune_fig(fig, 330, show_legend=False), width="stretch")
        display_table(sat_df.tail(250).sort_values("Timestamp", ascending=False))


with duty_tab:
    section("Payload Duty Cycle", "Payload ON/OFF is derived from modeled camera swath over Australia.")
    if state.empty:
        st.warning("No StateReport data is available.")
    else:
        duty = state.copy()
        duty["Timestamp"] = pd.to_datetime(duty["Timestamp"], errors="coerce")
        duty["Latitude"] = pd.to_numeric(duty["Latitude"], errors="coerce")
        duty["Longitude"] = pd.to_numeric(duty["Longitude"], errors="coerce")
        duty = duty.dropna(subset=["Timestamp", "Satellite Name", "Latitude", "Longitude"])
        camera_swath_km = float(camera_model["Ground Swath (km)"])
        duty["Footprint Intersects Australia"] = footprint_intersects_australia(
            duty,
            camera_swath_km,
            lon_col="Longitude",
            lat_col="Latitude",
        )
        duty["Payload State"] = duty["Footprint Intersects Australia"].map({True: "ON", False: "OFF"})
        duty = duty.sort_values(["Satellite Name", "Timestamp"])
        steps = duty.groupby("Satellite Name")["Timestamp"].diff().dt.total_seconds()
        nominal_step = steps[(steps > 0) & (steps < 3600)].median()
        nominal_step = float(nominal_step) if pd.notna(nominal_step) else 0.0
        duty["Sample Duration (s)"] = nominal_step
        duty["AOI Active Duration (s)"] = duty["Sample Duration (s)"].where(duty["Payload State"].eq("ON"), 0.0)

        duty["In Eclipse"] = False
        if not eclipse.empty and {"Satellite Name", "Start UTC", "Stop UTC"}.issubset(eclipse.columns):
            ec = eclipse[["Satellite Name", "Start UTC", "Stop UTC"]].copy()
            ec["Start UTC"] = pd.to_datetime(ec["Start UTC"], errors="coerce")
            ec["Stop UTC"] = pd.to_datetime(ec["Stop UTC"], errors="coerce")
            ec = ec.dropna()
            for sat_name, intervals in ec.groupby("Satellite Name"):
                sat_mask = duty["Satellite Name"].eq(sat_name)
                if not sat_mask.any():
                    continue
                timestamps = duty.loc[sat_mask, "Timestamp"]
                in_eclipse = pd.Series(False, index=timestamps.index)
                for start, stop in intervals[["Start UTC", "Stop UTC"]].itertuples(index=False, name=None):
                    in_eclipse |= timestamps.between(start, stop)
                duty.loc[in_eclipse.index, "In Eclipse"] = in_eclipse.values

        duty["AOI + Eclipse"] = duty["Payload State"].eq("ON") & duty["In Eclipse"]
        total_samples = len(duty)
        on_samples = int(duty["Payload State"].eq("ON").sum())
        on_hours = duty["AOI Active Duration (s)"].sum() / 3600.0
        duty_pct = (100.0 * on_samples / total_samples) if total_samples else 0.0
        overlap_hours = duty.loc[duty["AOI + Eclipse"], "Sample Duration (s)"].sum() / 3600.0

        a, b, c, d, e = st.columns(5)
        a.metric("Fleet Payload ON Time", f"{on_hours:.2f} h")
        b.metric("Fleet Duty Cycle", f"{duty_pct:.2f}%")
        c.metric("AOI Samples", f"{on_samples:,}")
        d.metric("AOI + Eclipse", f"{overlap_hours:.2f} h")
        e.metric("Report Cadence", f"{nominal_step:.0f} s" if nominal_step else "Not available")

        summary = duty.groupby("Satellite Name", as_index=False).agg(
            Samples=("Timestamp", "size"),
            AOI_Samples=("Payload State", lambda x: (x == "ON").sum()),
            Active_Duration_s=("AOI Active Duration (s)", "sum"),
            Eclipse_Overlap_Samples=("AOI + Eclipse", "sum"),
        )
        summary["Active Duration (min)"] = summary["Active_Duration_s"] / 60.0
        summary["Duty Cycle (%)"] = 100.0 * summary["AOI_Samples"] / summary["Samples"]
        summary["AOI + Eclipse (min)"] = summary["Eclipse_Overlap_Samples"] * nominal_step / 60.0

        left, right = st.columns(2)
        with left:
            section("Payload Active Time")
            fig = px.bar(summary, x="Satellite Name", y="Active Duration (min)", color_discrete_sequence=[ACCENT])
            fig.update_layout(xaxis_tickangle=-60)
            st.plotly_chart(tune_fig(fig, 410, show_legend=False), width="stretch")
        with right:
            section("Duty Cycle by Satellite")
            fig = px.bar(summary, x="Satellite Name", y="Duty Cycle (%)", color_discrete_sequence=[GREEN])
            fig.update_layout(xaxis_tickangle=-60)
            st.plotly_chart(tune_fig(fig, 410, show_legend=False), width="stretch")

        section("Timeline Explorer")
        selected_k2 = st.selectbox("Satellite", sorted(duty["Satellite Name"].astype(str).unique()), key="k2_sat")
        sat_k2 = duty[duty["Satellite Name"].astype(str).eq(selected_k2)].copy()
        fig = px.scatter(
            sat_k2,
            x="Timestamp",
            y="Latitude",
            color="Payload State",
            hover_data=["Longitude", "In Eclipse"],
            color_discrete_map={"ON": GREEN, "OFF": "#94a3b8"},
        )
        st.plotly_chart(tune_fig(fig, 360), width="stretch")

        display_table(summary.drop(columns=["Active_Duration_s", "Eclipse_Overlap_Samples"]))


with camera_tab:
    section("Camera and Payload", "Dynamic payload model assigned across the detected constellation.")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Camera Modules", f"{len(camera_modules):,}")
    c2.metric("HFOV", f"{camera_model['HFOV (deg)']:.2f} deg")
    c3.metric("Ground Swath", f"{camera_model['Ground Swath (km)']:.2f} km")
    c4.metric("GSD", f"{camera_model['GSD (m/pixel)']:.2f} m/pixel")
    c5.metric("Pointing", str(camera_model["Pointing"]))

    left, right = st.columns([.85, 1.15])
    with left:
        section("Camera Configuration")
        display_cfg = pd.DataFrame(
            {
                "Parameter": list(camera_model.keys()),
                "Value": [
                    ", ".join(v) if isinstance(v, list) else v
                    for v in camera_model.values()
                ],
            }
        )
        display_table(display_cfg)
    with right:
        section("Constellation Assignment")
        display_cols = [
            "Satellite Name",
            "Camera Name",
            "Camera Type",
            "Ground Swath (km)",
            "GSD (m/pixel)",
            "Pointing",
        ]
        display_table(camera_modules[display_cols])


with coverage_tab:
    section("Australia Cumulative Coverage", "Grid-based engineering estimate over the available GMAT simulation.")
    if state.empty:
        st.warning("No StateReport data is available.")
    else:
        control_col, note_col = st.columns([.32, .68])
        with control_col:
            resolution_deg = st.selectbox(
                "Grid resolution",
                [1.0, 0.5, 0.25],
                index=1,
                format_func=lambda x: f"{x} deg grid",
            )
        with note_col:
            st.info("Coverage uses available state samples, modeled camera swath, and an Australia boundary approximation.")

        with st.spinner("Calculating cumulative coverage..."):
            coverage_grid, coverage_contrib, coverage_pct = cached_coverage(
                state,
                float(camera_model["Ground Swath (km)"]),
                float(resolution_deg),
            )

        covered_cells = int(coverage_grid["Covered"].sum()) if not coverage_grid.empty else 0
        total_cells = int(len(coverage_grid))
        uncovered_cells = total_cells - covered_cells
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Coverage", f"{coverage_pct:.2f}%")
        c2.metric("Covered Cells", f"{covered_cells:,}")
        c3.metric("Uncovered Cells", f"{uncovered_cells:,}")
        c4.metric("Modeled Swath", f"{camera_model['Ground Swath (km)']:.2f} km")

        map_df = coverage_grid.copy()
        map_df["Coverage Status"] = map_df["Covered"].map({True: "Covered", False: "Uncovered"})
        fig = px.scatter_geo(
            map_df,
            lat="Latitude",
            lon="Longitude",
            color="Coverage Status",
            hover_data=["Latitude", "Longitude"],
            color_discrete_map={"Covered": GREEN, "Uncovered": RED},
            scope="world",
        )
        fig.update_traces(marker=dict(size=5, opacity=.78))
        fig.update_geos(
            projection_type="equirectangular",
            lataxis_range=[-46, -8],
            lonaxis_range=[110, 156],
            showland=True,
            landcolor="#eef3fb",
            showcountries=True,
            coastlinecolor="#94a3b8",
        )
        st.plotly_chart(tune_fig(fig, 610), width="stretch")

        left, right = st.columns([.52, .48])
        with left:
            section("Satellite Contribution")
            if not coverage_contrib.empty:
                fig = px.bar(
                    coverage_contrib.head(20),
                    x="Satellite Name",
                    y="Covered Cell Centers",
                    color_discrete_sequence=[ACCENT],
                )
                fig.update_layout(xaxis_tickangle=-60)
                st.plotly_chart(tune_fig(fig, 340, show_legend=False), width="stretch")
            else:
                st.info("No contribution data is available.")
        with right:
            section("Observation Summary")
            per_sat_obs, observation_windows, overall_obs, observation_timeline = cached_observation(
                state,
                float(camera_model["Ground Swath (km)"]),
            )
            o1, o2 = st.columns(2)
            o1.metric("Analysis Duration", overall_obs.get("Simulation Analysis Duration", "00h 00m 00s"))
            o2.metric("Max Simultaneous", overall_obs.get("Maximum Simultaneous Observing Satellites", 0))
            o3, o4 = st.columns(2)
            o3.metric("Unique Observed", overall_obs.get("Unique Constellation Observation Time", "00h 00m 00s"))
            o4.metric("Duty Cycle", f"{overall_obs.get('Overall Observation Duty Cycle (%)', 0):.2f}%")

        if not per_sat_obs.empty:
            section("Observation Duration by Satellite")
            chart_obs = per_sat_obs.copy()
            chart_obs["Total Observation Time (h)"] = chart_obs["Total Observation Seconds"] / 3600.0
            fig = px.bar(
                chart_obs,
                x="Satellite Name",
                y="Total Observation Time (h)",
                hover_data=["Observation Windows", "Average Window", "Longest Window", "Observation Duty Cycle (%)"],
                color_discrete_sequence=[GREEN],
            )
            fig.update_layout(xaxis_tickangle=-60)
            st.plotly_chart(tune_fig(fig, 430, show_legend=False), width="stretch")
            display_table(per_sat_obs.drop(columns=["Total Observation Seconds"]))

        if not observation_windows.empty:
            with st.expander("Observation windows"):
                windows_display = observation_windows.copy()
                windows_display["Observation Duration"] = windows_display["Observation Duration (s)"].map(
                    lambda s: f"{int(s // 3600):02d}h {int((s % 3600) // 60):02d}m {int(s % 60):02d}s"
                )
                display_table(windows_display.drop(columns=["Observation Duration (s)"]))


with k3_tab:
    section("Payload Data and Onboard Storage", "Pushbroom acquisition model linked to Australia observation time.")
    if "k3_config" not in st.session_state:
        st.session_state.k3_config = default_k3_config()

    known = pd.DataFrame(
        [
            {
                "Parameter": "Cross-track detector pixels",
                "Value": camera_model.get("Image Width (px)"),
                "Unit": "pixels",
                "Source": "Camera module",
            },
            {
                "Parameter": "Active spectral bands",
                "Value": len(camera_model.get("Spectral Bands", [])),
                "Unit": "bands",
                "Source": "Camera module",
            },
            {
                "Parameter": "Spectral bands",
                "Value": ", ".join(camera_model.get("Spectral Bands", [])),
                "Unit": "",
                "Source": "Camera module",
            },
        ]
    )
    display_table(known)

    input_left, input_right = st.columns(2)
    with input_left:
        bpp = st.number_input(
            "Bits per pixel",
            min_value=1.0,
            max_value=32.0,
            value=float(st.session_state.k3_config.get("Bits per Pixel") or 12.0),
            step=1.0,
        )
        gsd = st.number_input(
            "Along-track GSD (m)",
            min_value=0.0,
            value=float(st.session_state.k3_config.get("Along-track GSD (m)") or 0.0),
            step=0.1,
        )
    with input_right:
        compression = st.number_input(
            "Compression ratio (raw : compressed)",
            min_value=0.0,
            value=float(st.session_state.k3_config.get("Compression Ratio") or 0.0),
            step=0.1,
        )
        storage = st.number_input(
            "Onboard storage capacity (GB)",
            min_value=0.0,
            value=float(st.session_state.k3_config.get("Onboard Storage Capacity") or 0.0),
            step=1.0,
        )
        processing = st.number_input(
            "Processing rate (Mbps)",
            min_value=0.0,
            value=float(st.session_state.k3_config.get("Processing Rate") or 0.0),
            step=1.0,
        )

    st.session_state.k3_config = {
        "Bits per Pixel": bpp,
        "Along-track GSD (m)": gsd if gsd > 0 else None,
        "Compression Ratio": compression if compression > 0 else None,
        "Onboard Storage Capacity": storage if storage > 0 else None,
        "Processing Rate": processing if processing > 0 else None,
    }

    ground_speed_km_s = None
    try:
        speed_candidates = []
        if {"Satellite Name", "Timestamp", "X", "Y", "Z"}.issubset(state.columns):
            speed_df = state.copy()
            speed_df["Timestamp"] = pd.to_datetime(speed_df["Timestamp"], errors="coerce")
            for _, grp in speed_df.sort_values(["Satellite Name", "Timestamp"]).groupby("Satellite Name"):
                dt = grp["Timestamp"].diff().dt.total_seconds()
                dx = pd.to_numeric(grp["X"], errors="coerce").diff()
                dy = pd.to_numeric(grp["Y"], errors="coerce").diff()
                dz = pd.to_numeric(grp["Z"], errors="coerce").diff()
                velocity = ((dx * dx + dy * dy + dz * dz) ** 0.5) / dt
                speed_candidates.extend(velocity[(velocity > 0) & (velocity < 15)].dropna().tolist())
        if speed_candidates:
            ground_speed_km_s = float(pd.Series(speed_candidates).median())
    except Exception:
        ground_speed_km_s = None

    derived = derive_pushbroom_data_model(camera_model, st.session_state.k3_config, ground_speed_km_s)
    rows = [
        {
            "Parameter": "Ground speed",
            "Value": f"{derived['Ground Speed (km/s)']:.4f}" if derived["Ground Speed (km/s)"] else "Unavailable",
            "Unit": "km/s",
        },
        {
            "Parameter": "Line rate",
            "Value": f"{derived['Derived Line Rate (lines/s)']:.2f}" if derived["Derived Line Rate (lines/s)"] else "Awaiting GSD",
            "Unit": "lines/s",
        },
        {
            "Parameter": "Bits per line",
            "Value": f"{derived['Bits per Line']:,.0f}" if derived["Bits per Line"] else "Unavailable",
            "Unit": "bits/line",
        },
        {
            "Parameter": "Continuous raw data rate",
            "Value": f"{derived['Continuous Raw Data Rate (Mbps)']:,.2f}" if derived["Continuous Raw Data Rate (Mbps)"] else "Awaiting GSD",
            "Unit": "Mbps",
        },
    ]
    display_table(pd.DataFrame(rows))

    if state.empty:
        st.warning("No StateReport data is available.")
    else:
        per_sat, _, overall, _ = cached_observation(state, float(camera_model["Ground Swath (km)"]))
        results = calculate_k3_from_observation(per_sat, derived, st.session_state.k3_config)
        rate = derived["Continuous Raw Data Rate (Mbps)"]
        raw = pd.to_numeric(results["Raw Data Generated (GB)"], errors="coerce").sum(min_count=1)
        comp = pd.to_numeric(results["Compressed Data (GB)"], errors="coerce").sum(min_count=1)

        a, b, c, d = st.columns(4)
        a.metric("Observed Fleet Time", overall.get("Summed Satellite Observation Time", "00h 00m 00s"))
        b.metric("Raw Data Rate", f"{rate:,.2f} Mbps" if rate else "Awaiting GSD")
        c.metric("Raw Data Generated", f"{raw:,.2f} GB" if pd.notna(raw) else "Awaiting GSD")
        d.metric("Compressed Data", f"{comp:,.2f} GB" if pd.notna(comp) else "Awaiting compression")

        section("Per-Satellite K3 Results")
        display_cols = [
            "Satellite Name",
            "Total Observation Time",
            "Observation Windows",
            "Raw Data Generated (GB)",
            "Compressed Data (GB)",
            "Storage Utilization (%)",
            "Estimated Processing Time (s)",
        ]
        display_table(results[display_cols])


with config_tab:
    section("Loaded Mission Configuration", "Values read from config/Mission_Configuration.xlsx.")
    for title, key in [
        ("Mission", "mission_table"),
        ("Constellation", "constellation_table"),
        ("Orbit", "orbit_table"),
        ("Ground Stations", "ground_stations"),
        ("Payload", "payload_table"),
        ("Power", "power_table"),
    ]:
        with st.expander(title, expanded=title in ["Mission", "Constellation", "Orbit"]):
            display_table(config[key])


with data_tab:
    section("Processed GMAT Datasets", "Current processed Excel outputs.")
    for filename, frame in [
        ("RF_Contacts.xlsx", rf),
        ("Optical_Contacts.xlsx", optical),
        ("All_Eclipse_Events.xlsx", eclipse),
        ("Satellite_State_History.xlsx", state),
    ]:
        with st.expander(f"{filename} - {len(frame):,} rows", expanded=False):
            if frame.empty:
                st.info("No data available.")
            else:
                display_table(frame)
