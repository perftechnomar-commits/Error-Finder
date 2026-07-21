from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from io import BytesIO
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd


# Default thresholds copied from the ANTHEA Y adaptation of Error Finder v2.25.
DEFAULT_CONFIG: Dict[str, Any] = {
    "date_max_days_ahead": 1,
    "low_steaming_hours": 8.0,
    "low_fw_steaming_hours": 20.0,
    "slip_min": -0.07,
    "slip_max": 0.20,
    "me_load_min": 0.10,
    "me_load_max": 1.00,
    "electric_load_min_kw": 100.0,
    "electric_load_max_kw": 7000.0,
    "sfoc_min": 160.0,
    "sfoc_max": 280.0,
    "torque_power_min_kw": 3400.0,
    "torque_power_max_kw": 40000.0,
    "fw_produced_min_cbm": 10.0,
    "fw_consumed_max_cbm": 10.0,
    "sludge_factor_of_total_consumption": 0.015,
    "mgo_rob_min_mt": 50.0,
    "difference_pct_clean_min": -0.60,
    "difference_pct_clean_max": 0.70,
    "difference_pct_avg_band": 0.13,
    "difference_pct_min_count": 20,
    "distance_tolerance_pct": 0.05,
    "boiler_cons_max_mt": 5.0,
    "dg_cons_high_mt": 13.0,
    "dg_cons_low_mt": 1.0,
    "dg_sfc_g_per_kwh": 220.0,
    "dg_cons_vs_load_buffer_mt": 2.0,
    "dg_power_running_threshold_kw": 10.0,
    "dg_optimization_load_factor": 0.70,
}

COLUMN_ALIASES: Dict[str, List[str]] = {
    "report_id": ["ReportId", "Report ID"],
    "ship_name": ["ShipName", "Ship Name", "Vessel"],
    "fleet": ["Fleet", "Fleet Group", "FleetGroup"],
    "report_type": ["Report Type"],
    "start_gmt": ["Start Date & Time GMT", "Start Date Time GMT", "Start GMT"],
    "end_gmt": ["End Date & Time GMT", "End Date Time GMT", "End GMT"],
    "time_since_last": ["Time Since Last Report"],
    "state_name": ["State Name", "State"],
    "steaming_time": ["Steaming Time Since Last Report [hh:mm]", "Steaming Time Since Last Report", "Steaming Time"],
    "calculated_slip": ["Calculated Slip", "Slip"],
    "wind_force": ["Wind Speed [bft]", "Wind Force", "Wind Force [bft]"],
    "me_load": ["ME Load [%MCR]", "ME Load %MCR", "MCR", "ME Load"],
    "total_dg_power": ["Total DG Power [kW]", "Total DG Power", "Electric Load"],
    "dg1_hours": ["DG1 Running Hours [hh:mm]", "DG1 Running Hours"],
    "dg2_hours": ["DG2 Running Hours [hh:mm]", "DG2 Running Hours"],
    "dg3_hours": ["DG3 Running Hours [hh:mm]", "DG3 Running Hours"],
    "dg4_hours": ["DG4 Running Hours [hh:mm]", "DG4 Running Hours"],
    "dg1_power": ["DG1 Power [kW]", "DG1 Power", "DG1_POWER", "DG_1_POWER", "DG 1 Power [kW]", "DG 1 Power", "DG 1 POWER", "DG1 Load [kW]", "DG1 Load", "DG1_LOAD", "DG 1 Load", "DG1 Power Output", "DG1 Power Output [kW]", "D/G1 Power", "D/G 1 Power", "D/G 1 Power [kW]", "AE1 Power [kW]", "AE1 Power", "AE1_POWER", "AE 1 Power [kW]", "AE 1 Power", "AE1 Power Output", "AE1 Power Output [kW]"],
    "dg2_power": ["DG2 Power [kW]", "DG2 Power", "DG2_POWER", "DG_2_POWER", "DG 2 Power [kW]", "DG 2 Power", "DG 2 POWER", "DG2 Load [kW]", "DG2 Load", "DG2_LOAD", "DG 2 Load", "DG2 Power Output", "DG2 Power Output [kW]", "D/G2 Power", "D/G 2 Power", "D/G 2 Power [kW]", "AE2 Power [kW]", "AE2 Power", "AE2_POWER", "AE 2 Power [kW]", "AE 2 Power", "AE2 Power Output", "AE2 Power Output [kW]"],
    "dg3_power": ["DG3 Power [kW]", "DG3 Power", "DG3_POWER", "DG_3_POWER", "DG 3 Power [kW]", "DG 3 Power", "DG 3 POWER", "DG3 Load [kW]", "DG3 Load", "DG3_LOAD", "DG 3 Load", "DG3 Power Output", "DG3 Power Output [kW]", "D/G3 Power", "D/G 3 Power", "D/G 3 Power [kW]", "AE3 Power [kW]", "AE3 Power", "AE3_POWER", "AE 3 Power [kW]", "AE 3 Power", "AE3 Power Output", "AE3 Power Output [kW]"],
    "dg4_power": ["DG4 Power [kW]", "DG4 Power", "DG4_POWER", "DG_4_POWER", "DG 4 Power [kW]", "DG 4 Power", "DG 4 POWER", "DG4 Load [kW]", "DG4 Load", "DG4_LOAD", "DG 4 Load", "DG4 Power Output", "DG4 Power Output [kW]", "D/G4 Power", "D/G 4 Power", "D/G 4 Power [kW]", "AE4 Power [kW]", "AE4 Power", "AE4_POWER", "AE 4 Power [kW]", "AE 4 Power", "AE4 Power Output", "AE4 Power Output [kW]"],
    "sfoc": ["SFOC [gr/Kwh]", "SFOC [g/kWh]", "SFOC"],
    "torque_power": ["Power from Torque Meter [kW]", "Power from Torque Meter", "Torque Power"],
    "fw_produced": ["FW Produced [cbm]", "FW Produced"],
    "fw_consumed": ["FW Consumed [cbm]", "FW Consumed"],
    "sludge_incinerated": ["Sludge Incinerated / Evaporated [cbm]", "Sludge Incinerated", "Sludge Evaporated"],
    "sludge_produced": ["Sludge Produced [cbm]", "Sludge Produced"],
    "total_consumption_24h": ["Total Consumption 24 Hours [MT]", "Total Consumption 24H [MT]", "Total Consumption [MT]"],
    "rob_mgo": ["ROB MGO [MT]", "MGO ROB [MT]", "ROB MGO"],
    "reefer_load": ["Estimated Reefer Load", "Reefer Load"],
    "difference_pct": ["Difference Percentage", "Consumption Difference Percentage", "Difference %"],
    "distance_over_ground": ["Distance Over Ground [nm]", "Distance Over Ground", "Distance [nm]"],
    "speed_over_ground": ["Speed over ground [kn GPS]", "Speed Over Ground [kn GPS]", "Speed over ground", "GPS Speed"],
    "boiler_cons_24h": ["Consumption Boiler 24 Hours [MT]", "Boiler Cons 24 Hours [MT]", "Boiler Consumption [MT]"],
    "dg_cons_24h": ["Consumption DGs 24 Hours [MT]", "DG Cons 24 Hours [MT]", "DG Consumption [MT]"],
}

RULES: List[Dict[str, str]] = [
    {"rule_id": "R02", "issue_type": "Date", "severity": "High", "description": "Start Date & Time GMT must be a valid date and not more than tomorrow."},
    {"rule_id": "R04", "issue_type": "Low Steaming", "severity": "Medium", "description": "Sea rows with Steaming Time below the threshold."},
    {"rule_id": "R05", "issue_type": "Slip", "severity": "Medium", "description": "Sea rows where Calculated Slip is outside the accepted band."},
    {"rule_id": "R06", "issue_type": "MCR/ME Load", "severity": "Medium", "description": "Sea rows where ME Load [%MCR] is outside the accepted band."},
    {"rule_id": "R07", "issue_type": "Electric Load", "severity": "Medium", "description": "Total DG Power [kW] is outside the accepted range."},
    {"rule_id": "R10", "issue_type": "DG Hours", "severity": "High", "description": "Any DG running hours exceed Time Since Last Report."},
    {"rule_id": "R11", "issue_type": "SFOC", "severity": "Medium", "description": "Sea rows with non-zero SFOC outside the accepted range."},
    {"rule_id": "R12", "issue_type": "Power from Torque Meter", "severity": "Medium", "description": "Sea rows with torque-meter power outside the accepted range."},
    {"rule_id": "R13", "issue_type": "Low FW Production", "severity": "Medium", "description": "Sea rows with low FW production during long steaming."},
    {"rule_id": "R14", "issue_type": "High FW Consumption", "severity": "Medium", "description": "Sea rows with high FW consumption."},
    {"rule_id": "R15", "issue_type": "Sludge Incinerated", "severity": "Low", "description": "Sea rows where sludge incinerated/evaporated is zero or blank."},
    {"rule_id": "R16", "issue_type": "Excessive Sludge", "severity": "Medium", "description": "Sludge produced is greater than allowed share of total consumption."},
    {"rule_id": "R18", "issue_type": "Low MGO ROB", "severity": "Medium", "description": "ROB MGO [MT] is below threshold."},
    {"rule_id": "R20", "issue_type": "Reefer Load", "severity": "Low", "description": "Estimated Reefer Load is present but non-numeric."},
    {"rule_id": "R21", "issue_type": "Consumption % Outlier", "severity": "Medium", "description": "Difference Percentage is outside clean average +/- band."},
    {"rule_id": "R22", "issue_type": "Distance vs Speed*Time", "severity": "Medium", "description": "Distance is outside tolerance vs Steaming Time * Speed over ground."},
    {"rule_id": "R23", "issue_type": "Boiler Cons", "severity": "Medium", "description": "Boiler consumption exceeds threshold."},
    {"rule_id": "R24A", "issue_type": "DG Cons >13", "severity": "Medium", "description": "DG consumption exceeds fixed high threshold."},
    {"rule_id": "R24B", "issue_type": "High DG Cons vs Load", "severity": "Medium", "description": "DG consumption is high compared with electric load."},
    {"rule_id": "R24C", "issue_type": "DG Cons <1", "severity": "Medium", "description": "Sea rows with DG consumption below minimum threshold."},
    {"rule_id": "R25", "issue_type": "Multiple DGs", "severity": "Medium", "description": "Multiple DGs running at low combined relative load based on vessel-specific AE/DG MCR; fewer DGs may be sufficient."},
]


# Fixed vessel ME/AE MCR values from ME-AE.xlsx.
# AE Power Output is used as the DG MCR for the Multiple DGs rule.
VESSEL_FIXED_MCR: Dict[str, Dict[str, Any]] = {'AGIOS DIMITRIOS': {'dg_mcr': [2245.0, 2245.0, 2245.0, 2245.0], 'me_mcr': 57200.0},
 'ANTHEA Y': {'dg_mcr': [4000.0, 4000.0, 4000.0, 4000.0], 'me_mcr': 41400.0},
 'ATETI': {'dg_mcr': [2960.0, 2960.0, 2960.0, None], 'me_mcr': 68520.0},
 'ATHENA I': {'dg_mcr': [1360.0, 1360.0, 1360.0, 1360.0], 'me_mcr': 28880.0},
 'BREMERHAVEN EXPRESS': {'dg_mcr': [4500.0, 4500.0, 4500.0, 4500.0], 'me_mcr': 38590.0},
 'CAPTAIN THANASIS I': {'dg_mcr': [1680.0, 1680.0, 1680.0, 1680.0], 'me_mcr': 25270.0},
 'CMA CGM ALCAZAR': {'dg_mcr': [1680.0, 1680.0, 1680.0, 1680.0], 'me_mcr': 41130.0},
 'CMA CGM AMERICA': {'dg_mcr': [2526.0, 2526.0, 2526.0, 2526.0], 'me_mcr': 40040.0},
 'CMA CGM JAMAICA': {'dg_mcr': [1800.0, 1800.0, 2400.0, 2400.0], 'me_mcr': 36560.0},
 'CMA CGM SAMBHAR': {'dg_mcr': [2526.0, 2526.0, 2526.0, 2526.0], 'me_mcr': 40040.0},
 'CMA CGM THALASSA': {'dg_mcr': [3192.0, 3192.0, 3192.0, 3192.0], 'me_mcr': 72240.0},
 'COLOMBIA EXPRESS': {'dg_mcr': [3500.0, 3500.0, 3500.0, 3000.0], 'me_mcr': 33670.0},
 'CONSTANTINOS P II': {'dg_mcr': [2400.0, 2400.0, 2400.0, 2400.0], 'me_mcr': 36560.0},
 'COSTA RICA EXPRESS': {'dg_mcr': [3500.0, 3500.0, 3500.0, 3000.0], 'me_mcr': 33670.0},
 'CZECH': {'dg_mcr': [4500.0, 4500.0, 4500.0, 4500.0], 'me_mcr': 38590.0},
 'DOLPHIN II': {'dg_mcr': [2550.0, 2550.0, 2550.0, None], 'me_mcr': 57910.0},
 'ELENI T': {'dg_mcr': [1810.0, 1810.0, 1810.0, 1810.0], 'me_mcr': 36560.0},
 'EPAMINONDAS': {'dg_mcr': [3840.0, 3840.0, 3840.0, 3840.0], 'me_mcr': 65880.0},
 'GSL ALEXANDRA': {'dg_mcr': [3600.0, 2700.0, 3600.0, None], 'me_mcr': 63000.0},
 'GSL ALICE': {'dg_mcr': [1684.0, 1684.0, 1684.0, 1684.0], 'me_mcr': 25040.0},
 'GSL ARCADIA': {'dg_mcr': [3088.0, 3088.0, 3088.0, None], 'me_mcr': 54840.0},
 "GSL CHATEAU D'...": {'dg_mcr': [1680.0, 1680.0, 1680.0, 1680.0], 'me_mcr': 41130.0},
 'GSL CHLOE': {'dg_mcr': [1760.0, 1980.0, 1980.0, 1760.0], 'me_mcr': 21660.0},
 'GSL CHRISTEL ELISAB...': {'dg_mcr': [2900.0, 2900.0, 2900.0, None], 'me_mcr': 57100.0},
 'GSL CHRISTEN': {'dg_mcr': [2942.0, 2942.0, 2942.0, 2942.0], 'me_mcr': 62587.0},
 'GSL DOROTHEA': {'dg_mcr': [2400.0, 2400.0, 2400.0, 2400.0], 'me_mcr': 54840.0},
 'GSL EFFIE': {'dg_mcr': [3600.0, 2700.0, 3600.0, None], 'me_mcr': 63000.0},
 'GSL ELEFTHERIA': {'dg_mcr': [1684.0, 1684.0, 1684.0, 1684.0], 'me_mcr': 25040.0},
 'GSL ELENI': {'dg_mcr': [2100.0, 2700.0, 2700.0, 2100.0], 'me_mcr': 68640.0},
 'GSL ELIZABETH': {'dg_mcr': [1400.0, 1400.0, 1400.0, 950.0], 'me_mcr': 21170.0},
 'GSL GRANIA': {'dg_mcr': [2100.0, 2700.0, 2700.0, 2100.0], 'me_mcr': 68640.0},
 'GSL KALLIOPI': {'dg_mcr': [2100.0, 2700.0, 2700.0, 2700.0], 'me_mcr': 68640.0},
 'GSL KITHIRA': {'dg_mcr': [4500.0, 4500.0, 4500.0, 4000.0], 'me_mcr': 40040.0},
 'GSL LALO': {'dg_mcr': [1680.0, 1680.0, 1680.0, 1680.0], 'me_mcr': 25270.0},
 'GSL LYDIA': {'dg_mcr': [3600.0, 2700.0, 3600.0, None], 'me_mcr': 63000.0},
 'GSL MAMITSA': {'dg_mcr': [1680.0, 1680.0, 1680.0, 1680.0], 'me_mcr': 25270.0},
 'GSL MAREN': {'dg_mcr': [1760.0, 1760.0, 1980.0, 1980.0], 'me_mcr': 21660.0},
 'GSL MARIA': {'dg_mcr': [3088.0, 3088.0, 3088.0, None], 'me_mcr': 54880.0},
 'GSL MELINA': {'dg_mcr': [1684.0, 1684.0, 1684.0, 1684.0], 'me_mcr': 25040.0},
 'GSL MELITA': {'dg_mcr': [3088.0, 3088.0, 3088.0, None], 'me_mcr': 54840.0},
 'GSL MERCER': {'dg_mcr': [1680.0, 1680.0, 1680.0, 1680.0], 'me_mcr': 25270.0},
 'GSL MYNY': {'dg_mcr': [3088.0, 3088.0, 3088.0, None], 'me_mcr': 54840.0},
 'GSL NICOLETTA': {'dg_mcr': [2942.0, 2942.0, 2942.0, 2942.0], 'me_mcr': 62587.0},
 'GSL NINGBO': {'dg_mcr': [3160.0, 3160.0, 3160.0, 3160.0], 'me_mcr': 68520.0},
 'GSL ROSSI': {'dg_mcr': [1760.0, 1760.0, 1760.0, 1760.0], 'me_mcr': 27120.0},
 'GSL SOFIA': {'dg_mcr': [3600.0, 2700.0, 3600.0, None], 'me_mcr': 63000.0},
 'GSL SUSAN': {'dg_mcr': [1800.0, 1800.0, 2400.0, 2400.0], 'me_mcr': 36560.0},
 'GSL SYROS': {'dg_mcr': [4500.0, 4500.0, 4500.0, 3912.0], 'me_mcr': 44040.0},
 'GSL TEGEA': {'dg_mcr': [2400.0, 2400.0, 2400.0, 2400.0], 'me_mcr': 54840.0},
 'GSL TINOS': {'dg_mcr': [4500.0, 4500.0, 4500.0, 4000.0], 'me_mcr': 40040.0},
 'GSL TRIPOLI': {'dg_mcr': [4500.0, 4500.0, 4500.0, 4000.0], 'me_mcr': 40040.0},
 'GSL VALERIE': {'dg_mcr': [1680.0, 1680.0, 1680.0, 1680.0], 'me_mcr': 25270.0},
 'GSL VINIA': {'dg_mcr': [2900.0, 2900.0, 2900.0, None], 'me_mcr': 57100.0},
 'GSL VIOLETTA': {'dg_mcr': [3088.0, 3088.0, 3088.0, None], 'me_mcr': 54840.0},
 'IAN H': {'dg_mcr': [2320.0, 2320.0, 2320.0, 2320.0], 'me_mcr': 54900.0},
 'ISTANBUL EXPRESS': {'dg_mcr': [4500.0, 4500.0, 4500.0, 4500.0], 'me_mcr': 38590.0},
 'JAMAICA EXPRESS': {'dg_mcr': [2530.0, 2530.0, 2530.0, 2530.0], 'me_mcr': 32900.0},
 'JULIE': {'dg_mcr': [1275.0, 1275.0, 1275.0, 1275.0], 'me_mcr': 24824.0},
 'KOI': {'dg_mcr': [None, None, None, None], 'me_mcr': 68640.0},
 'KOSTAS K': {'dg_mcr': [3600.0, 2700.0, 3600.0, None], 'me_mcr': 63000.0},
 'KUMASI': {'dg_mcr': [1275.0, 1275.0, 1275.0, 1275.0], 'me_mcr': 24824.0},
 'MAIRA': {'dg_mcr': [1280.0, 1280.0, 1280.0, 780.0], 'me_mcr': 20930.0},
 'MANET': {'dg_mcr': [1530.0, 1530.0, 1530.0, 1530.0], 'me_mcr': 24840.0},
 'MARIA Y': {'dg_mcr': [3600.0, 2700.0, 3600.0, None], 'me_mcr': 63000.0},
 'MARIANNA I': {'dg_mcr': [3600.0, 3600.0, 3600.0, 3600.0], 'me_mcr': 65880.0},
 'MELINA': {'dg_mcr': [1810.0, 1810.0, 1810.0, 1810.0], 'me_mcr': 36560.0},
 'MEXICO EXPRESS': {'dg_mcr': [2530.0, 2530.0, 2530.0, 2530.0], 'me_mcr': 32900.0},
 'MSC QINGDAO': {'dg_mcr': [3160.0, 3160.0, 3160.0, 3160.0], 'me_mcr': 68520.0},
 'MSC ROMA': {'dg_mcr': [2880.0, 2880.0, 2880.0, 2880.0], 'me_mcr': 68520.0},
 'MSC TIANJIN': {'dg_mcr': [3160.0, 3160.0, 3160.0, 3160.0], 'me_mcr': 68520.0},
 'MYNY': {'dg_mcr': [2942.0, 2942.0, 2942.0, 2942.0], 'me_mcr': 62587.0},
 'NEWYORKER': {'dg_mcr': [1280.0, 1280.0, 1280.0, 780.0], 'me_mcr': 20930.0},
 'NICARAGUA EXPRESS': {'dg_mcr': [3500.0, 3500.0, 3500.0, 3000.0], 'me_mcr': 33670.0},
 'NIKOLAS': {'dg_mcr': [1280.0, 1280.0, 1280.0, 780.0], 'me_mcr': 20930.0},
 'ORCA I': {'dg_mcr': [2550.0, 2550.0, 2550.0, None], 'me_mcr': 57910.0},
 'PANAMA EXPRESS': {'dg_mcr': [3500.0, 3500.0, 3000.0, 3000.0], 'me_mcr': 33670.0},
 'SPYROS V': {'dg_mcr': [2400.0, 2400.0, 2400.0, 2400.0], 'me_mcr': 36560.0},
 'STAMATIS B': {'dg_mcr': [1421.0, 1421.0, 2100.0, 2100.0], 'me_mcr': 36450.0},
 'SYDNEY EXPRESS': {'dg_mcr': [4500.0, 4500.0, 4500.0, 4500.0], 'me_mcr': 38590.0},
 'TINA I': {'dg_mcr': [2354.0, 2354.0, 2354.0, 2354.0], 'me_mcr': 57200.0},
 'TONSBERG': {'dg_mcr': [2395.0, 2395.0, 2000.0, 2000.0], 'me_mcr': 54900.0},
 'TORRANCE': {'dg_mcr': [3080.0, 3080.0, 3080.0, None], 'me_mcr': 54840.0},
 'ZIM NORFOLK': {'dg_mcr': [4000.0, 4000.0, 4000.0, 4000.0], 'me_mcr': 41400.0},
 'ZIM XIAMEN': {'dg_mcr': [4000.0, 4000.0, 4000.0, 4000.0], 'me_mcr': 41400.0},
 'ZOI': {'dg_mcr': [2395.0, 2395.0, 2720.0, 2720.0], 'me_mcr': 54900.0}}


def normalize_vessel_key(value: Any) -> str:
    """Normalize vessel names for matching fixed MCR values."""
    if value is None:
        return ""
    return " ".join(str(value).strip().upper().split())


VESSEL_FIXED_MCR_BY_KEY: Dict[str, Dict[str, Any]] = {
    normalize_vessel_key(name): values for name, values in VESSEL_FIXED_MCR.items()
}


def get_vessel_fixed_mcr(vessel_name: Any) -> Optional[Dict[str, Any]]:
    """Return fixed ME/AE MCR data for a vessel, if available.

    ME-AE.xlsx contains some long vessel names shortened with ``...``.
    The first lookup is exact; the second lookup treats the part before
    ``...`` as a prefix so full source names can still match the stored
    AE power-output values.
    """
    key = normalize_vessel_key(vessel_name)
    if not key:
        return None

    exact = VESSEL_FIXED_MCR_BY_KEY.get(key)
    if exact is not None:
        return exact

    for stored_key, values in VESSEL_FIXED_MCR_BY_KEY.items():
        if "..." in stored_key:
            prefix = stored_key.split("...", 1)[0].strip()
            if prefix and key.startswith(prefix):
                return values

    return None


def is_valid_positive_number(value: Any) -> bool:
    """True when value can be used as a positive numeric denominator."""
    try:
        return pd.notna(value) and float(value) > 0
    except Exception:
        return False


@dataclass
class ValidationError:
    file_name: str
    sheet_name: str
    excel_row: int
    report_id: Any
    ship_name: Any
    fleet: Any
    report_type: Any
    start_gmt: Any
    end_gmt: Any
    state_name: Any
    rule_id: str
    issue_type: str
    severity: str
    message: str
    value: Any
    expected: str
    columns: str


def read_noon_excel(file_obj: Any, file_name: str = "uploaded.xlsx", sheet_name: Optional[str] = None) -> Tuple[pd.DataFrame, str]:
    """Read an ANTHEA-style noon report Excel file.

    The function prefers a sheet called 'Table'. If it does not exist, it falls back
    to 'Query1' and then to the first worksheet. The returned dataframe preserves
    the original column names.
    """
    content = file_obj.read() if hasattr(file_obj, "read") else open(file_obj, "rb").read()
    xls = pd.ExcelFile(BytesIO(content), engine="openpyxl")
    if sheet_name and sheet_name in xls.sheet_names:
        selected = sheet_name
    elif "Table" in xls.sheet_names:
        selected = "Table"
    elif "Query1" in xls.sheet_names:
        selected = "Query1"
    else:
        selected = xls.sheet_names[0]
    df = pd.read_excel(xls, sheet_name=selected, engine="openpyxl")
    df = df.dropna(how="all").reset_index(drop=True)
    df.attrs["file_name"] = file_name
    df.attrs["sheet_name"] = selected
    return df, selected


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower().replace("\n", " ").replace("  ", " ")


def map_columns(df: pd.DataFrame) -> Tuple[Dict[str, Optional[str]], Dict[str, List[str]]]:
    normalized_to_original = {_normalize_text(col): col for col in df.columns}
    mapping: Dict[str, Optional[str]] = {}
    missing: Dict[str, List[str]] = {}
    for key, aliases in COLUMN_ALIASES.items():
        found = None
        for alias in aliases:
            if _normalize_text(alias) in normalized_to_original:
                found = normalized_to_original[_normalize_text(alias)]
                break
        mapping[key] = found
        if found is None:
            missing[key] = aliases
    return mapping, missing


def col(df: pd.DataFrame, mapping: Dict[str, Optional[str]], key: str) -> pd.Series:
    name = mapping.get(key)
    if name is None or name not in df.columns:
        return pd.Series([np.nan] * len(df), index=df.index)
    return df[name]


def to_number(series: pd.Series) -> pd.Series:
    """Convert numbers, Excel dates/times, timedeltas, and HH:MM strings to floats.

    For time-like values, returns hours when the value looks like a time duration.
    Numeric Excel values are left as numeric, matching the ANTHEA export where
    time durations are already expressed in hours.
    """
    if series.empty:
        return pd.Series(dtype="float64")

    def one(v: Any) -> float:
        if pd.isna(v):
            return np.nan
        if isinstance(v, pd.Timedelta):
            return v.total_seconds() / 3600.0
        if isinstance(v, timedelta):
            return v.total_seconds() / 3600.0
        if isinstance(v, datetime):
            # This is unusual for duration columns; return NaN instead of the serial date.
            return np.nan
        if isinstance(v, (int, float, np.integer, np.floating)):
            return float(v)
        text = str(v).strip()
        if text == "":
            return np.nan
        if ":" in text:
            parts = text.split(":")
            try:
                if len(parts) == 2:
                    h, m = float(parts[0]), float(parts[1])
                    return h + m / 60.0
                if len(parts) == 3:
                    h, m, s = float(parts[0]), float(parts[1]), float(parts[2])
                    return h + m / 60.0 + s / 3600.0
            except ValueError:
                pass
        text = text.replace("%", "").replace(",", "")
        try:
            val = float(text)
            # If user pasted 20% as text, convert to 0.20.
            if "%" in str(v):
                return val / 100.0
            return val
        except ValueError:
            return np.nan

    return series.map(one).astype("float64")


def to_date(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce")


def is_blank_value(value: Any) -> bool:
    if value is None or pd.isna(value):
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def safe_display(value: Any) -> Any:
    if pd.isna(value) if not isinstance(value, (list, tuple, dict)) else False:
        return ""
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.strftime("%Y-%m-%d %H:%M")
    return value


def fmt_pct(v: Any) -> str:
    try:
        if pd.isna(v):
            return ""
        return f"{float(v):.1%}"
    except Exception:
        return str(v)


def fmt_num(v: Any, decimals: int = 1) -> str:
    try:
        if pd.isna(v):
            return ""
        return f"{float(v):.{decimals}f}"
    except Exception:
        return str(v)


def issue_meta(rule_id: str) -> Tuple[str, str]:
    for rule in RULES:
        if rule["rule_id"] == rule_id:
            return rule["issue_type"], rule["severity"]
    return rule_id, "Medium"


def build_error(
    df: pd.DataFrame,
    mapping: Dict[str, Optional[str]],
    idx: int,
    rule_id: str,
    message: str,
    value: Any,
    expected: str,
    columns: Iterable[str],
    file_name: str,
    sheet_name: str,
) -> ValidationError:
    issue_type, severity = issue_meta(rule_id)
    return ValidationError(
        file_name=file_name,
        sheet_name=sheet_name,
        excel_row=int(idx) + 2,
        report_id=safe_display(col(df, mapping, "report_id").iloc[idx]),
        ship_name=safe_display(col(df, mapping, "ship_name").iloc[idx]),
        fleet=safe_display(col(df, mapping, "fleet").iloc[idx]),
        report_type=safe_display(col(df, mapping, "report_type").iloc[idx]),
        start_gmt=safe_display(col(df, mapping, "start_gmt").iloc[idx]),
        end_gmt=safe_display(col(df, mapping, "end_gmt").iloc[idx]),
        state_name=safe_display(col(df, mapping, "state_name").iloc[idx]),
        rule_id=rule_id,
        issue_type=issue_type,
        severity=severity,
        message=message,
        value=safe_display(value),
        expected=expected,
        columns=", ".join([c for c in columns if c]),
    )


def validate_noon_report(
    df: pd.DataFrame,
    file_name: str = "uploaded.xlsx",
    sheet_name: str = "Table",
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, pd.DataFrame]:
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    mapping, missing = map_columns(df)
    n = len(df)

    report_type = col(df, mapping, "report_type").fillna("").astype(str)
    state_name = col(df, mapping, "state_name").fillna("").astype(str)
    sea = state_name.str.strip().str.lower().eq("sea passage") | report_type.str.lower().str.contains("sea", na=False)

    start_gmt = to_date(col(df, mapping, "start_gmt"))
    steaming_time = to_number(col(df, mapping, "steaming_time"))
    calculated_slip = to_number(col(df, mapping, "calculated_slip"))
    me_load = to_number(col(df, mapping, "me_load"))
    total_dg_power = to_number(col(df, mapping, "total_dg_power"))
    time_since_last = to_number(col(df, mapping, "time_since_last"))
    dg_hours = {k: to_number(col(df, mapping, k)) for k in ["dg1_hours", "dg2_hours", "dg3_hours", "dg4_hours"]}
    sfoc = to_number(col(df, mapping, "sfoc"))
    torque_power = to_number(col(df, mapping, "torque_power"))
    fw_produced = to_number(col(df, mapping, "fw_produced"))
    fw_consumed = to_number(col(df, mapping, "fw_consumed"))
    sludge_incinerated_raw = col(df, mapping, "sludge_incinerated")
    sludge_incinerated = to_number(sludge_incinerated_raw)
    sludge_produced = to_number(col(df, mapping, "sludge_produced"))
    total_consumption_24h = to_number(col(df, mapping, "total_consumption_24h"))
    rob_mgo = to_number(col(df, mapping, "rob_mgo"))
    reefer_raw = col(df, mapping, "reefer_load")
    reefer_num = to_number(reefer_raw)
    difference_pct = to_number(col(df, mapping, "difference_pct"))
    distance_over_ground = to_number(col(df, mapping, "distance_over_ground"))
    speed_over_ground = to_number(col(df, mapping, "speed_over_ground"))
    boiler_cons_24h = to_number(col(df, mapping, "boiler_cons_24h"))
    dg_cons_24h = to_number(col(df, mapping, "dg_cons_24h"))
    dg_power = {k: to_number(col(df, mapping, k)) for k in ["dg1_power", "dg2_power", "dg3_power", "dg4_power"]}

    clean_diff = difference_pct[(difference_pct >= cfg["difference_pct_clean_min"]) & (difference_pct <= cfg["difference_pct_clean_max"]) & (difference_pct != 0)]
    diff_avg = clean_diff.mean() if len(clean_diff) else np.nan
    diff_count = int(clean_diff.count())

    errors: List[ValidationError] = []
    multiple_dgs_running_counts = [np.nan] * n
    multiple_dgs_load_ratio_sums = [np.nan] * n
    multiple_dgs_limits = [np.nan] * n
    multiple_dgs_status = [""] * n

    def add(idx: int, rule_id: str, message: str, value: Any, expected: str, column_keys: Iterable[str]) -> None:
        columns = [mapping.get(k) or k for k in column_keys]
        errors.append(build_error(df, mapping, idx, rule_id, message, value, expected, columns, file_name, sheet_name))

    max_date = pd.Timestamp(datetime.now().date() + timedelta(days=int(cfg["date_max_days_ahead"])))
    for i in range(n):
        # R02 Date
        raw_date = col(df, mapping, "start_gmt").iloc[i]
        if pd.isna(start_gmt.iloc[i]) or start_gmt.iloc[i] > max_date:
            add(i, "R02", "Date", raw_date, f"Valid date <= {max_date.date()}", ["start_gmt"])

        if sea.iloc[i]:
            # R04 Low Steaming
            if pd.notna(steaming_time.iloc[i]) and steaming_time.iloc[i] < cfg["low_steaming_hours"]:
                add(i, "R04", "Low Steaming time", steaming_time.iloc[i], f">= {cfg['low_steaming_hours']} hours", ["steaming_time"])

            # R05 Slip
            if pd.notna(calculated_slip.iloc[i]) and (calculated_slip.iloc[i] < cfg["slip_min"] or calculated_slip.iloc[i] > cfg["slip_max"]):
                wind_val = col(df, mapping, "wind_force").iloc[i]
                suffix = f", Wind Force = {wind_val}" if not is_blank_value(wind_val) else ""
                add(i, "R05", f"Slip = {fmt_pct(calculated_slip.iloc[i])}{suffix}", calculated_slip.iloc[i], f"{fmt_pct(cfg['slip_min'])} to {fmt_pct(cfg['slip_max'])}", ["calculated_slip", "wind_force"])

            # R06 MCR/ME Load
            if pd.notna(me_load.iloc[i]) and (me_load.iloc[i] < cfg["me_load_min"] or me_load.iloc[i] > cfg["me_load_max"]):
                add(i, "R06", f"MCR = {fmt_pct(me_load.iloc[i])}", me_load.iloc[i], f"{fmt_pct(cfg['me_load_min'])} to {fmt_pct(cfg['me_load_max'])}", ["me_load"])

            # R11 SFOC
            if pd.notna(sfoc.iloc[i]) and sfoc.iloc[i] != 0 and (sfoc.iloc[i] < cfg["sfoc_min"] or sfoc.iloc[i] > cfg["sfoc_max"]):
                add(i, "R11", f"SFOC = {fmt_num(sfoc.iloc[i], 1)}", sfoc.iloc[i], f"{cfg['sfoc_min']} to {cfg['sfoc_max']}", ["sfoc"])

            # R12 Torque
            if pd.notna(torque_power.iloc[i]) and torque_power.iloc[i] != 0 and (torque_power.iloc[i] < cfg["torque_power_min_kw"] or torque_power.iloc[i] > cfg["torque_power_max_kw"]):
                add(i, "R12", f"Torque = {fmt_num(torque_power.iloc[i], 0)}", torque_power.iloc[i], f"{cfg['torque_power_min_kw']} to {cfg['torque_power_max_kw']} kW", ["torque_power"])

            # R13 Low FW Production
            if pd.notna(fw_produced.iloc[i]) and pd.notna(steaming_time.iloc[i]) and fw_produced.iloc[i] < cfg["fw_produced_min_cbm"] and steaming_time.iloc[i] > cfg["low_fw_steaming_hours"]:
                add(i, "R13", "Low FW production", fw_produced.iloc[i], f">= {cfg['fw_produced_min_cbm']} cbm when steaming > {cfg['low_fw_steaming_hours']} h", ["fw_produced", "steaming_time"])

            # R14 High FW Consumption
            if pd.notna(fw_consumed.iloc[i]) and fw_consumed.iloc[i] > cfg["fw_consumed_max_cbm"]:
                add(i, "R14", "High FW Consumption", fw_consumed.iloc[i], f"<= {cfg['fw_consumed_max_cbm']} cbm", ["fw_consumed"])

            # R15 Sludge Incinerated
            raw_sludge_inc = sludge_incinerated_raw.iloc[i]
            if is_blank_value(raw_sludge_inc) or (pd.notna(sludge_incinerated.iloc[i]) and sludge_incinerated.iloc[i] == 0):
                add(i, "R15", "Sludge Incinerated = 0", raw_sludge_inc, "> 0 for sea rows", ["sludge_incinerated"])

            # R16 Excessive Sludge
            if pd.notna(sludge_produced.iloc[i]) and pd.notna(total_consumption_24h.iloc[i]) and sludge_produced.iloc[i] > cfg["sludge_factor_of_total_consumption"] * total_consumption_24h.iloc[i]:
                add(i, "R16", "Excessive Sludge", sludge_produced.iloc[i], f"<= {cfg['sludge_factor_of_total_consumption']:.3f} * Total Consumption 24H", ["sludge_produced", "total_consumption_24h"])

            # R21 Consumption % Outlier
            if diff_count >= cfg["difference_pct_min_count"] and pd.notna(difference_pct.iloc[i]) and difference_pct.iloc[i] != 0:
                if difference_pct.iloc[i] < diff_avg - cfg["difference_pct_avg_band"] or difference_pct.iloc[i] > diff_avg + cfg["difference_pct_avg_band"]:
                    add(i, "R21", f"Consumption = {fmt_pct(difference_pct.iloc[i])}, Average = {fmt_pct(diff_avg)}", difference_pct.iloc[i], f"Average +/- {fmt_pct(cfg['difference_pct_avg_band'])}", ["difference_pct"])

            # R22 Distance vs Speed*Time
            expected_distance = steaming_time.iloc[i] * speed_over_ground.iloc[i]
            if pd.notna(distance_over_ground.iloc[i]) and pd.notna(steaming_time.iloc[i]) and pd.notna(speed_over_ground.iloc[i]) and expected_distance != 0:
                low = expected_distance * (1 - cfg["distance_tolerance_pct"])
                high = expected_distance * (1 + cfg["distance_tolerance_pct"])
                if distance_over_ground.iloc[i] < low or distance_over_ground.iloc[i] > high:
                    add(i, "R22", "St.Time*Speed =/= Distance", distance_over_ground.iloc[i], f"{low:.2f} to {high:.2f} nm", ["distance_over_ground", "steaming_time", "speed_over_ground"])

            # R24C DG Cons <1
            if pd.notna(dg_cons_24h.iloc[i]) and dg_cons_24h.iloc[i] < cfg["dg_cons_low_mt"]:
                add(i, "R24C", "DG Cons < 1", dg_cons_24h.iloc[i], f">= {cfg['dg_cons_low_mt']} MT", ["dg_cons_24h"])

        # R07 Electric Load (all report types)
        if pd.notna(total_dg_power.iloc[i]) and (total_dg_power.iloc[i] < cfg["electric_load_min_kw"] or total_dg_power.iloc[i] > cfg["electric_load_max_kw"]):
            add(i, "R07", f"Electric Load = {fmt_num(total_dg_power.iloc[i], 0)}", total_dg_power.iloc[i], f"{cfg['electric_load_min_kw']} to {cfg['electric_load_max_kw']} kW", ["total_dg_power"])

        # R10 DG Hours
        if pd.notna(time_since_last.iloc[i]):
            over = []
            for key, series in dg_hours.items():
                if pd.notna(series.iloc[i]) and series.iloc[i] > time_since_last.iloc[i]:
                    over.append(mapping.get(key) or key)
            if over:
                add(i, "R10", "a DG's Hours is more then Time since last reporting", "; ".join(over), f"Each DG running hours <= {time_since_last.iloc[i]}", ["time_since_last", "dg1_hours", "dg2_hours", "dg3_hours", "dg4_hours"])

        # R25 Multiple DGs
        # Formula requested:
        # sum(DG_POWER / DG_MCR) < load_factor * (running_dg_count - 1)
        # where a DG is treated as running when DG_POWER > running_threshold_kw.
        vessel_name_for_mcr = col(df, mapping, "ship_name").iloc[i]
        vessel_mcr = get_vessel_fixed_mcr(vessel_name_for_mcr)
        if vessel_mcr and vessel_mcr.get("dg_mcr"):
            running_threshold_kw = float(cfg.get("dg_power_running_threshold_kw", 10.0))
            load_factor = float(cfg.get("dg_optimization_load_factor", 0.70))
            dg_mcr_values = vessel_mcr["dg_mcr"]
            dg_power_values = [dg_power[key].iloc[i] for key in ["dg1_power", "dg2_power", "dg3_power", "dg4_power"]]

            running_count = 0
            load_ratio_sum = 0.0
            display_terms = []
            missing_mcr_for_running = []
            any_power_available = False

            for pos, (power_value, mcr_value) in enumerate(zip(dg_power_values, dg_mcr_values), start=1):
                if pd.isna(power_value):
                    power_kw = 0.0
                else:
                    any_power_available = True
                    power_kw = float(power_value)

                is_running = power_kw > running_threshold_kw
                if is_running:
                    running_count += 1

                running_label = "counted running" if is_running else "not counted"
                if is_valid_positive_number(mcr_value):
                    mcr_kw = float(mcr_value)
                    # Keep the left side exactly as requested: all DG power values
                    # are included in the sum, while the threshold only controls
                    # the running-DG count on the right side.
                    load_ratio = power_kw / mcr_kw
                    load_ratio_sum += load_ratio
                    display_terms.append(
                        f"DG{pos}: {fmt_num(power_kw, 0)}/{fmt_num(mcr_kw, 0)} kW ({fmt_pct(load_ratio)}, {running_label})"
                    )
                elif is_running:
                    missing_mcr_for_running.append(f"DG{pos}")
                else:
                    display_terms.append(f"DG{pos}: {fmt_num(power_kw, 0)} kW ({running_label}, MCR not set)")

            if any_power_available:
                threshold = load_factor * max(running_count - 1, 0)
                multiple_dgs_running_counts[i] = running_count
                multiple_dgs_load_ratio_sums[i] = load_ratio_sum
                multiple_dgs_limits[i] = threshold
                multiple_dgs_status[i] = (
                    f"DG threshold > {fmt_num(running_threshold_kw, 0)} kW; "
                    f"running DGs = {running_count}; relative load = {fmt_pct(load_ratio_sum)}; "
                    f"limit = {fmt_pct(threshold)}"
                )

            if any_power_available and running_count > 1 and not missing_mcr_for_running:
                threshold = load_factor * (running_count - 1)
                if load_ratio_sum < threshold:
                    add(
                        i,
                        "R25",
                        f"Multiple DGs check: {running_count} DGs counted running above {fmt_num(running_threshold_kw, 0)} kW; combined relative load = {fmt_pct(load_ratio_sum)}",
                        "; ".join(display_terms),
                        f">= {fmt_pct(threshold)} based on {fmt_num(load_factor, 2)} * ({running_count} - 1). A DG is counted running only when DG power > {fmt_num(running_threshold_kw, 0)} kW; consider if fewer DGs can cover the required load",
                        ["ship_name", "dg1_power", "dg2_power", "dg3_power", "dg4_power"],
                    )
        else:
            multiple_dgs_status[i] = f"No fixed AE/DG MCR found for vessel: {safe_display(vessel_name_for_mcr)}"

        # R18 Low MGO ROB
        if pd.notna(rob_mgo.iloc[i]) and rob_mgo.iloc[i] < cfg["mgo_rob_min_mt"]:
            add(i, "R18", "Low MGO ROB", rob_mgo.iloc[i], f">= {cfg['mgo_rob_min_mt']} MT", ["rob_mgo"])

        # R20 Reefer Load
        raw_reefer = reefer_raw.iloc[i]
        if not is_blank_value(raw_reefer) and pd.isna(reefer_num.iloc[i]):
            add(i, "R20", "Error in Reefer Load", raw_reefer, "Numeric when present", ["reefer_load"])

        # R23 Boiler Cons
        if pd.notna(boiler_cons_24h.iloc[i]) and boiler_cons_24h.iloc[i] > cfg["boiler_cons_max_mt"]:
            add(i, "R23", "Boiler Cons > 5", boiler_cons_24h.iloc[i], f"<= {cfg['boiler_cons_max_mt']} MT", ["boiler_cons_24h"])

        # R24A DG Cons >13
        if pd.notna(dg_cons_24h.iloc[i]) and dg_cons_24h.iloc[i] > cfg["dg_cons_high_mt"]:
            add(i, "R24A", "DG Cons > 13", dg_cons_24h.iloc[i], f"<= {cfg['dg_cons_high_mt']} MT", ["dg_cons_24h"])

        # R24B High DG Cons vs Load
        if pd.notna(dg_cons_24h.iloc[i]) and pd.notna(total_dg_power.iloc[i]):
            expected_dg_cons = cfg["dg_sfc_g_per_kwh"] * 24 * total_dg_power.iloc[i] / 1_000_000
            if dg_cons_24h.iloc[i] - expected_dg_cons > cfg["dg_cons_vs_load_buffer_mt"]:
                add(i, "R24B", "High DG Cons", dg_cons_24h.iloc[i], f"<= load-based expected + {cfg['dg_cons_vs_load_buffer_mt']} MT ({expected_dg_cons + cfg['dg_cons_vs_load_buffer_mt']:.2f})", ["dg_cons_24h", "total_dg_power"])

    errors_df = pd.DataFrame([asdict(e) for e in errors])
    if errors_df.empty:
        errors_df = pd.DataFrame(columns=list(ValidationError.__annotations__.keys()))

    # Wide row-level checker, similar to the Excel checker workbook.
    base_cols = {
        "file_name": file_name,
        "sheet_name": sheet_name,
        "excel_row": np.arange(2, n + 2),
        "report_id": col(df, mapping, "report_id"),
        "ship_name": col(df, mapping, "ship_name"),
        "fleet": col(df, mapping, "fleet"),
        "report_type": col(df, mapping, "report_type"),
        "start_gmt": col(df, mapping, "start_gmt"),
        "end_gmt": col(df, mapping, "end_gmt"),
        "state_name": col(df, mapping, "state_name"),
        "scope": np.where(sea, "Sea", "Not sea"),
        "multiple_dgs_running_count": multiple_dgs_running_counts,
        "multiple_dgs_load_ratio_sum": multiple_dgs_load_ratio_sums,
        "multiple_dgs_limit": multiple_dgs_limits,
        "multiple_dgs_status": multiple_dgs_status,
    }
    checked_rows = pd.DataFrame(base_cols)
    for rule in RULES:
        checked_rows[rule["issue_type"]] = ""
    for _, e in errors_df.iterrows():
        mask = checked_rows["excel_row"] == e["excel_row"]
        if e["issue_type"] in checked_rows.columns:
            checked_rows.loc[mask, e["issue_type"]] = checked_rows.loc[mask, e["issue_type"]].astype(str).where(
                checked_rows.loc[mask, e["issue_type"]].astype(str).eq(""),
                checked_rows.loc[mask, e["issue_type"]].astype(str) + " | "
            ) + str(e["message"])
    issue_cols = [r["issue_type"] for r in RULES]
    checked_rows["issue_count"] = checked_rows[issue_cols].ne("").sum(axis=1)
    checked_rows["combined_issues"] = checked_rows[issue_cols].apply(lambda row: "OK" if all(v == "" for v in row) else " & ".join([str(v) for v in row if v != ""]), axis=1)
    checked_rows["notes"] = np.where(checked_rows["scope"].eq("Sea"), "", "Not sea passage / sea-only checks skipped")

    skipped_rule_rows = []
    required_by_rule = {
        "R02": ["start_gmt"],
        "R04": ["report_type", "state_name", "steaming_time"],
        "R05": ["report_type", "state_name", "calculated_slip"],
        "R06": ["report_type", "state_name", "me_load"],
        "R07": ["total_dg_power"],
        "R10": ["time_since_last", "dg1_hours", "dg2_hours", "dg3_hours", "dg4_hours"],
        "R11": ["report_type", "state_name", "sfoc"],
        "R12": ["report_type", "state_name", "torque_power"],
        "R13": ["report_type", "state_name", "fw_produced", "steaming_time"],
        "R14": ["report_type", "state_name", "fw_consumed"],
        "R15": ["report_type", "state_name", "sludge_incinerated"],
        "R16": ["report_type", "state_name", "sludge_produced", "total_consumption_24h"],
        "R18": ["rob_mgo"],
        "R20": ["reefer_load"],
        "R21": ["report_type", "state_name", "difference_pct"],
        "R22": ["report_type", "state_name", "distance_over_ground", "steaming_time", "speed_over_ground"],
        "R23": ["boiler_cons_24h"],
        "R24A": ["dg_cons_24h"],
        "R24B": ["dg_cons_24h", "total_dg_power"],
        "R24C": ["report_type", "state_name", "dg_cons_24h"],
        "R25": ["ship_name", "dg1_power", "dg2_power", "dg3_power", "dg4_power"],
    }
    for rule in RULES:
        missing_cols = [k for k in required_by_rule.get(rule["rule_id"], []) if mapping.get(k) is None]
        if missing_cols:
            skipped_rule_rows.append({
                "file_name": file_name,
                "sheet_name": sheet_name,
                "rule_id": rule["rule_id"],
                "issue_type": rule["issue_type"],
                "missing_column_keys": ", ".join(missing_cols),
                "expected_aliases": "; ".join([f"{k}: {COLUMN_ALIASES.get(k, [])}" for k in missing_cols]),
            })
    skipped_rules_df = pd.DataFrame(skipped_rule_rows)

    summary_rows = [
        {"metric": "File", "value": file_name},
        {"metric": "Sheet", "value": sheet_name},
        {"metric": "Report rows", "value": n},
        {"metric": "Rows with issues", "value": int((checked_rows["issue_count"] > 0).sum())},
        {"metric": "Rows OK", "value": int((checked_rows["issue_count"] == 0).sum())},
        {"metric": "Total issues", "value": int(len(errors_df))},
        {"metric": "Average Difference Percentage basis", "value": diff_avg},
        {"metric": "Count Difference Percentage basis", "value": diff_count},
        {"metric": "Skipped rules due to missing columns", "value": len(skipped_rules_df)},
    ]
    summary = pd.DataFrame(summary_rows)
    by_rule = errors_df.groupby(["rule_id", "issue_type", "severity"], dropna=False).size().reset_index(name="count") if not errors_df.empty else pd.DataFrame(columns=["rule_id", "issue_type", "severity", "count"])

    rules_df = pd.DataFrame(RULES)
    columns_df = pd.DataFrame([{"column_key": k, "matched_column": v or "", "aliases": ", ".join(COLUMN_ALIASES.get(k, []))} for k, v in mapping.items()])

    return {
        "summary": summary,
        "by_rule": by_rule,
        "errors": errors_df,
        "checked_rows": checked_rows,
        "skipped_rules": skipped_rules_df,
        "rules": rules_df,
        "columns": columns_df,
    }


def validate_excel_file(file_obj: Any, file_name: str = "uploaded.xlsx", sheet_name: Optional[str] = None, config: Optional[Dict[str, Any]] = None) -> Dict[str, pd.DataFrame]:
    df, selected_sheet = read_noon_excel(file_obj, file_name=file_name, sheet_name=sheet_name)
    return validate_noon_report(df, file_name=file_name, sheet_name=selected_sheet, config=config)


def combine_results(results: List[Dict[str, pd.DataFrame]]) -> Dict[str, pd.DataFrame]:
    keys = ["summary", "by_rule", "errors", "checked_rows", "skipped_rules", "rules", "columns"]
    combined: Dict[str, pd.DataFrame] = {}
    for key in keys:
        frames = [r[key] for r in results if key in r and not r[key].empty]
        combined[key] = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not combined["errors"].empty:
        combined["by_rule"] = combined["errors"].groupby(["rule_id", "issue_type", "severity"], dropna=False).size().reset_index(name="count")
    if not combined["checked_rows"].empty:
        total_rows = len(combined["checked_rows"])
        rows_with_issues = int((combined["checked_rows"]["issue_count"] > 0).sum())
        combined["portfolio_summary"] = pd.DataFrame([
            {"metric": "Files checked", "value": combined["checked_rows"]["file_name"].nunique()},
            {"metric": "Report rows", "value": total_rows},
            {"metric": "Rows with issues", "value": rows_with_issues},
            {"metric": "Rows OK", "value": total_rows - rows_with_issues},
            {"metric": "Total issues", "value": len(combined["errors"])},
        ])
    else:
        combined["portfolio_summary"] = pd.DataFrame(columns=["metric", "value"])
    return combined


def results_to_excel_bytes(results: Dict[str, pd.DataFrame]) -> bytes:
    output = BytesIO()
    sheet_map = {
        "portfolio_summary": "Summary",
        "captain_message": "Captain Message",
        "recent_errors": "Recent Errors",
        "daily_kpis": "Daily KPIs",
        "by_severity": "By Severity",
        "status_summary": "Status Summary",
        "by_rule": "By Rule",
        "errors": "Errors",
        "checked_rows": "Checked Rows",
        "skipped_rules": "Skipped Rules",
        "rules": "Rules",
        "columns": "Column Mapping",
    }
    with pd.ExcelWriter(output, engine="xlsxwriter", datetime_format="yyyy-mm-dd hh:mm", date_format="yyyy-mm-dd") as writer:
        workbook = writer.book
        header_fmt = workbook.add_format({"bold": True, "bg_color": "#D9EAF7", "border": 1})
        error_fmt = workbook.add_format({"bg_color": "#FDE9D9"})
        ok_fmt = workbook.add_format({"bg_color": "#E2F0D9"})
        for key, sheet in sheet_map.items():
            df = results.get(key, pd.DataFrame())
            if df is None or df.empty:
                df = pd.DataFrame({"note": ["No rows"]})
            df.to_excel(writer, sheet_name=sheet, index=False)
            worksheet = writer.sheets[sheet]
            for col_num, value in enumerate(df.columns.values):
                worksheet.write(0, col_num, value, header_fmt)
                width = min(max(len(str(value)) + 2, 12), 45)
                try:
                    sample = df.iloc[:100, col_num].astype(str).map(len).max()
                    if pd.notna(sample):
                        width = min(max(width, int(sample) + 2), 55)
                except Exception:
                    pass
                worksheet.set_column(col_num, col_num, width)
            worksheet.freeze_panes(1, 0)
            if len(df) > 0 and len(df.columns) > 0:
                worksheet.autofilter(0, 0, len(df), len(df.columns) - 1)
            if sheet == "Checked Rows" and "issue_count" in df.columns:
                issue_idx = list(df.columns).index("issue_count")
                worksheet.conditional_format(1, issue_idx, len(df), issue_idx, {"type": "cell", "criteria": ">", "value": 0, "format": error_fmt})
                worksheet.conditional_format(1, issue_idx, len(df), issue_idx, {"type": "cell", "criteria": "==", "value": 0, "format": ok_fmt})
        workbook.set_properties({"title": "Noon Report Validation Results", "subject": "ANTHEA-style Streamlit checker output"})
    return output.getvalue()
