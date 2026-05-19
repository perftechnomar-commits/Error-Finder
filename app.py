from __future__ import annotations

from io import BytesIO

import pandas as pd
import streamlit as st

from validator import DEFAULT_CONFIG, RULES, combine_results, results_to_excel_bytes, validate_excel_file

st.set_page_config(page_title="Noon Report Checker", page_icon="✅", layout="wide")

st.title("Noon Report Checker")
st.caption("Upload ANTHEA-style noon report Excel files and run the adapted Error Finder validation rules.")

with st.sidebar:
    st.header("Validation thresholds")
    st.write("Defaults match the ANTHEA Y checker adaptation.")
    config = DEFAULT_CONFIG.copy()
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

metric_map = dict(zip(summary["metric"], summary["value"]))
cols = st.columns(5)
cols[0].metric("Files", int(metric_map.get("Files checked", 0)))
cols[1].metric("Rows", int(metric_map.get("Report rows", 0)))
cols[2].metric("Rows with errors", int(metric_map.get("Rows with issues", 0)))
cols[3].metric("Rows OK", int(metric_map.get("Rows OK", 0)))
cols[4].metric("Total errors", int(metric_map.get("Total issues", 0)))

if not by_rule.empty:
    st.subheader("Errors by rule")
    st.dataframe(by_rule.sort_values("count", ascending=False), use_container_width=True, hide_index=True)

st.subheader("Errors")
if errors.empty:
    st.success("No validation errors found.")
else:
    left, mid, right = st.columns(3)
    file_filter = left.multiselect("File", sorted(errors["file_name"].dropna().unique().tolist()), default=sorted(errors["file_name"].dropna().unique().tolist()))
    rule_filter = mid.multiselect("Rule", sorted(errors["issue_type"].dropna().unique().tolist()), default=sorted(errors["issue_type"].dropna().unique().tolist()))
    severity_filter = right.multiselect("Severity", sorted(errors["severity"].dropna().unique().tolist()), default=sorted(errors["severity"].dropna().unique().tolist()))
    view = errors[
        errors["file_name"].isin(file_filter)
        & errors["issue_type"].isin(rule_filter)
        & errors["severity"].isin(severity_filter)
    ].copy()
    st.dataframe(view, use_container_width=True, hide_index=True)

st.subheader("Checked rows")
st.dataframe(checked_rows, use_container_width=True, hide_index=True)

if not skipped_rules.empty:
    st.warning("Some rules were skipped because required columns were not found in at least one file.")
    st.dataframe(skipped_rules, use_container_width=True, hide_index=True)

excel_bytes = results_to_excel_bytes(combined)
st.download_button(
    "Download Excel validation report",
    data=excel_bytes,
    file_name="noon_report_validation_results.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=True,
)

csv_bytes = errors.to_csv(index=False).encode("utf-8-sig")
st.download_button(
    "Download errors as CSV",
    data=csv_bytes,
    file_name="noon_report_errors.csv",
    mime="text/csv",
    use_container_width=True,
)
