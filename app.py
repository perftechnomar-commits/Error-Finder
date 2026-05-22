from __future__ import annotations

from io import BytesIO
import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
import altair as alt
import pandas as pd
import streamlit as st

from validator import DEFAULT_CONFIG, RULES, combine_results, results_to_excel_bytes, validate_excel_file

APP_BUILD = "AUTO_SOURCE_FLEET_FINAL_2026_05_21"

st.set_page_config(page_title="Noon Report Checker", page_icon="✅", layout="wide")

st.title("Noon Report Checker")


# -----------------------------------------------------------------------------
# General helpers
# -----------------------------------------------------------------------------

def parse_report_datetime(series: pd.Series) -> pd.Series:
    """Parse report datetimes robustly for filtering and KPI charts."""
    if series is None or series.empty:
        return pd.Series(dtype="datetime64[ns]")
    return pd.to_datetime(series, errors="coerce")


def with_report_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with report_datetime and report_date columns based on start_gmt."""
    out = df.copy()
    if "start_gmt" not in out.columns:
        out["report_datetime"] = pd.NaT
        out["report_date"] = pd.NaT
        return out
    out["report_datetime"] = parse_report_datetime(out["start_gmt"])
    out["report_date"] = out["report_datetime"].dt.date
    return out


def filter_last_report_days(errors_df: pd.DataFrame, days: int = 2) -> tuple[pd.DataFrame, list]:
    """Keep errors from the latest N report dates in the loaded data, not from today's date."""
    if errors_df.empty or "start_gmt" not in errors_df.columns:
        return errors_df.copy(), []
    dated = with_report_dates(errors_df)
    available_dates = sorted([d for d in dated["report_date"].dropna().unique().tolist()])
    last_dates = available_dates[-int(days):] if available_dates else []
    recent = dated[dated["report_date"].isin(last_dates)].copy()
    return recent, last_dates


def get_latest_report_dates(df: pd.DataFrame, days: int) -> list:
    """Return the latest N report dates from a dated dataframe."""
    if df.empty or "report_date" not in df.columns:
        return []
    available_dates = sorted([d for d in df["report_date"].dropna().unique().tolist()])
    return available_dates[-int(days):] if available_dates else []


def filter_to_report_dates(df: pd.DataFrame, report_dates: list) -> pd.DataFrame:
    """Filter a dated dataframe to selected report dates."""
    if df.empty or "report_date" not in df.columns:
        return df.copy()
    if not report_dates:
        return df.iloc[0:0].copy()
    return df[df["report_date"].isin(report_dates)].copy()


def build_daily_kpis(checked_rows: pd.DataFrame, errors_df: pd.DataFrame) -> pd.DataFrame:
    """Build daily operational validation KPIs."""
    if checked_rows.empty or "start_gmt" not in checked_rows.columns:
        return pd.DataFrame()

    rows = with_report_dates(checked_rows).dropna(subset=["report_date"]).copy()
    if rows.empty:
        return pd.DataFrame()

    daily_rows = (
        rows.groupby("report_date", dropna=False)
        .agg(
            report_rows=("excel_row", "count"),
            rows_with_errors=("issue_count", lambda s: int((s > 0).sum())),
            rows_ok=("issue_count", lambda s: int((s == 0).sum())),
        )
        .reset_index()
    )

    if errors_df.empty:
        daily_errors = pd.DataFrame({"report_date": daily_rows["report_date"], "total_errors": 0})
    else:
        err = with_report_dates(errors_df).dropna(subset=["report_date"])
        daily_errors = err.groupby("report_date", dropna=False).size().reset_index(name="total_errors")

    daily = daily_rows.merge(daily_errors, on="report_date", how="left")
    daily["total_errors"] = daily["total_errors"].fillna(0).astype(int)
    daily["error_row_rate"] = daily["rows_with_errors"] / daily["report_rows"].replace(0, pd.NA)
    daily["avg_errors_per_report"] = daily["total_errors"] / daily["report_rows"].replace(0, pd.NA)
    daily["report_date"] = daily["report_date"].astype(str)
    return daily.sort_values("report_date", ascending=False)


def pie_chart(df: pd.DataFrame, category: str, value: str, title: str) -> alt.Chart:
    base = df[[category, value]].dropna().copy()
    base = base[base[value] > 0]
    return (
        alt.Chart(base)
        .mark_arc(innerRadius=55)
        .encode(
            theta=alt.Theta(f"{value}:Q"),
            color=alt.Color(f"{category}:N"),
            tooltip=[alt.Tooltip(f"{category}:N", title=category), alt.Tooltip(f"{value}:Q", title=value)],
        )
        .properties(title=title, height=300)
    )


def display_error_table(title: str, df: pd.DataFrame) -> None:
    st.subheader(title)
    if df.empty:
        st.success("No validation errors found for this selection.")
        return

    preferred_cols = [
        "report_date",
        "file_name",
        "excel_row",
        "report_id",
        "ship_name",
        "report_type",
        "state_name",
        "issue_type",
        "severity",
        "message",
        "value",
        "expected",
        "columns",
    ]
    cols = [c for c in preferred_cols if c in df.columns]
    sort_cols = [c for c in ["report_date", "severity", "issue_type"] if c in df.columns]
    if sort_cols:
        df = df.sort_values(sort_cols, ascending=[False, True, True][: len(sort_cols)])
    st.dataframe(df[cols], use_container_width=True, hide_index=True)


# -----------------------------------------------------------------------------
# Department auto-source helpers
# -----------------------------------------------------------------------------

class MemoryUploadedFile:
    """Small uploaded-file-like wrapper so the existing validator can read auto-source bytes."""

    def __init__(self, name: str, data: bytes):
        self.name = name
        self._data = data

    def getvalue(self) -> bytes:
        return self._data


def make_sharepoint_download_url(url: str) -> str:
    """Convert a SharePoint/OneDrive web-view URL into a best-effort download URL."""
    parts = urlsplit(url.strip())
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.pop("web", None)
    query["download"] = "1"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


@st.cache_data(ttl=600, show_spinner=False)
def fetch_auto_source_file(source_url: str, refresh_token: int = 0) -> bytes:
    """Download the department Excel source. refresh_token is used to force cache refresh."""
    del refresh_token

    if not source_url or not source_url.strip():
        raise ValueError("AUTO_SOURCE_URL is missing from Streamlit secrets.")

    download_url = make_sharepoint_download_url(source_url)
    response = requests.get(
        download_url,
        timeout=90,
        allow_redirects=True,
        headers={
            "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/octet-stream,*/*",
            "User-Agent": "Mozilla/5.0",
        },
    )
    response.raise_for_status()

    content = response.content
    content_type = response.headers.get("Content-Type", "")

    # xlsx/xlsm files are ZIP containers and normally start with PK.
    # If SharePoint returns a login page/HTML, validation would fail later with a cryptic error.
    if not content.startswith(b"PK"):
        preview = content[:160].decode("utf-8", errors="ignore").replace("\n", " ").strip()
        raise ValueError(
            "The auto source did not return a downloadable Excel file. "
            "It may require SharePoint login, or the link is not a direct/anonymous download link. "
            f"Content-Type: {content_type}. Preview: {preview}"
        )

    return content


# -----------------------------------------------------------------------------
# Validation cache / dashboard rule-filter helpers
# -----------------------------------------------------------------------------

def build_source_signature(uploaded_files: list) -> tuple:
    """Create a robust signature so filters do not trigger revalidation, but source changes do."""
    signature = []
    for uploaded in uploaded_files:
        payload = uploaded.getvalue()
        payload_hash = hashlib.md5(payload).hexdigest()
        signature.append((uploaded.name, len(payload), payload_hash))
    return tuple(signature)


def build_config_signature(config: dict) -> tuple:
    """Validation thresholds signature. Display filters are intentionally excluded."""
    return tuple(sorted(config.items()))


def get_rule_name(rule: object) -> str:
    """Extract a stable display name from RULES entries."""
    if isinstance(rule, dict):
        for key in ("issue_type", "rule", "name", "id", "Rule", "Rule Name"):
            value = rule.get(key)
            if value is not None and str(value).strip():
                return str(value)
    return str(rule)


def get_rule_options() -> list[str]:
    return sorted(set(get_rule_name(rule) for rule in RULES if str(get_rule_name(rule)).strip()))


def rules_by_keywords(rule_options: list[str], keywords: list[str]) -> list[str]:
    out = []
    for rule in rule_options:
        text = rule.lower()
        if any(keyword in text for keyword in keywords):
            out.append(rule)
    return out


def rebuild_checked_rows_issue_counts(checked_rows_df: pd.DataFrame, errors_df: pd.DataFrame) -> pd.DataFrame:
    """Recalculate issue_count after validation rule scope is applied."""
    out = checked_rows_df.copy()
    if out.empty:
        return out

    keys = [c for c in ["file_name", "excel_row", "report_id", "ship_name"] if c in out.columns and c in errors_df.columns]
    if "raw_issue_count" not in out.columns and "issue_count" in out.columns:
        out["raw_issue_count"] = out["issue_count"]

    if not keys or errors_df.empty:
        out["issue_count"] = 0
        return out

    issue_counts = errors_df.groupby(keys, dropna=False).size().reset_index(name="display_issue_count")
    out = out.merge(issue_counts, on=keys, how="left")
    out["issue_count"] = out["display_issue_count"].fillna(0).astype(int)
    return out.drop(columns=["display_issue_count"])


def build_portfolio_summary(checked_rows_df: pd.DataFrame, errors_df: pd.DataFrame) -> pd.DataFrame:
    rows_total = len(checked_rows_df)
    rows_with_errors = int((checked_rows_df.get("issue_count", pd.Series(dtype=int)) > 0).sum()) if rows_total else 0
    rows_ok = int((checked_rows_df.get("issue_count", pd.Series(dtype=int)) == 0).sum()) if rows_total else 0
    files_checked = checked_rows_df["file_name"].nunique() if "file_name" in checked_rows_df.columns else 0
    return pd.DataFrame(
        [
            {"metric": "Files checked", "value": files_checked},
            {"metric": "Report rows", "value": rows_total},
            {"metric": "Rows with issues", "value": rows_with_errors},
            {"metric": "Rows OK", "value": rows_ok},
            {"metric": "Total issues", "value": len(errors_df)},
        ]
    )


def apply_rule_display_filter(combined_result: dict, selected_rules: list[str]) -> dict:
    """Apply the selected rule filter to displayed dashboard output only."""
    scoped = dict(combined_result)
    errors_raw = combined_result["errors"].copy()
    checked_rows_raw = combined_result["checked_rows"].copy()

    if selected_rules and not errors_raw.empty and "issue_type" in errors_raw.columns:
        errors = errors_raw[errors_raw["issue_type"].astype(str).isin(selected_rules)].copy()
    elif selected_rules:
        errors = errors_raw.copy()
    else:
        errors = errors_raw.iloc[0:0].copy()

    checked_rows = rebuild_checked_rows_issue_counts(checked_rows_raw, errors)
    by_rule = (
        errors.groupby("issue_type", dropna=False).size().reset_index(name="count")
        if not errors.empty and "issue_type" in errors.columns
        else pd.DataFrame(columns=["issue_type", "count"])
    )

    scoped["errors"] = errors
    scoped["checked_rows"] = checked_rows
    scoped["by_rule"] = by_rule
    scoped["portfolio_summary"] = build_portfolio_summary(checked_rows, errors)
    return scoped


def get_vessel_options(errors_df: pd.DataFrame, rows_df: pd.DataFrame) -> list[str]:
    values = []
    for df in (errors_df, rows_df):
        if not df.empty and "ship_name" in df.columns:
            values.extend(df["ship_name"].dropna().astype(str).unique().tolist())
    return sorted(set(v for v in values if v.strip()))


def apply_vessel_filter(df: pd.DataFrame, vessel_name: str) -> pd.DataFrame:
    if df.empty or "ship_name" not in df.columns or vessel_name == "All vessels":
        return df.copy()
    return df[df["ship_name"].astype(str).eq(vessel_name)].copy()


# -----------------------------------------------------------------------------
# Sidebar controls
# -----------------------------------------------------------------------------

with st.sidebar:
    st.header("Validation thresholds")

    config = DEFAULT_CONFIG.copy()
    recent_days = st.number_input(
        "Dashboard report days to show",
        min_value=1,
        max_value=5,
        value=5,
        step=1,
        help="Display filter only. It scopes the dashboard to the latest N report dates from the loaded file and does not rerun validation.",
    )

    with st.expander("Rule filter", expanded=True):
        rule_options = get_rule_options()
        default_rules = [rule for rule in rule_options if "sludge" not in rule.lower()]

        selected_rules = st.multiselect(
            "Rules to show",
            options=rule_options,
            default=default_rules,
            help="Display filter only. Validation runs all rules once; changing this updates the dashboard without rerunning validation.",
        )


    with st.expander("Sea passage / performance", expanded=True):
        config["low_steaming_hours"] = st.number_input("Low steaming below hours", value=float(DEFAULT_CONFIG["low_steaming_hours"]), step=0.5)
        config["slip_min"] = st.number_input("Slip min", value=float(DEFAULT_CONFIG["slip_min"]), step=0.01, format="%.2f")
        config["slip_max"] = st.number_input("Slip max", value=float(DEFAULT_CONFIG["slip_max"]), step=0.01, format="%.2f")
        config["me_load_min"] = st.number_input("ME Load min", value=float(DEFAULT_CONFIG["me_load_min"]), step=0.01, format="%.2f")
        config["me_load_max"] = st.number_input("ME Load max", value=float(DEFAULT_CONFIG["me_load_max"]), step=0.01, format="%.2f")

    with st.expander("Consumption / ROB", expanded=False):
        config["electric_load_min_kw"] = st.number_input("Electric load min kW", value=float(DEFAULT_CONFIG["electric_load_min_kw"]), step=50.0)
        config["electric_load_max_kw"] = st.number_input("Electric load max kW", value=float(DEFAULT_CONFIG["electric_load_max_kw"]), step=100.0)
        config["mgo_rob_min_mt"] = st.number_input("MGO ROB min MT", value=float(DEFAULT_CONFIG["mgo_rob_min_mt"]), step=5.0)
        config["boiler_cons_max_mt"] = st.number_input("Boiler cons max MT", value=float(DEFAULT_CONFIG["boiler_cons_max_mt"]), step=0.5)
        config["dg_cons_high_mt"] = st.number_input("DG cons high MT", value=float(DEFAULT_CONFIG["dg_cons_high_mt"]), step=0.5)
        config["dg_cons_low_mt"] = st.number_input("DG cons low MT", value=float(DEFAULT_CONFIG["dg_cons_low_mt"]), step=0.1)

    with st.expander("Advanced", expanded=False):
        config["sfoc_min"] = st.number_input("SFOC min", value=float(DEFAULT_CONFIG["sfoc_min"]), step=5.0)
        config["sfoc_max"] = st.number_input("SFOC max", value=float(DEFAULT_CONFIG["sfoc_max"]), step=5.0)
        config["torque_power_min_kw"] = st.number_input("Torque power min kW", value=float(DEFAULT_CONFIG["torque_power_min_kw"]), step=100.0)
        config["torque_power_max_kw"] = st.number_input("Torque power max kW", value=float(DEFAULT_CONFIG["torque_power_max_kw"]), step=100.0)
        config["difference_pct_avg_band"] = st.number_input("Consumption % average band", value=float(DEFAULT_CONFIG["difference_pct_avg_band"]), step=0.01, format="%.2f")
        config["distance_tolerance_pct"] = st.number_input("Distance tolerance %", value=float(DEFAULT_CONFIG["distance_tolerance_pct"]), step=0.01, format="%.2f")


# -----------------------------------------------------------------------------
# Data source
# -----------------------------------------------------------------------------

source_mode = st.radio(
    "Data source",
    ["Department auto source", "Manual upload"],
    index=0,
    horizontal=True,
    label_visibility="collapsed",
)

uploaded_files = []

if "auto_source_refresh_token" not in st.session_state:
    st.session_state["auto_source_refresh_token"] = 0

if source_mode == "Department auto source":
    auto_source_url = st.secrets.get("AUTO_SOURCE_URL", "")
    auto_source_file_name = st.secrets.get("AUTO_SOURCE_FILE_NAME", "All vessels.xlsx")

    reload_col, _ = st.columns([1, 4])
    if reload_col.button("Reload source file", use_container_width=True):
        st.session_state["auto_source_refresh_token"] += 1

    try:
        auto_payload = fetch_auto_source_file(
            auto_source_url,
            st.session_state["auto_source_refresh_token"],
        )
        uploaded_files = [MemoryUploadedFile(auto_source_file_name, auto_payload)]
    except Exception as exc:  # noqa: BLE001 - user-facing source error
        st.error(f"Department auto source could not be loaded: {exc}")
        st.info("Switch to Manual upload as backup, or update AUTO_SOURCE_URL in Streamlit Secrets.")
        st.stop()

else:
    uploaded_files = st.file_uploader(
        "Upload one or more Excel files",
        type=["xlsx", "xlsm"],
        accept_multiple_files=True,
        help="Use a Power Query refreshed file. For fleet mode, upload one unified Excel for all vessels.",
    )

    if not uploaded_files:
        st.stop()

with st.expander("Validation rules included", expanded=False):
    st.dataframe(pd.DataFrame(RULES), use_container_width=True, hide_index=True)


# -----------------------------------------------------------------------------
# Validation execution: run once, then dashboard filters are smooth
# -----------------------------------------------------------------------------

current_source_signature = build_source_signature(uploaded_files)
current_config_signature = build_config_signature(config)

for key, default in {
    "validation_combined": None,
    "validation_failed": [],
    "validation_source_signature": None,
    "validation_config_signature": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

run = st.button("Run validation", type="primary", use_container_width=True)

if run:
    all_results = []
    failed = []
    progress = st.progress(0, text="Starting validation...")

    for pos, uploaded in enumerate(uploaded_files, start=1):
        try:
            payload = uploaded.getvalue()
            result = validate_excel_file(BytesIO(payload), file_name=uploaded.name, config=config)
            all_results.append(result)
        except Exception as exc:  # noqa: BLE001 - show user-facing file errors in Streamlit
            failed.append({"file_name": uploaded.name, "error": str(exc)})
        progress.progress(pos / len(uploaded_files), text=f"Validated {pos}/{len(uploaded_files)} files")

    progress.empty()

    if all_results:
        # Store the full validation result.
        # Rule selection is applied later as a dashboard filter, without rerunning validation.
        st.session_state["validation_combined"] = combine_results(all_results)
        st.session_state["validation_source_signature"] = current_source_signature
        st.session_state["validation_config_signature"] = current_config_signature
    else:
        st.session_state["validation_combined"] = None

    st.session_state["validation_failed"] = failed

if st.session_state["validation_combined"] is None:
    st.info("Run validation once. After that, vessel/day/rule/report filters work without rerunning validation.")
    st.stop()

if st.session_state["validation_source_signature"] != current_source_signature:
    st.warning("The uploaded source file changed. Click Run validation to apply the new file.")
    st.stop()

if st.session_state["validation_config_signature"] != current_config_signature:
    st.info("Validation thresholds changed. Current results still use the previous thresholds. Click Run validation to apply them.")

failed = st.session_state["validation_failed"]
if failed:
    st.error("Some files could not be validated.")
    st.dataframe(pd.DataFrame(failed), use_container_width=True, hide_index=True)

raw_combined = st.session_state["validation_combined"]
combined = apply_rule_display_filter(raw_combined, selected_rules)
summary = combined["portfolio_summary"]
errors = combined["errors"]
checked_rows = combined["checked_rows"]
by_rule = combined["by_rule"]
skipped_rules = combined["skipped_rules"]

errors_dated_all = with_report_dates(errors) if not errors.empty else errors.copy()
checked_rows_dated_all = with_report_dates(checked_rows) if not checked_rows.empty else checked_rows.copy()

# Dashboard report-day scope. This is a display filter only; it does not rerun validation.
# Dates are taken from checked rows first, so dates with zero errors are still respected.
recent_dates = get_latest_report_dates(checked_rows_dated_all, int(recent_days))
if not recent_dates:
    recent_dates = get_latest_report_dates(errors_dated_all, int(recent_days))

errors_dated = filter_to_report_dates(errors_dated_all, recent_dates)
checked_rows_dated = filter_to_report_dates(checked_rows_dated_all, recent_dates)
recent_errors = errors_dated.copy()


# -----------------------------------------------------------------------------
# Vessel selection / fleet drill-down
# -----------------------------------------------------------------------------

vessel_options = get_vessel_options(errors_dated, checked_rows_dated)
valid_vessels = ["All vessels"] + vessel_options
if "selected_vessel_filter" not in st.session_state or st.session_state["selected_vessel_filter"] not in valid_vessels:
    st.session_state["selected_vessel_filter"] = "All vessels"

if vessel_options:
    vessel_rows_summary = (
        checked_rows_dated.groupby("ship_name", dropna=False)
        .agg(
            report_rows=("excel_row", "count"),
            rows_with_errors=("issue_count", lambda s: int((s > 0).sum())),
            rows_ok=("issue_count", lambda s: int((s == 0).sum())),
        )
        .reset_index()
        .rename(columns={"ship_name": "Vessel"})
    )
    vessel_errors_summary = (
        errors_dated.groupby("ship_name", dropna=False)
        .agg(
            total_errors=("issue_type", "count"),
            high_severity_errors=("severity", lambda s: int((s == "High").sum())),
        )
        .reset_index()
        .rename(columns={"ship_name": "Vessel"})
        if not errors_dated.empty and "ship_name" in errors_dated.columns
        else pd.DataFrame(columns=["Vessel", "total_errors", "high_severity_errors"])
    )
    vessel_summary = vessel_rows_summary.merge(vessel_errors_summary, on="Vessel", how="left")
    vessel_summary[["total_errors", "high_severity_errors"]] = vessel_summary[["total_errors", "high_severity_errors"]].fillna(0).astype(int)
    vessel_summary["error_row_rate"] = vessel_summary["rows_with_errors"] / vessel_summary["report_rows"].replace(0, pd.NA)
    vessel_summary = vessel_summary.sort_values(["high_severity_errors", "total_errors", "error_row_rate"], ascending=[False, False, False])
else:
    vessel_summary = pd.DataFrame()

if vessel_options:
    st.divider()
    st.subheader("Vessel selection")
    button_cols = st.columns(6)
    if button_cols[0].button("All vessels", use_container_width=True):
        st.session_state["selected_vessel_filter"] = "All vessels"
    top_button_vessels = vessel_summary.sort_values("total_errors", ascending=False).head(5)
    for idx, row in enumerate(top_button_vessels.itertuples(index=False), start=1):
        label = f"{str(row.Vessel)[:18]} ({int(row.total_errors)})"
        if button_cols[idx].button(label, use_container_width=True):
            st.session_state["selected_vessel_filter"] = str(row.Vessel)

    selected_vessel = st.selectbox(
        "Search or select vessel",
        options=valid_vessels,
        index=valid_vessels.index(st.session_state["selected_vessel_filter"]),
        help="Use All vessels for fleet view, or select one vessel to drill down.",
    )
    st.session_state["selected_vessel_filter"] = selected_vessel
else:
    selected_vessel = "All vessels"

errors_scope = apply_vessel_filter(errors_dated, selected_vessel)
recent_errors_scope = apply_vessel_filter(recent_errors, selected_vessel)
checked_rows_scope = apply_vessel_filter(checked_rows_dated, selected_vessel)
daily_kpis_scope = build_daily_kpis(checked_rows_scope, errors_scope)
by_rule_scope = (
    errors_scope.groupby("issue_type", dropna=False).size().reset_index(name="count")
    if not errors_scope.empty and "issue_type" in errors_scope.columns
    else pd.DataFrame(columns=["issue_type", "count"])
)
by_severity_scope = (
    errors_scope.groupby("severity", dropna=False).size().reset_index(name="count")
    if not errors_scope.empty and "severity" in errors_scope.columns
    else pd.DataFrame(columns=["severity", "count"])
)

rows_total = len(checked_rows_scope)
rows_with_errors = int((checked_rows_scope["issue_count"] > 0).sum()) if "issue_count" in checked_rows_scope.columns else 0
rows_ok = int((checked_rows_scope["issue_count"] == 0).sum()) if "issue_count" in checked_rows_scope.columns else 0
total_errors = len(errors_scope)
error_rate = rows_with_errors / rows_total if rows_total else 0
avg_errors_per_problem_row = total_errors / rows_with_errors if rows_with_errors else 0
status_summary_scope = pd.DataFrame([{"status": "Rows with errors", "count": rows_with_errors}, {"status": "Rows OK", "count": rows_ok}])

cols = st.columns(6)
cols[0].metric("View", selected_vessel)
cols[1].metric("Rows", rows_total)
cols[2].metric("Rows with errors", rows_with_errors)
cols[3].metric("Rows OK", rows_ok)
cols[4].metric("Total errors", total_errors)
cols[5].metric("Error row rate", f"{error_rate:.1%}")

# -----------------------------------------------------------------------------
# Tabs
# -----------------------------------------------------------------------------

fleet_tab, main_tab, recent_tab, kpi_tab, rows_tab, export_tab = st.tabs(
    ["Fleet overview", "All errors", f"Latest {int(recent_days)} report days", "KPI dashboard", "Checked rows", "Export / setup"]
)

with fleet_tab:
    st.subheader("Fleet overview")
    if vessel_summary.empty:
        st.info("No vessel information found in the validation results.")
    else:
        overview_cols = st.columns(4)
        overview_cols[0].metric("Vessels", vessel_summary["Vessel"].nunique())
        overview_cols[1].metric("Fleet rows", int(vessel_summary["report_rows"].sum()))
        overview_cols[2].metric("Fleet total errors", int(vessel_summary["total_errors"].sum()))
        overview_cols[3].metric("Vessels with High errors", int((vessel_summary["high_severity_errors"] > 0).sum()))

        display_summary = vessel_summary.copy()
        display_summary["error_row_rate"] = display_summary["error_row_rate"].map(lambda x: f"{x:.1%}" if pd.notna(x) else "N/A")
        st.dataframe(display_summary, use_container_width=True, hide_index=True)

        st.subheader("Top vessels by total errors")
        st.bar_chart(vessel_summary.sort_values("total_errors", ascending=False).head(10).set_index("Vessel")["total_errors"])

with main_tab:
    st.subheader("Errors")
    if errors_scope.empty:
        st.success("No validation errors found for this vessel selection.")
    else:
        left, mid, right = st.columns(3)
        rule_filter = left.multiselect("Rule", sorted(errors_scope["issue_type"].dropna().unique().tolist()), default=sorted(errors_scope["issue_type"].dropna().unique().tolist()))
        severity_filter = mid.multiselect("Severity", sorted(errors_scope["severity"].dropna().unique().tolist()), default=sorted(errors_scope["severity"].dropna().unique().tolist()))
        report_type_options = sorted(errors_scope["report_type"].dropna().unique().tolist()) if "report_type" in errors_scope.columns else []
        report_type_filter = right.multiselect("Report type", report_type_options, default=report_type_options)

        view = errors_scope[
            errors_scope["issue_type"].isin(rule_filter)
            & errors_scope["severity"].isin(severity_filter)
        ].copy()
        if "report_type" in view.columns and report_type_filter:
            view = view[view["report_type"].isin(report_type_filter)].copy()
        display_error_table("Filtered errors", view)

    if not by_rule_scope.empty:
        st.subheader("Errors by rule")
        st.dataframe(by_rule_scope.sort_values("count", ascending=False), use_container_width=True, hide_index=True)

with recent_tab:
    display_error_table(f"Problems in selected latest {int(recent_days)} report day(s)", recent_errors_scope)

    available_dates = sorted([d for d in errors_scope.get("report_date", pd.Series(dtype=object)).dropna().unique().tolist()]) if not errors_scope.empty else []
    if available_dates:
        st.divider()
        selected_date = st.selectbox("Show problems for one specific report day", options=available_dates, index=len(available_dates) - 1)
        day_errors = errors_scope[errors_scope["report_date"].eq(selected_date)].copy()
        display_error_table(f"Problems for {selected_date}", day_errors)

with kpi_tab:
    st.subheader("KPI dashboard")
    kpi_cols = st.columns(4)
    kpi_cols[0].metric("Recent errors", len(recent_errors_scope))
    kpi_cols[1].metric("Avg errors / problem row", f"{avg_errors_per_problem_row:.2f}")
    kpi_cols[2].metric("Unique error types", errors_scope["issue_type"].nunique() if not errors_scope.empty else 0)
    kpi_cols[3].metric("High severity errors", int((errors_scope["severity"].eq("High")).sum()) if not errors_scope.empty and "severity" in errors_scope.columns else 0)

    chart_left, chart_right = st.columns(2)
    with chart_left:
        if not status_summary_scope.empty and status_summary_scope["count"].sum() > 0:
            st.altair_chart(pie_chart(status_summary_scope, "status", "count", "Rows OK vs rows with errors"), use_container_width=True)
    with chart_right:
        if not by_severity_scope.empty and by_severity_scope["count"].sum() > 0:
            st.altair_chart(pie_chart(by_severity_scope, "severity", "count", "Errors by severity"), use_container_width=True)

    if not by_rule_scope.empty:
        st.subheader("Top error categories")
        st.bar_chart(by_rule_scope.sort_values("count", ascending=False).head(10).set_index("issue_type")["count"])

    if not daily_kpis_scope.empty:
        st.subheader("Daily validation trend")
        daily_for_chart = daily_kpis_scope.sort_values("report_date")
        st.line_chart(daily_for_chart.set_index("report_date")[["total_errors", "rows_with_errors"]])
        st.dataframe(daily_kpis_scope, use_container_width=True, hide_index=True)

with rows_tab:
    st.subheader("Checked rows")
    st.dataframe(checked_rows_scope, use_container_width=True, hide_index=True)

    if not skipped_rules.empty:
        st.warning("Some rules were skipped because required columns were not found in at least one file.")
        st.dataframe(skipped_rules, use_container_width=True, hide_index=True)

with export_tab:
    st.subheader("Export results")
    combined_for_export = dict(combined)
    combined_for_export["errors"] = errors_scope
    combined_for_export["checked_rows"] = checked_rows_scope
    combined_for_export["by_rule"] = by_rule_scope
    combined_for_export["portfolio_summary"] = build_portfolio_summary(checked_rows_scope, errors_scope)
    combined_for_export["recent_errors"] = recent_errors_scope
    combined_for_export["daily_kpis"] = daily_kpis_scope
    combined_for_export["by_severity"] = by_severity_scope
    combined_for_export["status_summary"] = status_summary_scope

    excel_bytes = results_to_excel_bytes(combined_for_export)
    st.download_button(
        "Download Excel validation report for current selection",
        data=excel_bytes,
        file_name="noon_report_validation_results.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

    st.download_button(
        "Download current selection errors as CSV",
        data=errors_scope.to_csv(index=False).encode("utf-8-sig"),
        file_name="noon_report_errors_current_selection.csv",
        mime="text/csv",
        use_container_width=True,
    )

    st.download_button(
        f"Download selected latest {int(recent_days)} report day errors as CSV",
        data=recent_errors_scope.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"noon_report_errors_last_{int(recent_days)}_days.csv",
        mime="text/csv",
        use_container_width=True,
    )
