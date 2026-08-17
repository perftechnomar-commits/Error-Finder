from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
import json
import os
from typing import Any, Mapping
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from requests.auth import HTTPBasicAuth, HTTPDigestAuth

try:  # The module is also testable outside Streamlit.
    import streamlit as st
except ImportError:  # pragma: no cover
    st = None  # type: ignore[assignment]


DEFAULT_ENDPOINT = "https://online.marorka.com/Odata/v1/ODataService.svc/ReportData"
DEFAULT_LOOKBACK_DAYS = 5
DEFAULT_TIMEOUT_SECONDS = 90
DEFAULT_MAX_PAGES = 1000
DEFAULT_CACHE_TTL_SECONDS = 172800  # 48-hour safety expiry; refresh generation controls cadence.
DEFAULT_TIME_ZONE = ZoneInfo("Europe/Athens")

EXCLUDED_REPORT_TYPES = {"Intake Report", "Fuel Change Report"}

# Only the columns that survive the early Power Query RemoveColumns step are
# requested.  Every report variable is still returned through ValueDescription /
# ReportedValue and then pivoted into a column.
SOURCE_COLUMNS = [
    "ReportId",
    "ShipName",
    "ReportType",
    "StartDateTimeGMT",
    "EndDateTimeGMT",
    "LapTime",
    "StateName",
    "ValueDescription",
    "ReportedValue",
]

ME_FUEL_COLUMNS = [
    "Main Engine - HSHFO",
    "Main Engine - HSLFO",
    "Main Engine - MGO",
    "Main Engine - ULSHFO",
    "Main Engine - ULSLFO",
    "Main Engine - VLSHFO",
    "Main Engine - VLSLFO",
]
DG_FUEL_COLUMNS = [
    "Diesel Generators - HSHFO",
    "Diesel Generators - HSLFO",
    "Diesel Generators - MGO",
    "Diesel Generators - ULSHFO",
    "Diesel Generators - ULSLFO",
    "Diesel Generators - VLSHFO",
    "Diesel Generators - VLSLFO",
]
BOILER_FUEL_COLUMNS = [
    "Boiler - HSHFO",
    "Boiler - HSLFO",
    "Boiler - MGO",
    "Boiler - ULSHFO",
    "Boiler - ULSLFO",
    "Boiler - VLSHFO",
    "Boiler - VLSLFO",
]
ROB_COLUMNS = [
    "ROB_HSHFO",
    "ROB_HSLFO",
    "ROB_MGO",
    "ROB_ULSHFO",
    "ROB_ULSLFO",
    "ROB_VLSHFO",
    "ROB_VLSLFO",
]
DG_RUNNING_HOUR_COLUMNS = [
    "DG1 Running Hours [hh:mm]",
    "DG2 Running Hours [hh:mm]",
    "DG3 Running Hours [hh:mm]",
    "DG4 Running Hours [hh:mm]",
    "Shaft Generator Running Hours [hh:mm]",
]

# Default Fleet_Vessel replacement.  An optional JSON mapping in Streamlit
# Secrets can override or extend this without changing code.
DEFAULT_FLEET_GROUPS: dict[str, list[str]] = {
    "Fleet 1": [
        "ATETI", "CMA CGM THALASSA", "CZECH", "DOLPHIN II",
        "GSL CHRISTEL ELISABETH", "GSL VINIA", "ORCA I", "MYNY",
        "SYDNEY EXPRESS",
    ],
    "Fleet 2": [
        "AGIOS DIMITRIOS", "CONSTANTINOS P II", "ELENI T", "MAIRA",
        "MELINA", "NEWYORKER", "NIKOLAS", "TORRANCE",
    ],
    "Fleet 3": [
        "BREMERHAVEN EXPRESS", "CMA CGM ALCAZAR", "GSL ALICE",
        "GSL CHATEAU D'IF", "GSL ELEFTHERIA", "GSL MAREN", "GSL MELINA",
        "ISTANBUL EXPRESS",
    ],
    "Fleet 4": [
        "ANTHEA Y", "COLOMBIA EXPRESS", "COSTA RICA EXPRESS",
        "JAMAICA EXPRESS", "MEXICO EXPRESS", "NICARAGUA EXPRESS",
        "PANAMA EXPRESS", "ZIM NORFOLK", "ZIM XIAMEN",
    ],
    "Fleet 9": [
        "CMA CGM AMERICA", "CMA CGM SAMBHAR", "GSL ELENI", "GSL GRANIA",
        "GSL KALLIOPI", "GSL NINGBO", "MSC QINGDAO", "MSC TIANJIN",
    ],
    "Fleet 10": [
        "CAPTAIN THANASIS I", "CMA CGM JAMAICA", "GSL CHRISTEN",
        "GSL NICOLETTA", "GSL VALERIE", "JULIE", "KUMASI", "MANET",
    ],
    "Fleet 11": [
        "ATHENA I", "EPAMINONDAS", "IAN H", "MARIANNA I", "MSC ROMA",
        "TINA I",
    ],
    "Fleet 12": [
        "GSL DOROTHEA", "GSL KITHIRA", "GSL MARIA", "GSL MELITA",
        "GSL SYROS", "GSL TEGEA", "GSL TINOS", "GSL TRIPOLI",
    ],
    "Fleet 14": [
        "GSL CHLOE", "GSL ELIZABETH", "GSL MAMITSA", "GSL MERCER",
        "GSL ROSSI", "GSL SUSAN", "TONSBERG",
    ],
    "Fleet 15": [
        "GSL ALEXANDRA", "GSL ARCADIA", "GSL EFFIE", "GSL LYDIA",
        "GSL MYNY", "GSL SOFIA", "GSL VIOLETTA", "KOSTAS K", "MARIA Y",
    ],
}

RENAME_COLUMNS = {
    "ReportType": "Report Type",
    "StartDateTimeGMT": "Start Date & Time GMT",
    "EndDateTimeGMT": "End Date & Time GMT",
    "LapTime": "Time Since Last Report",
    "StateName": "State Name",
    "ETD [dd:mm:yyyy hh:mm]": "Estimated Time of Departure [dd:mm:yyyy hh:mm]",
    "ETA to Next Port  [dd:mm:yyyy hh:mm]": "Estimated Time of Arrival to Next Port  [dd:mm:yyyy hh:mm]",
    "Draft Forward [m] (m)": "Draft Forward [m]",
    "Draft Aft [m] (m)": "Draft Aft [m]",
    "Shaft 1 RPM (rpm)": "ME Shaft RPM [RPM]",
    "Consumption ME 24 Hours": "Consumption ME 24 Hours [MT]",
    "Consumption DGs 24 Hours": "Consumption DGs 24 Hours [MT]",
    "Consumption Boiler 24 Hours": "Consumption Boiler 24 Hours [MT]",
    "Total Consumption 24 Hours": "Total Consumption 24 Hours [MT]",
    "Main Engine - HSHFO": "Main Engine - HSHFO consumption [MT]",
    "Diesel Generators - HSHFO": "Diesel Generator - HSHFO consumption [MT]",
    "Boiler - HSHFO": "Boiler - HSHFO consumption [MT]",
    "Main Engine - HSLFO": "Main Engine - HSLFO consumption [MT]",
    "Diesel Generators - HSLFO": "Diesel Generator - HSLFO consumption [MT]",
    "Boiler - HSLFO": "Boiler - HSLFO consumption [MT]",
    "Main Engine - MGO": "Main Engine - MGO consumption [MT]",
    "Diesel Generators - MGO": "Diesel Generator - MGO consumption [MT]",
    "Boiler - MGO": "Boiler - MGO consumption [MT]",
    "Main Engine - ULSHFO": "Main Engine - ULSHFO consumption [MT]",
    "Diesel Generators - ULSHFO": "Diesel Generator - ULSHFO consumption [MT]",
    "Boiler - ULSHFO": "Boiler - ULSHFO consumption [MT]",
    "Main Engine - ULSLFO": "Main Engine - ULSLFO consumption [MT]",
    "Diesel Generators - ULSLFO": "Diesel Generator - ULSLFO consumption [MT]",
    "Boiler - ULSLFO": "Boiler - ULSLFO consumption [MT]",
    "Main Engine - VLSHFO": "Main Engine - VLSHFO consumption [MT]",
    "Diesel Generators - VLSHFO": "Diesel Generator - VLSHFO consumption [MT]",
    "Boiler - VLSHFO": "Boiler - VLSHFO consumption [MT]",
    "Main Engine - VLSLFO": "Main Engine - VLSLFO consumption [MT]",
    "Diesel Generators - VLSLFO": "Diesel Generator - VLSLFO consumption [MT]",
    "Boiler - VLSLFO": "Boiler - VLSLFO consumption [MT]",
    "ROB_HSHFO": "ROB HSHFO [MT]",
    "ROB_HSLFO": "ROB HSLFO [MT]",
    "ROB_MGO": "ROB MGO [MT]",
    "ROB_ULSHFO": "ROB ULSHFO [MT]",
    "ROB_ULSLFO": "ROB ULSLFO [MT]",
    "ROB_VLSHFO": "ROB VLSHFO [MT]",
    "ROB_VLSLFO": "ROB VLSLFO [MT]",
    "HFO Consumption Equivalent": "HFO Consumption Equivalent [MT]",
    "Current Speed Calculated": "Current Speed Calculated [kn]",
    "Water speed [kn Log] (kn)": "Speed Through Water [kn Log]",
    "Speed over ground [kn GPS] (kn)": "Speed over ground [kn GPS]",
    "Total DG Power [kW] (kW)": "Total DG Power [kW]",
    "Load per Generator %": "Load per Generator [% MCR]",
    "Total Number Reefer Units (20 and 40ft)": "Total Number Reefer Units (20ft and 40ft)",
    "Ships Alongside": "Ship Alongside",
    "Total Number DG Units (20 and 40ft)": "Total Number DG Units (20ft and 40ft)",
    "Total Number Empty Units (20 and 40ft)": "Total Number Empty Units (20ft and 40ft)",
    "Total Empty Units Weight (20 and 40ft) [tons]": "Total Empty Units Weight (20ft and 40ft) [tons]",
    "Total Number Full Units (20 and 40ft)": "Total Number Full Units (20ft and 40ft)",
    "Total Full Units Weight (20 and 40ft) [tons]": "Total Full Units Weight (20ft and 40ft) [tons]",
    "Heading [COG] [0 - 360°] (°)": "Heading [COG] [0 - 360°]",
}

# The validator's key fields first; every other pivoted API field is retained after
# these columns, so downstream rules and ad-hoc inspection continue to work.
PREFERRED_OUTPUT_COLUMNS = [
    "ReportId", "ShipName", "Fleet", "Report Type", "Start Date & Time GMT",
    "End Date & Time GMT", "Time Since Last Report", "State Name",
    "Position (HHMMSS)", "Voyage Number",
    "Estimated Time of Arrival to Next Port  [dd:mm:yyyy hh:mm]",
    "Estimated Time of Berthing [dd:mm:yyyy hh:mm]",
    "Estimated Time of Departure [dd:mm:yyyy hh:mm]",
    "Steaming Time Since Last Report [hh:mm]", "Draft Forward [m]",
    "Draft Aft [m]", "Average Draft [m]", "Trim [m]", "Slip Average [%]",
    "Calculated Slip", "ME Shaft RPM [RPM]", "Corrected Speed for 7% Slip",
    "Consumption ME 24 Hours [MT]", "Consumption DGs 24 Hours [MT]",
    "Consumption Boiler 24 Hours [MT]", "Total Consumption 24 Hours [MT]",
    "ROB MGO [MT]", "HFO Consumption Equivalent [MT]",
    "Engine Miles Calculated [RPM]", "Engine Miles Calculated [Rev]",
    "Engine Distance [nm]", "Distance Over Ground [nm]",
    "Distance Through Water [nm]", "Miles to Go [nm]", "ME Load [%MCR]",
    "Wind Speed [bft]", "Current Speed Calculated [kn]",
    "Speed over ground [kn GPS]", "Speed Through Water [kn Log]",
    "Total DG Power [kW]", "DG1 Running Hours [hh:mm]",
    "DG2 Running Hours [hh:mm]", "DG3 Running Hours [hh:mm]",
    "DG4 Running Hours [hh:mm]", "Shaft Generator Running Hours [hh:mm]",
    "Load per Generator Calculated", "Load per Generator [% MCR]",
    "Power from Torque Meter [kW]", "SFOC [gr/Kwh]", "Estimated Reefer Load",
    "FW Produced [cbm]", "FW Consumed [cbm]", "Sludge Produced [cbm]",
    "Sludge Incinerated / Evaporated [cbm]", "Difference Percentage",
]


class MarorkaSourceError(RuntimeError):
    """Readable source error intended for the Streamlit UI."""


@dataclass(frozen=True)
class MarorkaApiConfig:
    endpoint: str = DEFAULT_ENDPOINT
    username: str = ""
    password: str = ""
    token: str = ""
    auth_method: str = "basic"
    lookback_days: int = DEFAULT_LOOKBACK_DAYS
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    max_pages: int = DEFAULT_MAX_PAGES
    fleet_groups: Mapping[str, list[str]] | None = None

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any] | None = None) -> "MarorkaApiConfig":
        values = values or {}

        def get(name: str, default: Any = "") -> Any:
            value = values.get(name, os.getenv(name, default))
            return default if value is None else value

        fleet_groups: Mapping[str, list[str]] | None = None
        raw_fleet_map = get("FLEET_VESSEL_MAP_JSON", "")
        if raw_fleet_map:
            try:
                parsed = json.loads(str(raw_fleet_map))
                if not isinstance(parsed, dict):
                    raise TypeError("top level must be an object")
                fleet_groups = {
                    str(fleet): [str(vessel) for vessel in vessels]
                    for fleet, vessels in parsed.items()
                    if isinstance(vessels, list)
                }
            except (json.JSONDecodeError, TypeError) as exc:
                raise MarorkaSourceError(
                    "FLEET_VESSEL_MAP_JSON is not valid JSON in the form "
                    '{"Fleet 1": ["VESSEL A", "VESSEL B"]}.'
                ) from exc

        return cls(
            endpoint=str(get("MARORKA_API_URL", get("MARORKA_ODATA_ENDPOINT", DEFAULT_ENDPOINT))).strip(),
            username=str(get("MARORKA_USERNAME", "")).strip(),
            password=str(get("MARORKA_PASSWORD", "")).strip(),
            token=str(get("MARORKA_TOKEN", "")).strip(),
            auth_method=str(get("MARORKA_AUTH_METHOD", "basic")).strip().lower(),
            lookback_days=int(get("MARORKA_LOOKBACK_DAYS", DEFAULT_LOOKBACK_DAYS)),
            timeout_seconds=int(get("MARORKA_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)),
            max_pages=int(get("MARORKA_MAX_PAGES", DEFAULT_MAX_PAGES)),
            fleet_groups=fleet_groups,
        )


class MemoryUploadedFile:
    """Uploaded-file-compatible wrapper for the existing validation pipeline."""

    def __init__(self, name: str, data: bytes) -> None:
        self.name = name
        self._data = data

    def getvalue(self) -> bytes:
        return self._data


@dataclass(frozen=True)
class DepartmentApiResult:
    dataframe: pd.DataFrame
    excel_bytes: bytes
    raw_rows: int
    report_rows: int
    start_date: date
    end_date_exclusive: date
    pulled_at_utc: datetime


def _request_auth(config: MarorkaApiConfig) -> Any:
    if config.auth_method == "basic":
        if not config.username or not config.password:
            raise MarorkaSourceError(
                "MARORKA_USERNAME and MARORKA_PASSWORD are required for basic authentication."
            )
        return HTTPBasicAuth(config.username, config.password)
    if config.auth_method == "digest":
        if not config.username or not config.password:
            raise MarorkaSourceError(
                "MARORKA_USERNAME and MARORKA_PASSWORD are required for digest authentication."
            )
        return HTTPDigestAuth(config.username, config.password)
    if config.auth_method in {"bearer", "none", "anonymous", ""}:
        return None
    raise MarorkaSourceError(
        "Unsupported MARORKA_AUTH_METHOD. Use basic, digest, bearer, or none."
    )


def _request_headers(config: MarorkaApiConfig) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if config.auth_method == "bearer":
        if not config.token:
            raise MarorkaSourceError("MARORKA_TOKEN is required for bearer authentication.")
        headers["Authorization"] = f"Bearer {config.token}"
    return headers


def _extract_odata_page(payload: Any) -> tuple[list[dict[str, Any]], str | None]:
    if isinstance(payload, list):
        return payload, None
    if not isinstance(payload, dict):
        raise MarorkaSourceError("The Marorka API returned an unexpected JSON structure.")

    rows = payload.get("value")
    next_link = payload.get("@odata.nextLink") or payload.get("odata.nextLink")
    if rows is None and isinstance(payload.get("d"), dict):
        legacy = payload["d"]
        rows = legacy.get("results")
        next_link = next_link or legacy.get("__next")
    if rows is None:
        raise MarorkaSourceError("Could not find OData rows in the Marorka response.")
    if not isinstance(rows, list):
        raise MarorkaSourceError("The OData row payload is not a list.")
    return rows, str(next_link) if next_link else None


def fetch_reportdata_rows(
    config: MarorkaApiConfig,
    *,
    today: date | None = None,
    session: requests.Session | None = None,
) -> tuple[list[dict[str, Any]], date, date]:
    """Fetch the same dynamic window as the Power Query: today-5 to tomorrow."""
    today = today or datetime.now(DEFAULT_TIME_ZONE).date()
    start_date = today - timedelta(days=config.lookback_days)
    end_date_exclusive = today + timedelta(days=1)

    params = {
        "$filter": (
            f"StartDateTimeGMT ge DateTime'{start_date:%Y-%m-%d}' "
            f"and StartDateTimeGMT lt DateTime'{end_date_exclusive:%Y-%m-%d}'"
        ),
        "$select": ",".join(SOURCE_COLUMNS),
        "$orderby": "StartDateTimeGMT desc",
        "$format": "json",
    }

    client = session or requests.Session()
    auth = _request_auth(config)
    headers = _request_headers(config)
    next_url: str | None = config.endpoint
    next_params: Mapping[str, str] | None = params
    rows: list[dict[str, Any]] = []

    for page_number in range(1, config.max_pages + 1):
        if not next_url:
            break
        try:
            response = client.get(
                next_url,
                params=next_params,
                auth=auth,
                headers=headers,
                timeout=config.timeout_seconds,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise MarorkaSourceError(
                f"Marorka ReportData request failed on page {page_number}: {exc}"
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            snippet = response.text[:300].replace("\n", " ")
            raise MarorkaSourceError(
                f"Marorka returned non-JSON content: {snippet}"
            ) from exc

        page_rows, next_link = _extract_odata_page(payload)
        rows.extend(page_rows)
        next_url = urljoin(response.url, next_link) if next_link else None
        next_params = None  # nextLink already contains its own OData query.
    else:
        raise MarorkaSourceError(
            f"Stopped after MARORKA_MAX_PAGES={config.max_pages}; pagination may be incomplete."
        )

    return rows, start_date, end_date_exclusive


def _numeric(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(float("nan"), index=df.index, dtype="float64")
    source = df[column]
    if pd.api.types.is_timedelta64_dtype(source):
        return source.dt.total_seconds() / 3600.0
    # Excel/PQ duration-like values may arrive as HH:MM strings.  Numeric strings
    # remain numeric; HH:MM[:SS] strings are converted to decimal hours.
    numeric = pd.to_numeric(source, errors="coerce")
    unresolved = numeric.isna() & source.notna()
    if unresolved.any():
        text = source.astype(str).str.strip()
        duration_mask = unresolved & text.str.match(r"^-?\d{1,4}:\d{2}(?::\d{2}(?:\.\d+)?)?$", na=False)
        if duration_mask.any():
            sign = text.loc[duration_mask].str.startswith("-").map({True: -1.0, False: 1.0})
            clean = text.loc[duration_mask].str.lstrip("-")
            parts = clean.str.split(":", expand=True).astype(float)
            hours = parts[0] + parts[1] / 60.0
            if parts.shape[1] > 2:
                hours = hours + parts[2] / 3600.0
            numeric.loc[duration_mask] = hours * sign
    return numeric.astype("float64")


def _sum_columns(df: pd.DataFrame, columns: list[str]) -> pd.Series:
    values = pd.concat([_numeric(df, column).rename(column) for column in columns], axis=1)
    # Power Query List.Sum ignores nulls and returns zero when every item is null.
    return values.sum(axis=1, skipna=True)


def _safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    result = numerator.astype("float64").div(denominator.astype("float64"))
    return result.where(denominator.notna() & denominator.ne(0))


def _fleet_lookup(groups: Mapping[str, list[str]] | None) -> dict[str, str]:
    groups = groups or DEFAULT_FLEET_GROUPS
    lookup: dict[str, str] = {}
    for fleet, vessels in groups.items():
        for vessel in vessels:
            lookup[str(vessel).strip().upper()] = str(fleet)
    return lookup


def pivot_reportdata(raw_rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Mirror Table.Pivot(..., ReportedValue, List.First)."""
    if not raw_rows:
        return pd.DataFrame(columns=SOURCE_COLUMNS[:-2])

    raw = pd.DataFrame(raw_rows)
    for column in SOURCE_COLUMNS:
        if column not in raw.columns:
            raw[column] = pd.NA

    raw = raw[raw["ValueDescription"].notna()].copy()
    raw = raw[~raw["ReportType"].isin(EXCLUDED_REPORT_TYPES)].copy()
    if raw.empty:
        return pd.DataFrame(columns=SOURCE_COLUMNS[:-2])

    key_columns = [column for column in SOURCE_COLUMNS if column not in {"ValueDescription", "ReportedValue"}]

    # Keep exact API order and select the first item, including a possible null,
    # rather than pandas' default GroupBy.first which skips nulls.
    deduplicated = raw.drop_duplicates(
        subset=key_columns + ["ValueDescription"], keep="first"
    )
    wide = deduplicated.pivot(
        index=key_columns,
        columns="ValueDescription",
        values="ReportedValue",
    ).reset_index()
    wide.columns.name = None
    return wide


def apply_power_query_logic(
    wide: pd.DataFrame,
    *,
    fleet_groups: Mapping[str, list[str]] | None = None,
) -> pd.DataFrame:
    """Apply the derived-column, percentage and rename logic from All vessels.xlsx."""
    df = wide.copy()
    if df.empty:
        for column in PREFERRED_OUTPUT_COLUMNS:
            if column not in df.columns:
                df[column] = pd.Series(dtype="object")
        return df[PREFERRED_OUTPUT_COLUMNS]

    lookup = _fleet_lookup(fleet_groups)
    ship_upper = df.get("ShipName", pd.Series("", index=df.index)).astype(str).str.strip().str.upper()
    df["Fleet"] = ship_upper.map(lookup)

    # Draft / slip / corrected speed.
    draft_forward = _numeric(df, "Draft Forward [m] (m)")
    draft_aft = _numeric(df, "Draft Aft [m] (m)")
    df["Average Draft [m]"] = pd.concat([draft_forward, draft_aft], axis=1).mean(axis=1, skipna=True).round(3)

    engine_distance = _numeric(df, "Engine Distance [nm]")
    distance_over_ground = _numeric(df, "Distance Over Ground [nm]")
    df["Calculated Slip"] = (1.0 - _safe_divide(distance_over_ground, engine_distance)).round(3)

    shaft_rpm = _numeric(df, "Shaft 1 RPM (rpm)")
    df["Corrected Speed for 7% Slip"] = (shaft_rpm * 0.030123 * 8.2220).round(3)

    lap_time = _numeric(df, "LapTime")
    me_24 = _safe_divide(_sum_columns(df, ME_FUEL_COLUMNS) * 24.0, lap_time).round(3)
    dg_24 = _safe_divide(_sum_columns(df, DG_FUEL_COLUMNS) * 24.0, lap_time).round(3)
    boiler_24 = _safe_divide(_sum_columns(df, BOILER_FUEL_COLUMNS) * 24.0, lap_time).round(3)
    df["Consumption ME 24 Hours"] = me_24
    df["Consumption DGs 24 Hours"] = dg_24
    df["Consumption Boiler 24 Hours"] = boiler_24
    df["Total Consumption 24 Hours"] = pd.concat([me_24, dg_24, boiler_24], axis=1).sum(axis=1, skipna=True).round(3)

    torque_power = _numeric(df, "Power from Torque Meter [kW]")
    sfoc = _safe_divide(me_24, torque_power) / 2.4e-05
    df["SFOC [gr/Kwh]"] = sfoc.fillna(0).round(3)

    hfo_columns = [
        "Main Engine - HSHFO", "Diesel Generators - HSHFO", "Boiler - HSHFO",
        "Main Engine - VLSHFO", "Diesel Generators - VLSHFO", "Boiler - VLSHFO",
        "Main Engine - ULSHFO", "Diesel Generators - ULSHFO", "Boiler - ULSHFO",
    ]
    lfo_columns = [
        "Main Engine - HSLFO", "Diesel Generators - HSLFO", "Boiler - HSLFO",
        "Main Engine - VLSLFO", "Diesel Generators - VLSLFO", "Boiler - VLSLFO",
        "Main Engine - ULSLFO", "Diesel Generators - ULSLFO", "Boiler - ULSLFO",
    ]
    mgo_columns = ["Main Engine - MGO", "Diesel Generators - MGO", "Boiler - MGO"]
    total_hfo = _sum_columns(df, hfo_columns)
    total_lfo = _sum_columns(df, lfo_columns) / 0.9481
    total_mgo = _sum_columns(df, mgo_columns) / 0.9415
    df["HFO Consumption Equivalent"] = (total_hfo + total_lfo + total_mgo).round(3)

    df["Engine Miles Calculated [RPM]"] = (shaft_rpm * 0.032397 * lap_time * 8.2220).fillna(0).round(3)
    df["Engine Miles Calculated [Rev]"] = (_numeric(df, "ME Rev Since Last Report") / 1852.0 * 8.2220).round(3)

    water_speed = _numeric(df, "Water speed [kn Log] (kn)")
    gps_speed = _numeric(df, "Speed over ground [kn GPS] (kn)")
    state_name = df.get("StateName", pd.Series(pd.NA, index=df.index))
    current_speed = (water_speed - gps_speed).where(state_name.eq("Sea Passage"))
    df["Current Speed Calculated"] = current_speed.fillna(0).round(3)

    total_running_hours = _sum_columns(df, DG_RUNNING_HOUR_COLUMNS)
    load_per_generator = _safe_divide(_numeric(df, "Total DG Power [kW] (kW)"), total_running_hours) * lap_time
    df["Load per Generator Calculated"] = load_per_generator.round(3)
    df["Load per Generator %"] = (load_per_generator / 2900.0).round(3)

    reefers = (_numeric(df, "20ft Reefer Units") + _numeric(df, "40ft Reefer Units")) * 1.66
    df["Reefers Onboard 20ft Equivalent"] = reefers.fillna(0).round(3)
    df["Estimated Reefer Load"] = (df["Reefers Onboard 20ft Equivalent"] * 3.0).round(3)

    corrected_speed = _numeric(df, "Corrected Speed for 7% Slip")

    def cp_consumption(speed: pd.Series) -> pd.Series:
        return (
            -0.002695939 * speed.pow(3)
            + 0.38073932 * speed.pow(2)
            - 1.884501436 * speed
        )

    cp = cp_consumption(corrected_speed).fillna(0).round(3)
    df["For Corrected Speed CP Consumption is"] = cp
    df["Difference from Actual"] = cp - me_24
    diff_pct = (1.0 - _safe_divide(cp, me_24)).where(cp.gt(0))
    df["Difference Percentage"] = diff_pct.where(diff_pct.ne(0))

    cp_plus = cp_consumption(corrected_speed + 0.5).fillna(0).round(3)
    df["For Corrected Speed with + 0.5 kn for on about CP Consumption is"] = cp_plus
    df["Difference from Actual2"] = cp_plus - me_24
    diff_pct2 = (1.0 - _safe_divide(cp_plus, me_24)).where(cp_plus.gt(0))
    df["Difference Percentage2"] = diff_pct2.where(diff_pct2.ne(0))

    cp_plus_5 = (cp_plus * 1.05).round(3)
    df["For Corrected Speed with + 0.5 kn + 5% for both on abouts CP Consumption is"] = cp_plus_5
    df["Difference from Actual3"] = (cp_plus_5 - me_24).round(3)
    diff_pct3 = (1.0 - _safe_divide(cp_plus_5, _numeric(df, "Total Consumption 24 Hours"))).where(cp_plus_5.gt(0))
    df["Difference Percentage3"] = diff_pct3.where(diff_pct3.ne(0))

    # Final Power Query percentage scaling.
    for column in [
        "Slip Average [%]", "ME Load [%MCR]", "DG1 Load [% MCR]",
        "DG2 Load [% MCR]", "DG3 Load [% MCR]", "DG4 Load [% MCR]",
        "Bending Moments [%]", "Shearing Forces [%]", "Torsional Moments [%]",
    ]:
        if column in df.columns:
            df[column] = _numeric(df, column) / 100.0

    df = df.rename(columns={old: new for old, new in RENAME_COLUMNS.items() if old in df.columns})

    for datetime_column in ["Start Date & Time GMT", "End Date & Time GMT"]:
        if datetime_column in df.columns:
            df[datetime_column] = pd.to_datetime(df[datetime_column], errors="coerce", utc=True).dt.tz_localize(None)

    # The M query replaces ReportId=0 with null and zero difference percentages with null.
    if "ReportId" in df.columns:
        report_id_numeric = pd.to_numeric(df["ReportId"], errors="coerce")
        df.loc[report_id_numeric.eq(0), "ReportId"] = pd.NA
    for column in ["Difference Percentage", "Difference Percentage2", "Difference Percentage3"]:
        if column in df.columns:
            numeric = pd.to_numeric(df[column], errors="coerce")
            df.loc[numeric.eq(0), column] = pd.NA

    if "Start Date & Time GMT" in df.columns:
        df = df.sort_values("Start Date & Time GMT", ascending=False, kind="stable")

    ordered = [column for column in PREFERRED_OUTPUT_COLUMNS if column in df.columns]
    remaining = [column for column in df.columns if column not in ordered]
    return df[ordered + remaining].reset_index(drop=True)


def dataframe_to_excel_bytes(df: pd.DataFrame) -> bytes:
    """Create the same worksheet shape consumed by read_noon_excel()."""
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl", datetime_format="yyyy-mm-dd hh:mm:ss") as writer:
        df.to_excel(writer, sheet_name="Table", index=False)
        worksheet = writer.sheets["Table"]
        worksheet.freeze_panes = "A2"
        worksheet.auto_filter.ref = worksheet.dimensions
    return output.getvalue()


def build_department_api_result(
    config: MarorkaApiConfig,
    *,
    today: date | None = None,
    session: requests.Session | None = None,
) -> DepartmentApiResult:
    rows, start_date, end_date_exclusive = fetch_reportdata_rows(
        config, today=today, session=session
    )
    wide = pivot_reportdata(rows)
    transformed = apply_power_query_logic(
        wide,
        fleet_groups=config.fleet_groups,
    )
    return DepartmentApiResult(
        dataframe=transformed,
        excel_bytes=dataframe_to_excel_bytes(transformed),
        raw_rows=len(rows),
        report_rows=len(transformed),
        start_date=start_date,
        end_date_exclusive=end_date_exclusive,
        pulled_at_utc=datetime.now(timezone.utc),
    )


def _streamlit_secrets_mapping() -> Mapping[str, Any]:
    if st is None:
        return os.environ
    try:
        return st.secrets
    except Exception:
        return os.environ


def _uncached_streamlit_result(refresh_token: str | int = 0) -> DepartmentApiResult:
    del refresh_token  # cache-busting input only
    config = MarorkaApiConfig.from_mapping(_streamlit_secrets_mapping())
    return build_department_api_result(config)


if st is not None:
    # API results are cached so ordinary Streamlit reruns (filters, tabs, selectboxes)
    # do not hit Marorka again. The app changes the shared refresh generation only
    # when an explicit API refresh is requested (scheduler or Reload API button).
    fetch_department_api_result = st.cache_data(
        ttl=DEFAULT_CACHE_TTL_SECONDS,
        show_spinner=False,
    )(_uncached_streamlit_result)

    @st.cache_resource(show_spinner=False)
    def _department_api_refresh_state() -> dict[str, int]:
        # cache_resource is shared by all sessions in the running Streamlit process.
        return {"generation": 0}
else:  # pragma: no cover
    fetch_department_api_result = _uncached_streamlit_result
    _NON_STREAMLIT_REFRESH_STATE = {"generation": 0}

    def _department_api_refresh_state() -> dict[str, int]:
        return _NON_STREAMLIT_REFRESH_STATE


def get_department_api_refresh_generation() -> int:
    """Return the shared API refresh generation used as the cache key."""
    return int(_department_api_refresh_state()["generation"])


def request_department_api_refresh() -> int:
    """Invalidate the cached API result and advance the shared refresh generation.

    Call this exactly when a real source refresh is required (for example, from a
    scheduler-triggered Streamlit session or the manual Reload API button). Normal
    widget reruns should only read the current generation.
    """
    state = _department_api_refresh_state()
    state["generation"] = int(state.get("generation", 0)) + 1

    clear_method = getattr(fetch_department_api_result, "clear", None)
    if callable(clear_method):
        clear_method()

    return int(state["generation"])


def build_department_uploaded_file(refresh_token: str | int = 0) -> tuple[MemoryUploadedFile, DepartmentApiResult]:
    result = fetch_department_api_result(refresh_token)
    file_name = (
        f"API_All_vessels_{result.start_date:%Y%m%d}_"
        f"{(result.end_date_exclusive - timedelta(days=1)):%Y%m%d}.xlsx"
    )
    return MemoryUploadedFile(file_name, result.excel_bytes), result
