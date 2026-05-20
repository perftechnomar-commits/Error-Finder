from __future__ import annotations

from io import BytesIO

import altair as alt
import pandas as pd
import streamlit as st

from validator import DEFAULT_CONFIG, RULES, combine_results, results_to_excel_bytes, validate_excel_file

st.set_page_config(page_title="Noon Report Checker", page_icon="✅", layout="wide")

st.title("Noon Report Checker")
st.caption("Upload ANTHEA-style noon report Excel files and run the adapted Error Finder validation rules.")


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
    """Keep errors from the latest N report dates in the uploaded data, not from today's date."""
    if errors_df.empty or "start_gmt" not in errors_df.columns:
        return errors_df.copy(), []
    dated = with_report_dates(errors_df)
    available_dates = sorted([d for d in dated["report_date"].dropna().unique().tolist()])
    last_dates = available_dates[-int(days):] if available_dates else []
    recent = dated[dated["report_date"].isin(last_dates)].copy()
    return recent, last_dates


def build_daily_kpis(checked_rows: pd.DataFrame, errors_df: pd.DataFrame) -> pd.DataFrame:
    """Build daily operational validation KPIs."""
    if checked_rows.empty or "start_gmt" not in checked_rows.columns:
        return pd.DataFrame()

    rows = with_report_dates(checked_rows)
    rows = rows.dropna(subset=["report_date"]).copy()
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
    st.dataframe(df[cols].sort_values(["report_date", "severity", "issue_type"], ascending=[False, True, True]), use_container_width=True, hide_index=True)


with st.sidebar:
    st.header("Validation thresholds")
    st.write("Defaults match the ANTHEA Y checker adaptation.")
    config = DEFAULT_CONFIG.copy()
    recent_days = st.number_input(
        "Recent problem table: last N report days",
        min_value=1,
        max_value=14,
        value=2,
        step=1,
        help="Uses the latest report dates found inside the uploaded Excel, not today's calendar date.",
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

uploaded_files = st.file_uploader(
    "Upload one or more Excel files",
    type=["xlsx", "xlsm"],
    accept_multiple_files=True,
    help="The app expects an ANTHEA-style workbook with a 'Table' sheet. If missing, it uses 'Query1' or the first sheet.",
)

with st.expander("Validation rules included", expanded=False):
    st.dataframe(pd.DataFrame(RULES), use_container_width=True, hide_index=True)

if not uploaded_files:
    st.info("Upload an ANTHEA-style noon report Excel file to start.")
    st.stop()

run = st.button("Run validation", type="primary", use_container_width=True)
if not run:
    st.stop()

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

if failed:
    st.error("Some files could not be validated.")
    st.dataframe(pd.DataFrame(failed), use_container_width=True, hide_index=True)

if not all_results:
    st.stop()

combined = combine_results(all_results)
summary = combined["portfolio_summary"]
errors = combined["errors"]
checked_rows = combined["checked_rows"]
by_rule = combined["by_rule"]
skipped_rules = combined["skipped_rules"]

recent_errors, recent_dates = filter_last_report_days(errors, int(recent_days))
daily_kpis = build_daily_kpis(checked_rows, errors)
errors_dated = with_report_dates(errors) if not errors.empty else errors.copy()
checked_rows_dated = with_report_dates(checked_rows) if not checked_rows.empty else checked_rows.copy()

metric_map = dict(zip(summary["metric"], summary["value"]))
rows_total = int(metric_map.get("Report rows", 0))
rows_with_errors = int(metric_map.get("Rows with issues", 0))
total_errors = int(metric_map.get("Total issues", 0))
error_rate = rows_with_errors / rows_total if rows_total else 0
avg_errors_per_problem_row = total_errors / rows_with_errors if rows_with_errors else 0

cols = st.columns(6)
cols[0].metric("Files", int(metric_map.get("Files checked", 0)))
cols[1].metric("Rows", rows_total)
cols[2].metric("Rows with errors", rows_with_errors)
cols[3].metric("Rows OK", int(metric_map.get("Rows OK", 0)))
cols[4].metric("Total errors", total_errors)
cols[5].metric("Error row rate", f"{error_rate:.1%}")

recent_label = ", ".join(str(d) for d in recent_dates) if recent_dates else "no report dates found"
st.info(f"Recent problem table is based on the latest {int(recent_days)} report day(s): {recent_label}.")

# Extra KPI summary frames for charts/export.
by_severity = errors.groupby("severity", dropna=False).size().reset_index(name="count") if not errors.empty else pd.DataFrame(columns=["severity", "count"])
status_summary = pd.DataFrame(
    [
        {"status": "Rows with errors", "count": rows_with_errors},
        {"status": "Rows OK", "count": int(metric_map.get("Rows OK", 0))},
    ]
)

main_tab, recent_tab, kpi_tab, rows_tab, export_tab = st.tabs([
    "All errors",
    f"Last {int(recent_days)} days",
    "KPI dashboard",
    "Checked rows",
    "Export / setup",
])

with main_tab:
    st.subheader("Errors")
    if errors.empty:
        st.success("No validation errors found.")
    else:
        left, mid, right = st.columns(3)
        file_filter = left.multiselect("File", sorted(errors["file_name"].dropna().unique().tolist()), default=sorted(errors["file_name"].dropna().unique().tolist()))
        rule_filter = mid.multiselect("Rule", sorted(errors["issue_type"].dropna().unique().tolist()), default=sorted(errors["issue_type"].dropna().unique().tolist()))
        severity_filter = right.multiselect("Severity", sorted(errors["severity"].dropna().unique().tolist()), default=sorted(errors["severity"].dropna().unique().tolist()))
        view = errors_dated[
            errors_dated["file_name"].isin(file_filter)
            & errors_dated["issue_type"].isin(rule_filter)
            & errors_dated["severity"].isin(severity_filter)
        ].copy()
        display_error_table("Filtered errors", view)

    if not by_rule.empty:
        st.subheader("Errors by rule")
        st.dataframe(by_rule.sort_values("count", ascending=False), use_container_width=True, hide_index=True)

with recent_tab:
    display_error_table(f"Problems in the latest {int(recent_days)} report day(s)", recent_errors)

    available_dates = sorted([d for d in errors_dated.get("report_date", pd.Series(dtype=object)).dropna().unique().tolist()]) if not errors_dated.empty else []
    if available_dates:
        st.divider()
        selected_date = st.selectbox("Show problems for one specific report day", options=available_dates, index=len(available_dates) - 1)
        day_errors = errors_dated[errors_dated["report_date"].eq(selected_date)].copy()
        display_error_table(f"Problems for {selected_date}", day_errors)

with kpi_tab:
    st.subheader("KPI dashboard")
    kpi_cols = st.columns(4)
    kpi_cols[0].metric("Recent errors", len(recent_errors))
    kpi_cols[1].metric("Avg errors / problem row", f"{avg_errors_per_problem_row:.2f}")
    kpi_cols[2].metric("Unique error types", errors["issue_type"].nunique() if not errors.empty else 0)
    kpi_cols[3].metric("High severity errors", int((errors["severity"].eq("High")).sum()) if not errors.empty else 0)

    chart_left, chart_right = st.columns(2)
    with chart_left:
        if not status_summary.empty and status_summary["count"].sum() > 0:
            st.altair_chart(pie_chart(status_summary, "status", "count", "Rows OK vs rows with errors"), use_container_width=True)
    with chart_right:
        if not by_severity.empty and by_severity["count"].sum() > 0:
            st.altair_chart(pie_chart(by_severity, "severity", "count", "Errors by severity"), use_container_width=True)

    if not by_rule.empty:
        top_rules = by_rule.sort_values("count", ascending=False).head(10)
        st.subheader("Top error categories")
        st.bar_chart(top_rules.set_index("issue_type")["count"])

    if not daily_kpis.empty:
        st.subheader("Daily validation trend")
        daily_for_chart = daily_kpis.sort_values("report_date")
        st.line_chart(daily_for_chart.set_index("report_date")[["total_errors", "rows_with_errors"]])
        st.dataframe(daily_kpis, use_container_width=True, hide_index=True)

    st.subheader("Extra KPI ideas to add next")
    st.markdown(
        """
- **Error rate by vessel / file**: ποσοστό προβληματικών rows ανά πλοίο ή αρχείο.
- **Top 5 recurring rules**: ποιοι κανόνες εμφανίζονται πιο συχνά, για να ξέρεις πού χρειάζεται training ή correction.
- **Severity mix pie**: High / Medium / Low errors σε πίτα.
- **Rows OK vs problematic pie**: γρήγορη εικόνα ποιότητας report.
- **Daily trend**: errors ανά report date, ώστε να βλέπεις αν βελτιώνεται ή χειροτερεύει η ποιότητα.
- **Consumption / performance KPIs**: SFOC outliers, Slip outliers, DG consumption vs load, boiler consumption exceedances.
- **Data completeness KPI**: πόσα required columns λείπουν ή πόσα blank critical fields υπάρχουν.
- **Critical open issues table**: μόνο High severity ή rules που επηρεάζουν consumption/performance.
        """
    )

with rows_tab:
    st.subheader("Checked rows")
    st.dataframe(checked_rows_dated, use_container_width=True, hide_index=True)

    if not skipped_rules.empty:
        st.warning("Some rules were skipped because required columns were not found in at least one file.")
        st.dataframe(skipped_rules, use_container_width=True, hide_index=True)

with export_tab:
    st.subheader("Export results")
    combined_for_export = dict(combined)
    combined_for_export["recent_errors"] = recent_errors
    combined_for_export["daily_kpis"] = daily_kpis
    combined_for_export["by_severity"] = by_severity
    combined_for_export["status_summary"] = status_summary

    excel_bytes = results_to_excel_bytes(combined_for_export)
    st.download_button(
        "Download Excel validation report",
        data=excel_bytes,
        file_name="noon_report_validation_results.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

    csv_bytes = errors.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "Download all errors as CSV",
        data=csv_bytes,
        file_name="noon_report_errors.csv",
        mime="text/csv",
        use_container_width=True,
    )

    recent_csv_bytes = recent_errors.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        f"Download last {int(recent_days)} days errors as CSV",
        data=recent_csv_bytes,
        file_name=f"noon_report_errors_last_{int(recent_days)}_days.csv",
        mime="text/csv",
        use_container_width=True,
    )
