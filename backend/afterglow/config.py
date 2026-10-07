"""Constants shared by every stage. Values follow ../backend.md sections 4 and 6."""
from __future__ import annotations

import calendar
import os
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("AFTERGLOW_DATA", ROOT / "data"))
CACHE = DATA / "cache"
STATE = DATA / "state"
OUT = Path(os.environ.get("AFTERGLOW_OUT", ROOT / "out")) / "data" / "v1"
REGIONS_YAML = ROOT / "regions.yaml"
USER_AGENT = "afterglow-backend/0.1 (NASA Space Apps 2026 hackathon project; open data only)"

# --- fleet -------------------------------------------------------------------------------
SENSORS = ["T", "A", "N", "J1", "J2"]  # Terra, Aqua, Suomi NPP, NOAA-20, NOAA-21 (fixed order everywhere)
SIDX = {s: i for i, s in enumerate(SENSORS)}
S = len(SENSORS)
REFERENCE = "A"
SENSOR_INFO = {
    "T": dict(name="Terra MODIS", instrument="MODIS", data_start="2000-11-02", planned_end="2027-01",
              end_note="Data collection ends Jan 2027 (planned)"),
    "A": dict(name="Aqua MODIS", instrument="MODIS", data_start="2002-07", planned_end="2027-09",
              end_note="Data collection ends around Sep 2027 (planned)"),
    "N": dict(name="Suomi NPP VIIRS", instrument="VIIRS", data_start="2012-01-20", planned_end="2026-11-01",
              end_note="Product delivery ends 1 Nov 2026 (subject to change)"),
    "J1": dict(name="NOAA-20 VIIRS", instrument="VIIRS", data_start="2018-04-01", planned_end=None, end_note=None),
    "J2": dict(name="NOAA-21 VIIRS", instrument="VIIRS", data_start="2024-01-17", planned_end=None, end_note=None),
}
# FIRMS yearly country files: sensor -> (url folder, file prefix, first year)
FIRMS_COUNTRY = {
    "T+A": ("modis", "modis", 2001),
    "N": ("viirs-snpp", "viirs-snpp", 2012),
    "J1": ("viirs-jpss1", "viirs-jpss1", 2018),
}
FIRMS_API_SOURCES = {"T+A": "MODIS_SP", "N": "VIIRS_SNPP_SP", "J1": "VIIRS_NOAA20_SP", "J2": "VIIRS_NOAA21_SP"}
FIRMS_API_NRT = {"T+A": "MODIS_NRT", "N": "VIIRS_SNPP_NRT", "J1": "VIIRS_NOAA20_NRT", "J2": "VIIRS_NOAA21_NRT"}
# which satellites carry TLEs for "next look" (CelesTrak catalog numbers, verified 2026-10-07)
NORAD = {"T": 25994, "A": 27424, "N": 37849, "J1": 43013, "J2": 54234}
HALF_SWATH_KM = {"T": 1165.0, "A": 1165.0, "N": 1520.0, "J1": 1520.0, "J2": 1520.0}  # FIRMS FAQ: MODIS 2330 km, VIIRS 3040 km
L2_PRODUCTS = {"T": ("MOD14", "061"), "A": ("MYD14", "061"), "N": ("VNP14IMG", "002"),
               "J1": ("VJ114IMG", "002"), "J2": ("VJ214IMG", "002")}
L3_PRODUCTS = {"T": ("MOD14A1", "061"), "A": ("MYD14A1", "061"), "N": ("VNP14A1", "002"),
               "J1": ("VJ114A1", "002"), "J2": ("VJ214A1", "002")}

# --- periods -------------------------------------------------------------------------------
P = 46  # eight-day periods per year, aligned to 1 January
START_DOY = list(range(1, 366, 8))  # [1, 9, ..., 361]


def period_of_doy(doy):
    return np.minimum(P, (np.asarray(doy) - 1) // 8 + 1)


def days_in_period(year: int, p: int) -> int:
    if p < P:
        return 8
    return (366 if calendar.isleap(year) else 365) - 360


# --- MODIS sinusoidal grid (MOD14A1 family; VIIRS L3 uses the same grid) --------------------
R_SIN = 6371007.181
TILE_M = 1111950.5197665233
NPX = 1200
PX_M = TILE_M / NPX
PX_KM2 = (PX_M / 1000.0) ** 2  # 0.858634 km2

# --- science thresholds ----------------------------------------------------------------------
MIN_COV = 0.30
RATE_FLOOR = 0.01       # additive floor on rates (detections per 1000 clear km2-days); replaces a +0.5 pseudo-count that inflated rates when clear-view area was small
MIN_LAND_KM2D = 100.0
Q_MIN = 0.5            # detections per 1000 km2-days: low verdicts only where normal activity exceeds this
P_SURE, P_MAYBE = 0.90, 0.60
MIN_BASELINE_N = 20
Z80, Z95 = 1.2815515655446004, 1.959963984540054
BASELINES = {"2003-2022": (2003, 2022), "2012-2022": (2012, 2022)}
DEFAULT_BASELINE = "2003-2022"
HELD_OUT_FROM = 2023       # held-out years: >= 2023 (calibration: <= 2022)
BOOTSTRAP_B = int(os.environ.get("AFTERGLOW_BOOT", "100"))
# bridge training windows (inclusive years or (year, month) starts): backend.md 6.2
BRIDGES = [  # (from, to, train_start_year, train_end_year)
    ("T", "A", 2003, 2018),
    ("N", "A", 2012, 2018),
    ("J1", "N", 2018, 2022),
    ("J2", "J1", 2024, 2024),
]
CHAIN = {"T": ["T", "A"], "A": ["A"], "N": ["N", "A"], "J1": ["J1", "N", "A"], "J2": ["J2", "J1", "N", "A"]}

# static-source mask (learned from VIIRS detections, training years only)
STATIC_GRID_DEG = 0.0036   # ~400 m
STATIC_MIN_DET, STATIC_MIN_DAYS, STATIC_MIN_MONTHS, STATIC_MIN_YEARS = 5, 5, 3, 2
STATIC_TRAIN_YEARS = (2012, 2022)
DEDUPE_M = 200.0

# verdict codes (JSON)
V_NO_DATA, V_NOT_OBS, V_UNUSUALLY_LOW, V_POSSIBLY_LOW, V_TYPICAL = -1, 0, 1, 2, 3
V_POSSIBLY_HIGH, V_UNUSUALLY_HIGH, V_RECORD, V_INSUFFICIENT, V_PENDING = 4, 5, 6, 7, 8
VERDICT_CODES = {"no_data": -1, "not_observed": 0, "unusually_low": 1, "possibly_low": 2, "typical": 3,
                 "possibly_high": 4, "unusually_high": 5, "record": 6, "insufficient_baseline": 7,
                 "pending_coverage": 8}
# flags bitmask
F_PROVISIONAL, F_HELD_OUT, F_CALIB, F_PARTIAL, F_COV_PENDING, F_COV_PROXY = 1, 2, 4, 8, 16, 32


def class3(code):
    """Collapse verdict codes to 3 classes: 0 low, 1 typical, 2 high ('possibly' folds into typical)."""
    code = np.asarray(code)
    out = np.full(code.shape, 1, dtype=np.int8)
    out[code == V_UNUSUALLY_LOW] = 0
    out[(code == V_UNUSUALLY_HIGH) | (code == V_RECORD)] = 2
    return out


def judged(code):
    code = np.asarray(code)
    return (code >= V_UNUSUALLY_LOW) & (code <= V_RECORD)


for _d in (CACHE, STATE):
    _d.mkdir(parents=True, exist_ok=True)
