from __future__ import annotations

from io import BytesIO
import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
import altair as alt
import pandas as pd
import streamlit as st

from validator import DEFAULT_CONFIG, RULES, combine_results, results_to_excel_bytes, validate_excel_file

APP_BUILD = "AUTO_SOURCE_FLEET_FINAL_2026_05_21_DG_OPTIMISATION"

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


def format_report_date(value: object) -> str:
    """Format report dates as d/m/yy for compact dashboard captions."""
    if value is None or pd.isna(value):
        return ""
    dt = pd.to_datetime(value)
    return f"{dt.day}/{dt.month}/{dt.strftime('%y')}"


def get_data_window_caption(rows_df: pd.DataFrame, errors_df: pd.DataFrame) -> str:
    """Build a small caption showing the report-date window available in the loaded source."""
    date_values = []
    for df in (rows_df, errors_df):
        if not df.empty and "report_date" in df.columns:
            date_values.extend(df["report_date"].dropna().tolist())

    if not date_values:
        return "Report days: no report dates found"

    dates = sorted(set(date_values))
    start_date = dates[0]
    end_date = dates[-1]

    if start_date == end_date:
        return f"Report days: {format_report_date(start_date)}"

    return f"Report days from {format_report_date(start_date)} - {format_report_date(end_date)}"


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
        "report_id",
        "ship_name",
        "fleet",
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
# Copy-paste message template helpers
# -----------------------------------------------------------------------------

def clean_message_value(value: object, default: str = "-") -> str:
    """Return a compact, readable string for message templates."""
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text if text else default


def format_template_report_date(value: object) -> str:
    """Format a report date for operational messages."""
    if value is None:
        return "-"
    try:
        if pd.isna(value):
            return "-"
    except (TypeError, ValueError):
        pass
    try:
        return format_report_date(value)
    except Exception:  # noqa: BLE001 - keep message generation robust
        return clean_message_value(value)


def get_template_date_label(errors_df: pd.DataFrame, checked_rows_df: pd.DataFrame) -> str:
    """Build a date label from the currently selected validation scope."""
    dates = []
    for df in (errors_df, checked_rows_df):
        if not df.empty and "report_date" in df.columns:
            dates.extend(df["report_date"].dropna().tolist())
    if not dates:
        return "selected report window"
    unique_dates = sorted(set(dates))
    if len(unique_dates) == 1:
        return format_template_report_date(unique_dates[0])
    return f"{format_template_report_date(unique_dates[0])} - {format_template_report_date(unique_dates[-1])}"


def build_issue_lines(errors_df: pd.DataFrame) -> str:
    """Create bullet lines for all validation findings in the current filtered scope."""
    if errors_df.empty:
        return "- No validation errors found for this selection."

    sort_cols = [c for c in ["report_date", "severity", "ship_name", "issue_type"] if c in errors_df.columns]
    view = errors_df.copy()
    if sort_cols:
        ascending = [False if c == "report_date" else True for c in sort_cols]
        view = view.sort_values(sort_cols, ascending=ascending)

    lines = []
    for _, row in view.iterrows():
        parts = []
        if "report_date" in view.columns:
            parts.append(format_template_report_date(row.get("report_date")))
        if "ship_name" in view.columns:
            parts.append(clean_message_value(row.get("ship_name")))
        if "report_type" in view.columns:
            parts.append(clean_message_value(row.get("report_type")))
        issue = clean_message_value(row.get("issue_type"))
        message = clean_message_value(row.get("message"), "")
        value = clean_message_value(row.get("value"), "")
        expected = clean_message_value(row.get("expected"), "")

        detail = issue
        if message:
            detail += f": {message}"
        if value and expected:
            detail += f" | Value: {value} | Expected: {expected}"
        elif value:
            detail += f" | Value: {value}"
        elif expected:
            detail += f" | Expected: {expected}"

        prefix = " | ".join(p for p in parts if p and p != "-")
        lines.append(f"- {prefix} | {detail}" if prefix else f"- {detail}")

    return "\n".join(lines)


def build_rule_summary_lines(by_rule_df: pd.DataFrame, max_items: int = 8) -> str:
    """Create a compact top-rule summary for message templates."""
    if by_rule_df.empty or not {"issue_type", "count"}.issubset(by_rule_df.columns):
        return "- No error categories found."
    view = by_rule_df.sort_values("count", ascending=False).head(int(max_items))
    return "\n".join(f"- {row.issue_type}: {int(row.count)}" for row in view.itertuples(index=False))


def build_vessel_attention_lines(vessel_summary_df: pd.DataFrame, max_items: int = 8) -> str:
    """Summarize vessels requiring attention for fleet-level messages."""
    needed = {"Vessel", "total_errors", "high_severity_errors"}
    if vessel_summary_df.empty or not needed.issubset(vessel_summary_df.columns):
        return "- No vessel summary available for this selection."
    view = vessel_summary_df.sort_values(["high_severity_errors", "total_errors"], ascending=[False, False]).head(int(max_items))
    lines = []
    for row in view.itertuples(index=False):
        if int(row.total_errors) <= 0:
            continue
        lines.append(f"- {row.Vessel}: {int(row.total_errors)} issue(s), {int(row.high_severity_errors)} high severity")
    return "\n".join(lines) if lines else "- No vessels with validation issues in this selection."


def build_message_template(
    template_name: str,
    errors_df: pd.DataFrame,
    checked_rows_df: pd.DataFrame,
    by_rule_df: pd.DataFrame,
    vessel_summary_df: pd.DataFrame,
    selected_vessel_name: str,
    data_window_text: str,

) -> str:
    """Generate a copy-ready operational message from the current app selection."""
    vessel_label = selected_vessel_name if selected_vessel_name != "All vessels" else "fleet / current selection"
    date_label = get_template_date_label(errors_df, checked_rows_df)
    total_rows = len(checked_rows_df)
    rows_with_issues = int((checked_rows_df.get("issue_count", pd.Series(dtype=int)) > 0).sum()) if total_rows else 0
    total_issues = len(errors_df)
    high_issues = int(errors_df["severity"].astype(str).eq("High").sum()) if not errors_df.empty and "severity" in errors_df.columns else 0
    issue_lines = build_issue_lines(errors_df)
    rule_lines = build_rule_summary_lines(by_rule_df)
    vessel_lines = build_vessel_attention_lines(vessel_summary_df)

    if total_issues == 0:
        no_issue_body = (
            f"Noon report validation completed for {vessel_label}.\n\n"
            f"Report window: {date_label}\n"
            f"{data_window_text}\n"
            f"Checked rows: {total_rows}\n\n"
            "No validation issues were found for the current selection."
        )
        if template_name == "Vessel follow-up email":
            return (
                f"Subject: Noon report validation - {vessel_label} - {date_label}\n\n"
                "Good day Captain,\n\n"
                f"{no_issue_body}\n\n"
                "No action is required from your side at this stage.\n\n"
                "Best regards,"
            )
        return no_issue_body

    if template_name == "Vessel follow-up email":
        return (
            f"Subject: Noon report validation follow-up - {vessel_label} - {date_label}\n\n"
            "Good day Captain,\n\n"
            f"Please review the below noon report validation findings for {vessel_label}.\n\n"
            "Summary:\n"
            f"- Report window: {date_label}\n"
            f"- {data_window_text}\n"
            f"- Checked rows: {total_rows}\n"
            f"- Rows with issues: {rows_with_issues}\n"
            f"- Total issues: {total_issues}\n"
            f"- High severity issues: {high_issues}\n\n"
            "Main findings:\n"
            f"{issue_lines}\n\n"
            "Kindly check the highlighted items in the exported Excel report and revert with confirmation/corrections where required.\n\n"
            "Best regards,"
        )

    if template_name == "Internal fleet summary":
        return (
            "Team,\n\n"
            f"Noon report validation has been completed for {vessel_label}.\n\n"
            "Summary:\n"
            f"- Report window: {date_label}\n"
            f"- {data_window_text}\n"
            f"- Checked rows: {total_rows}\n"
            f"- Rows with issues: {rows_with_issues}\n"
            f"- Total issues: {total_issues}\n"
            f"- High severity issues: {high_issues}\n\n"
            "Top error categories:\n"
            f"{rule_lines}\n\n"
            "Vessels requiring attention:\n"
            f"{vessel_lines}\n\n"
            "Detailed findings are available in the exported Excel validation report."
        )

    return (
        f"Noon checker completed for {vessel_label} ({date_label}). "
        f"Found {total_issues} issue(s) across {rows_with_issues} row(s); high severity: {high_issues}.\n\n"
        "Main items:\n"
        f"{issue_lines}\n\n"
        "Please review the exported Excel report and update/correct the relevant noon report entries."
    )


def build_message_templates_df(
    errors_df: pd.DataFrame,
    checked_rows_df: pd.DataFrame,
    by_rule_df: pd.DataFrame,
    vessel_summary_df: pd.DataFrame,
    selected_vessel_name: str,
    data_window_text: str,

) -> pd.DataFrame:
    """Return all standard templates as a dataframe, ready for optional Excel export."""
    template_names = ["Vessel follow-up email", "Internal fleet summary", "Short Teams/WhatsApp message"]
    rows = []
    for template_name in template_names:
        rows.append(
            {
                "template_name": template_name,
                "vessel_scope": selected_vessel_name,
                "message": build_message_template(
                    template_name,
                    errors_df,
                    checked_rows_df,
                    by_rule_df,
                    vessel_summary_df,
                    selected_vessel_name,
                    data_window_text,
                ),
            }
        )
    return pd.DataFrame(rows)



def build_issue_follow_up_message(issue_row: pd.Series | dict) -> str:
    """Build one copy-paste message for one validation issue row."""
    get_value = issue_row.get if hasattr(issue_row, "get") else lambda key, default=None: default
    return (
        "Dear Captain / Chief Engineer,\n\n"
        "Please note that a validation check has identified a possible inconsistency in the submitted report.\n\n"
        f"Issue: {clean_message_value(get_value('issue_type'))}\n"
        f"Reported value: {clean_message_value(get_value('value'))}\n"
        f"Expected / normal range: {clean_message_value(get_value('expected'))}\n"
        f"Related field(s): {clean_message_value(get_value('columns'))}\n\n"
        "Kindly verify the reported value and amend the report if required. "
        "If the value is confirmed correct, please provide a short comment/justification in the remarks.\n\n"
        "Best Regards,"
    )


def build_issue_message_subject(issue_row: pd.Series | dict, selected_vessel_name: str = "") -> str:
    """Build a concise email subject for the selected validation issue."""
    get_value = issue_row.get if hasattr(issue_row, "get") else lambda key, default=None: default
    vessel = clean_message_value(get_value("ship_name"), selected_vessel_name or "Vessel")
    issue = clean_message_value(get_value("issue_type"), "Validation issue")
    report_date = format_template_report_date(get_value("report_date"))
    date_suffix = f" - {report_date}" if report_date and report_date != "-" else ""
    return f"Noon report validation check - {vessel}{date_suffix} - {issue}"


def add_copy_paste_issue_messages(errors_df: pd.DataFrame, selected_vessel_name: str = "") -> pd.DataFrame:
    """Add one copy-paste message column per validation issue for Excel/CSV export."""
    out = errors_df.copy()
    if out.empty:
        out["email_subject"] = pd.Series(dtype="object")
        out["copy_paste_message"] = pd.Series(dtype="object")
        return out
    out["email_subject"] = out.apply(lambda row: build_issue_message_subject(row, selected_vessel_name), axis=1)
    out["copy_paste_message"] = out.apply(build_issue_follow_up_message, axis=1)
    return out


def build_issue_messages_df(errors_df: pd.DataFrame, selected_vessel_name: str = "") -> pd.DataFrame:
    """Return a dedicated dataframe containing one generated message per validation issue."""
    if errors_df.empty:
        return pd.DataFrame(columns=["message_no", "ship_name", "report_date", "issue_type", "email_subject", "copy_paste_message"])
    export_df = add_copy_paste_issue_messages(errors_df, selected_vessel_name).reset_index(drop=True)
    export_df.insert(0, "message_no", range(1, len(export_df) + 1))
    preferred = [
        "message_no",
        "ship_name",
        "report_date",
        "report_type",
        "excel_row",
        "report_id",
        "issue_type",
        "severity",
        "value",
        "expected",
        "columns",
        "email_subject",
        "copy_paste_message",
    ]
    return export_df[[col for col in preferred if col in export_df.columns]]


def build_issue_selector_options(errors_df: pd.DataFrame, selected_vessel_name: str = "") -> list[tuple[str, int]]:
    """Build readable selectbox labels for validation issues."""
    if errors_df.empty:
        return []
    view = errors_df.reset_index(drop=True)
    options = []
    for idx, row in view.iterrows():
        date_text = format_template_report_date(row.get("report_date")) if "report_date" in view.columns else "-"
        vessel = clean_message_value(row.get("ship_name"), selected_vessel_name or "-")
        issue = clean_message_value(row.get("issue_type"), "Validation issue")
        label_parts = [f"#{idx + 1}", vessel, date_text, issue]
        options.append((" | ".join(part for part in label_parts if part and part != "-"), idx))
    return options


def build_all_issue_messages_text(errors_df: pd.DataFrame, selected_vessel_name: str = "") -> str:
    """Build a combined text containing one message for every issue in the current filtered scope."""
    if errors_df.empty:
        return "No validation issues were found for the current selection."
    view = errors_df.reset_index(drop=True)
    messages = []
    for idx, row in view.iterrows():
        subject = build_issue_message_subject(row, selected_vessel_name)
        messages.append(f"MESSAGE {idx + 1}\nSubject: {subject}\n\n{build_issue_follow_up_message(row)}")
    return "\n\n---\n\n".join(messages)


def build_captain_chief_engineer_subject(errors_df: pd.DataFrame, selected_vessel_name: str = "") -> str:
    """Build one email subject for the current filtered validation scope."""
    vessel_label = selected_vessel_name if selected_vessel_name and selected_vessel_name != "All vessels" else "Current selection"
    date_label = get_template_date_label(errors_df, pd.DataFrame())
    date_suffix = f" - {date_label}" if date_label and date_label != "selected report window" else ""
    return f"Noon report validation check - {vessel_label}{date_suffix}"


def build_issue_detail_block(issue_row: pd.Series | dict, issue_no: int | None = None) -> str:
    """Build one issue block inside the Captain / Chief Engineer message."""
    get_value = issue_row.get if hasattr(issue_row, "get") else lambda key, default=None: default
    title = f"Issue {issue_no}" if issue_no is not None else "Issue"

    context_lines = []
    report_date = format_template_report_date(get_value("report_date"))
    if report_date and report_date != "-":
        context_lines.append(f"Report date: {report_date}")

    for label, key in [
        ("Vessel", "ship_name"),
        ("Report type", "report_type"),
        ("Report ID", "report_id"),
    ]:
        value = clean_message_value(get_value(key), "")
        if value:
            context_lines.append(f"{label}: {value}")

    lines = [f"{title}:"]
    if context_lines:
        lines.extend(context_lines)
    lines.extend(
        [
            f"Issue: {clean_message_value(get_value('issue_type'))}",
            f"Reported value: {clean_message_value(get_value('value'))}",
            f"Expected / normal range: {clean_message_value(get_value('expected'))}",
            f"Related field(s): {clean_message_value(get_value('columns'))}",
        ]
    )
    return "\n".join(lines)


def build_captain_chief_engineer_message(errors_df: pd.DataFrame, selected_vessel_name: str = "") -> str:
    """Build the single copy-paste message for Captain / Chief Engineer using current filters."""
    if errors_df.empty:
        return (
            "Dear Captain / Chief Engineer,\n\n"
            "Please note that the validation check has been completed for the current selection.\n\n"
            "No possible inconsistencies were identified in the submitted report(s).\n\n"
            "Best Regards,"
        )

    view = errors_df.copy().reset_index(drop=True)
    sort_cols = [c for c in ["report_date", "ship_name", "report_type", "issue_type"] if c in view.columns]
    if sort_cols:
        ascending = [False if c == "report_date" else True for c in sort_cols]
        view = view.sort_values(sort_cols, ascending=ascending).reset_index(drop=True)

    issue_blocks = [build_issue_detail_block(row, idx + 1) for idx, row in view.iterrows()]
    inconsistency_word = "a possible inconsistency" if len(view) == 1 else "possible inconsistencies"

    return (
        "Dear Captain / Chief Engineer,\n\n"
        f"Please note that a validation check has identified {inconsistency_word} in the submitted report.\n\n"
        + "\n\n".join(issue_blocks)
        + "\n\n"
        "Kindly verify the reported value(s) and amend the report if required. "
        "If the value(s) are confirmed correct, please provide a short comment/justification in the remarks.\n\n"
        "Best Regards,"
    )


def build_captain_message_df(errors_df: pd.DataFrame, selected_vessel_name: str = "") -> pd.DataFrame:
    """Return one-row dataframe containing the current Captain / Chief Engineer message."""
    return pd.DataFrame(
        [
            {
                "email_subject": build_captain_chief_engineer_subject(errors_df, selected_vessel_name),
                "copy_paste_message": build_captain_chief_engineer_message(errors_df, selected_vessel_name),
                "issue_count": len(errors_df),
                "vessel_scope": selected_vessel_name,
            }
        ]
    )


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


def normalize_merge_key_value(value: object) -> str:
    """Normalize merge-key values so app filtering is stable across mixed Excel dtypes."""
    try:
        if pd.isna(value):
            return "__MISSING__"
    except (TypeError, ValueError):
        pass

    if isinstance(value, float) and value.is_integer():
        return str(int(value))

    return str(value).strip()


def rebuild_checked_rows_issue_counts(checked_rows_df: pd.DataFrame, errors_df: pd.DataFrame) -> pd.DataFrame:
    """Recalculate issue_count after validation rule scope is applied.

    The checked rows and errors tables can contain the same key with different
    pandas dtypes, depending on how Excel interpreted the source values.
    For example, report_id or excel_row may be numeric in one table and object
    in another. Normalize temporary merge keys to strings before merging to
    avoid pandas dtype mismatch errors.
    """
    out = checked_rows_df.copy()
    if out.empty:
        return out

    keys = [c for c in ["file_name", "excel_row", "report_id", "ship_name"] if c in out.columns and c in errors_df.columns]
    if "raw_issue_count" not in out.columns and "issue_count" in out.columns:
        out["raw_issue_count"] = out["issue_count"]

    if not keys or errors_df.empty:
        out["issue_count"] = 0
        return out

    errors_for_count = errors_df.copy()
    merge_keys = []
    for key in keys:
        merge_key = f"__merge_key_{key}"
        out[merge_key] = out[key].map(normalize_merge_key_value)
        errors_for_count[merge_key] = errors_for_count[key].map(normalize_merge_key_value)
        merge_keys.append(merge_key)

    issue_counts = errors_for_count.groupby(merge_keys, dropna=False).size().reset_index(name="display_issue_count")
    out = out.merge(issue_counts, on=merge_keys, how="left")
    out["issue_count"] = out["display_issue_count"].fillna(0).astype(int)
    return out.drop(columns=["display_issue_count", *merge_keys])


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


def format_fleet_label(value: object) -> str:
    """Display source values such as 1, 1.0, or Fleet 1 as Fleet 1."""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass

    text = str(value).strip()
    if not text:
        return ""

    numeric_text = text[5:].strip() if text.lower().startswith("fleet") else text
    try:
        number = float(numeric_text)
        if number.is_integer():
            return f"Fleet {int(number)}"
    except (TypeError, ValueError):
        pass

    return text


def fleet_sort_key(value: object) -> tuple[int, int | str]:
    """Sort numbered fleets by their number instead of alphabetically."""
    label = format_fleet_label(value)
    if label.lower().startswith("fleet "):
        try:
            return (0, int(label[6:].strip()))
        except ValueError:
            pass
    return (1, label.casefold())


def get_fleet_options(errors_df: pd.DataFrame, rows_df: pd.DataFrame) -> list[str]:
    """Return raw fleet values, sorted numerically for display."""
    values = []
    for df in (errors_df, rows_df):
        if not df.empty and "fleet" in df.columns:
            fleet_values = df["fleet"].dropna().astype(str).str.strip()
            values.extend(fleet_values[fleet_values.ne("")].unique().tolist())
    return sorted(set(values), key=fleet_sort_key)


def apply_fleet_filter(df: pd.DataFrame, fleet_name: str) -> pd.DataFrame:
    """Filter a dataframe by fleet while preserving the original dataframe."""
    if df.empty or "fleet" not in df.columns or fleet_name == "All fleets":
        return df.copy()
    fleet_values = df["fleet"].fillna("").astype(str).str.strip()
    return df[fleet_values.eq(str(fleet_name).strip())].copy()


def get_vessel_options(errors_df: pd.DataFrame, rows_df: pd.DataFrame) -> list[str]:
    values = []
    for df in (errors_df, rows_df):
        if not df.empty and "ship_name" in df.columns:
            vessel_values = df["ship_name"].dropna().astype(str).str.strip()
            values.extend(vessel_values[vessel_values.ne("")].unique().tolist())
    return sorted(set(values))


def apply_vessel_filter(df: pd.DataFrame, vessel_name: str) -> pd.DataFrame:
    if df.empty or "ship_name" not in df.columns or vessel_name == "All vessels":
        return df.copy()
    vessel_values = df["ship_name"].fillna("").astype(str).str.strip()
    return df[vessel_values.eq(str(vessel_name).strip())].copy()


# -----------------------------------------------------------------------------
# Sidebar controls
# -----------------------------------------------------------------------------

with st.sidebar:
    st.header("Validation thresholds")

    config = DEFAULT_CONFIG.copy()
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

    with st.expander("Multiple DGs rule", expanded=False):
        config["dg_power_running_threshold_kw"] = st.number_input(
            "DG counted as running above kW",
            value=float(DEFAULT_CONFIG.get("dg_power_running_threshold_kw", 10.0)),
            step=1.0,
            key="dg_power_running_threshold_kw_input",
            help=(
                "Used by the Multiple DGs rule. A DG with power above this value is counted as running. "
                "The result changes only when this value crosses the actual DG1/DG2/DG3/DG4 power values in the report."
            ),
        )
        config["dg_optimization_load_factor"] = st.number_input(
            "Multiple DGs load factor",
            value=float(DEFAULT_CONFIG.get("dg_optimization_load_factor", 0.70)),
            min_value=0.0,
            max_value=1.0,
            step=0.05,
            format="%.2f",
            key="dg_optimization_load_factor_input",
            help="Used in the formula: sum(DG power / DG MCR) < factor * (running DGs - 1).",
        )
        st.caption(
            "Tip: the kW threshold controls only how many DGs are counted as running. "
            "The exported Checked Rows sheet includes Multiple DGs diagnostic columns so you can verify the DG threshold and formula result."
        )

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
# Validation execution
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


def run_validation_and_store(progress_text: str) -> None:
    """Run full validation and store the raw result.

    Rule selection is applied later as a dashboard filter, without rerunning validation.
    Validation thresholds are calculation parameters, so threshold changes trigger
    immediate revalidation after the first run.
    """
    all_results = []
    failed = []
    progress = st.progress(0, text=progress_text)

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
        st.session_state["validation_combined"] = combine_results(all_results)
        st.session_state["validation_source_signature"] = current_source_signature
        st.session_state["validation_config_signature"] = current_config_signature
    else:
        st.session_state["validation_combined"] = None

    st.session_state["validation_failed"] = failed


run = st.button("Run validation", type="primary", use_container_width=True)

source_changed_after_run = (
    st.session_state["validation_combined"] is not None
    and st.session_state["validation_source_signature"] != current_source_signature
)
thresholds_changed_after_run = (
    st.session_state["validation_combined"] is not None
    and st.session_state["validation_config_signature"] != current_config_signature
)

if run:
    run_validation_and_store("Starting validation...")
elif source_changed_after_run:
    run_validation_and_store("Source file changed. Revalidating automatically...")
elif thresholds_changed_after_run:
    run_validation_and_store("Validation thresholds changed. Revalidating automatically...")

if st.session_state["validation_combined"] is None:
    st.info("Run validation once. After that, vessel/day/rule/report filters work without rerunning validation. Threshold changes will revalidate automatically.")
    st.stop()

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

# Use the full loaded source window.
# The source file itself controls the time span; dashboard filters should not silently cut it down.
errors_dated = errors_dated_all.copy()
checked_rows_dated = checked_rows_dated_all.copy()
recent_errors = errors_dated.copy()
data_window_caption = get_data_window_caption(checked_rows_dated, errors_dated)


# -----------------------------------------------------------------------------
# Fleet and vessel selection / drill-down
# -----------------------------------------------------------------------------

fleet_options = get_fleet_options(errors_dated, checked_rows_dated)
valid_fleets = ["All fleets"] + fleet_options

if (
    "selected_fleet_filter" not in st.session_state
    or st.session_state["selected_fleet_filter"] not in valid_fleets
):
    st.session_state["selected_fleet_filter"] = "All fleets"

st.divider()
st.subheader("Fleet and vessel selection")
fleet_col, vessel_col = st.columns(2)

with fleet_col:
    selected_fleet = st.selectbox(
        "Search or select fleet",
        options=valid_fleets,
        key="selected_fleet_filter",
        format_func=lambda value: value if value == "All fleets" else format_fleet_label(value),
        help="Use All fleets for the complete source, or select one fleet to restrict the dashboard.",
    )

# Apply fleet selection first so the vessel dropdown only contains vessels
# belonging to the selected fleet.
errors_fleet_scope = apply_fleet_filter(errors_dated, selected_fleet)
recent_errors_fleet_scope = apply_fleet_filter(recent_errors, selected_fleet)
checked_rows_fleet_scope = apply_fleet_filter(checked_rows_dated, selected_fleet)

vessel_options = get_vessel_options(errors_fleet_scope, checked_rows_fleet_scope)
valid_vessels = ["All vessels"] + vessel_options

if (
    "selected_vessel_filter" not in st.session_state
    or st.session_state["selected_vessel_filter"] not in valid_vessels
):
    st.session_state["selected_vessel_filter"] = "All vessels"

with vessel_col:
    selected_vessel = st.selectbox(
        "Search or select vessel",
        options=valid_vessels,
        key="selected_vessel_filter",
        help="The available vessels are restricted by the selected fleet.",
    )

# Build the vessel overview within the selected fleet. Include the Fleet column
# when it exists so the all-fleets view remains easy to understand.
if vessel_options:
    row_group_cols = [c for c in ["fleet", "ship_name"] if c in checked_rows_fleet_scope.columns]
    vessel_rows_summary = (
        checked_rows_fleet_scope.groupby(row_group_cols, dropna=False)
        .agg(
            report_rows=("excel_row", "count"),
            rows_with_errors=("issue_count", lambda s: int((s > 0).sum())),
            rows_ok=("issue_count", lambda s: int((s == 0).sum())),
        )
        .reset_index()
        .rename(columns={"fleet": "Fleet", "ship_name": "Vessel"})
    )

    if not errors_fleet_scope.empty and "ship_name" in errors_fleet_scope.columns:
        error_group_cols = [c for c in ["fleet", "ship_name"] if c in errors_fleet_scope.columns]
        vessel_errors_summary = (
            errors_fleet_scope.groupby(error_group_cols, dropna=False)
            .agg(
                total_errors=("issue_type", "count"),
                high_severity_errors=("severity", lambda s: int(s.astype(str).eq("High").sum())),
            )
            .reset_index()
            .rename(columns={"fleet": "Fleet", "ship_name": "Vessel"})
        )
    else:
        error_summary_cols = ["Vessel", "total_errors", "high_severity_errors"]
        if "Fleet" in vessel_rows_summary.columns:
            error_summary_cols.insert(0, "Fleet")
        vessel_errors_summary = pd.DataFrame(columns=error_summary_cols)

    summary_merge_keys = [c for c in ["Fleet", "Vessel"] if c in vessel_rows_summary.columns and c in vessel_errors_summary.columns]
    vessel_summary = vessel_rows_summary.merge(vessel_errors_summary, on=summary_merge_keys, how="left")
    vessel_summary[["total_errors", "high_severity_errors"]] = (
        vessel_summary[["total_errors", "high_severity_errors"]].fillna(0).astype(int)
    )
    vessel_summary["error_row_rate"] = (
        vessel_summary["rows_with_errors"] / vessel_summary["report_rows"].replace(0, pd.NA)
    )
    vessel_summary = vessel_summary.sort_values(
        ["high_severity_errors", "total_errors", "error_row_rate"],
        ascending=[False, False, False],
    )
else:
    vessel_summary = pd.DataFrame()

# Apply the vessel filter after the fleet filter. All dashboard tabs and exports
# below use these scoped dataframes.
errors_scope = apply_vessel_filter(errors_fleet_scope, selected_vessel)
recent_errors_scope = apply_vessel_filter(recent_errors_fleet_scope, selected_vessel)
checked_rows_scope = apply_vessel_filter(checked_rows_fleet_scope, selected_vessel)
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
if selected_vessel != "All vessels":
    current_view_label = selected_vessel
elif selected_fleet != "All fleets":
    current_view_label = format_fleet_label(selected_fleet)
else:
    current_view_label = "All fleets"

cols[0].metric("View", current_view_label)
cols[1].metric("Rows", rows_total)
cols[2].metric("Rows with errors", rows_with_errors)
cols[3].metric("Rows OK", rows_ok)
cols[4].metric("Total errors", total_errors)
cols[5].metric("Error row rate", f"{error_rate:.1%}")

selected_fleet_display = selected_fleet if selected_fleet == "All fleets" else format_fleet_label(selected_fleet)
st.caption(f"Fleet: {selected_fleet_display} | Vessel: {selected_vessel} | {data_window_caption}")

# -----------------------------------------------------------------------------
# Tabs
# -----------------------------------------------------------------------------

fleet_tab, main_tab, recent_tab, kpi_tab, rows_tab, export_tab = st.tabs(
    ["Fleet overview", "All errors", "Report days", "KPI dashboard", "Checked rows", "Export / setup"]
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
        if "Fleet" in display_summary.columns:
            display_summary["Fleet"] = display_summary["Fleet"].map(format_fleet_label)
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
    display_error_table("Problems in selected data window", recent_errors_scope)

    # Report-day drilldown. Use checked rows first so dates with zero errors can still be selected.
    if not checked_rows_scope.empty and "report_date" in checked_rows_scope.columns:
        available_dates = sorted([d for d in checked_rows_scope["report_date"].dropna().unique().tolist()])
    elif not errors_scope.empty and "report_date" in errors_scope.columns:
        available_dates = sorted([d for d in errors_scope["report_date"].dropna().unique().tolist()])
    else:
        available_dates = []

    if available_dates:
        st.divider()

        single_col, multi_col = st.columns(2)

        with single_col:
            selected_date = st.selectbox(
                "Show problems for one specific report day",
                options=available_dates,
                index=len(available_dates) - 1,
                format_func=format_report_date,
            )

        with multi_col:
            default_multi_dates = available_dates[-2:] if len(available_dates) >= 2 else available_dates
            selected_dates = st.multiselect(
                "Show problems for multiple report days",
                options=available_dates,
                default=default_multi_dates,
                format_func=format_report_date,
                help="Select one or more report dates from the current vessel/source window.",
            )

        day_errors = errors_scope[errors_scope["report_date"].eq(selected_date)].copy() if not errors_scope.empty else errors_scope.copy()
        display_error_table(f"Problems for {format_report_date(selected_date)}", day_errors)

        if selected_dates:
            multi_errors = errors_scope[errors_scope["report_date"].isin(selected_dates)].copy() if not errors_scope.empty else errors_scope.copy()
            selected_dates_label = ", ".join(format_report_date(d) for d in selected_dates)
            display_error_table("Problems for selected report days", multi_errors)
            st.caption(f"Selected report days: {selected_dates_label}")
        else:
            st.info("Select one or more report days to see a combined problem table.")

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

    errors_export_scope = add_copy_paste_issue_messages(errors_scope, selected_vessel)
    recent_errors_export_scope = add_copy_paste_issue_messages(recent_errors_scope, selected_vessel)
    captain_message_subject = build_captain_chief_engineer_subject(errors_scope, selected_vessel)
    captain_message_text = build_captain_chief_engineer_message(errors_scope, selected_vessel)
    captain_message_export = build_captain_message_df(errors_scope, selected_vessel)

    combined_for_export = dict(combined)
    combined_for_export["errors"] = errors_export_scope
    combined_for_export["checked_rows"] = checked_rows_scope
    combined_for_export["by_rule"] = by_rule_scope
    combined_for_export["portfolio_summary"] = build_portfolio_summary(checked_rows_scope, errors_scope)
    combined_for_export["recent_errors"] = recent_errors_export_scope
    combined_for_export["daily_kpis"] = daily_kpis_scope
    combined_for_export["by_severity"] = by_severity_scope
    combined_for_export["status_summary"] = status_summary_scope
    combined_for_export["captain_message"] = captain_message_export

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
        data=errors_export_scope.to_csv(index=False).encode("utf-8-sig"),
        file_name="noon_report_errors_current_selection.csv",
        mime="text/csv",
        use_container_width=True,
    )

    st.download_button(
        "Download selected data-window errors as CSV",
        data=recent_errors_export_scope.to_csv(index=False).encode("utf-8-sig"),
        file_name="noon_report_errors_selected_data_window.csv",
        mime="text/csv",
        use_container_width=True,
    )

    st.divider()
    st.subheader("Copy-paste message to Captain / Chief Engineer")
    st.caption(
        "This message uses the current vessel/rule/date filters already applied in the dashboard. "
        "Adjust the filters if the message contains too many issues."
    )

    if errors_scope.empty:
        st.success("No validation issues were found for the current filtered selection.")
    else:
        st.info(f"Message includes {len(errors_scope)} issue(s) from the current filtered selection.")

    st.text_input("Suggested subject", value=captain_message_subject)
    st.text_area("Copy-ready message", value=captain_message_text, height=460)
    st.download_button(
        "Download Captain / Chief Engineer message as TXT",
        data=f"Subject: {captain_message_subject}\n\n{captain_message_text}".encode("utf-8-sig"),
        file_name="noon_report_captain_chief_engineer_message.txt",
        mime="text/plain",
        use_container_width=True,
    )
