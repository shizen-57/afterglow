"""Live path: next satellite passes from public TLEs (CelesTrak + SGP4) and near-real-time hotspots (needs FIRMS_MAP_KEY).

Pass geometry is approximate: sub-satellite point from SGP4 (TEME -> Earth-fixed by GMST rotation, spherical lat/lon);
a district is 'in view' when the great-circle distance from the sub-satellite point to its centroid is at most half the
instrument swath minus the district's equivalent radius. Real historical pass times come from CMR (passes.py).
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import time

import numpy as np
import pandas as pd
from sgp4.api import Satrec, jday

from . import http
from .boundaries import districts, load_units, region_cfg, state_dir
from .config import CACHE, HALF_SWATH_KM, NORAD, SENSORS, SENSOR_INFO, SIDX

CELESTRAK = "https://celestrak.org/NORAD/elements/gp.php"
EARTH_R = 6371.0


def fetch_tle(cat: int, max_age_h: float = 6.0) -> tuple[str, str, str]:
    p = CACHE / "tle" / f"{cat}.txt"
    if not p.exists() or time.time() - p.stat().st_mtime > max_age_h * 3600:
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            p.write_text(http.get(CELESTRAK, params={"CATNR": cat, "FORMAT": "TLE"}).text, encoding="utf-8")
        except Exception:
            if not p.exists():
                raise
    lines = [l.rstrip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    if len(lines) < 3:
        raise RuntimeError(f"unexpected TLE response for {cat}: {lines}")
    return lines[0].strip(), lines[1], lines[2]


def gmst_rad(jd: np.ndarray) -> np.ndarray:
    d = jd - 2451545.0
    t = d / 36525.0
    g = 280.46061837 + 360.98564736629 * d + 0.000387933 * t**2 - t**3 / 38710000.0
    return np.radians(g % 360.0)


def solar_zenith_deg(jd: float, lat: float, lon: float) -> float:
    n = jd - 2451545.0
    L = (280.46 + 0.9856474 * n) % 360
    g = math.radians((357.528 + 0.9856003 * n) % 360)
    lam = math.radians(L + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g))
    eps = math.radians(23.439 - 4e-7 * n)
    dec = math.asin(math.sin(eps) * math.sin(lam))
    ra = math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))
    h = float(gmst_rad(np.array([jd]))[0]) + math.radians(lon) - ra
    la = math.radians(lat)
    cz = math.sin(la) * math.sin(dec) + math.cos(la) * math.cos(dec) * math.cos(h)
    return math.degrees(math.acos(max(-1.0, min(1.0, cz))))


def subpoint(sat: Satrec, times: pd.DatetimeIndex):
    jd, fr = zip(*[jday(t.year, t.month, t.day, t.hour, t.minute, t.second) for t in times])
    jd, fr = np.array(jd), np.array(fr)
    e, r, _ = sat.sgp4_array(jd, fr)
    ok = e == 0
    th = gmst_rad(jd + fr)
    x = r[:, 0] * np.cos(th) + r[:, 1] * np.sin(th)
    y = -r[:, 0] * np.sin(th) + r[:, 1] * np.cos(th)
    lat = np.degrees(np.arctan2(r[:, 2], np.hypot(x, y)))
    lon = np.degrees(np.arctan2(y, x))
    lat[~ok], lon[~ok] = np.nan, np.nan
    return lat, lon, jd + fr


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2
    return 2 * EARTH_R * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def next_passes(units: list[dict], hours: float = 24.0, step_s: int = 30, now: dt.datetime | None = None) -> list[dict]:
    now = (now or dt.datetime.now(dt.timezone.utc)).replace(microsecond=0)
    times = pd.date_range(now, periods=int(hours * 3600 / step_s) + 1, freq=f"{step_s}s", tz=None)
    times = pd.DatetimeIndex([t.tz_localize(None) if t.tzinfo else t for t in times])
    dist = districts(units)
    c_lon = np.array([u["centroid"][0] for u in dist])
    c_lat = np.array([u["centroid"][1] for u in dist])
    radius = np.sqrt(np.array([u["area_km2"] for u in dist]) / math.pi)
    reg = units[-1]
    out = []
    for s in SENSORS:
        end = SENSOR_INFO[s]["planned_end"]
        if end and pd.Timestamp(end + ("-01" if len(end) == 7 else "")) < pd.Timestamp(now.date()):
            continue
        try:
            name, l1, l2 = fetch_tle(NORAD[s])
        except Exception as ex:
            print(f"  ! TLE for {s} unavailable: {ex}")
            continue
        sat = Satrec.twoline2rv(l1, l2)
        lat, lon, jdt = subpoint(sat, times)
        d = haversine_km(lat[:, None], lon[:, None], c_lat[None, :], c_lon[None, :])
        margin = HALF_SWATH_KM[s] - radius[None, :] - d  # >0 means in view
        inview = margin > 0
        any_in = inview.any(1)
        runs, start = [], None
        for i, v in enumerate(any_in):
            if v and start is None:
                start = i
            if (not v or i == len(any_in) - 1) and start is not None:
                runs.append((start, i if v else i - 1))
                start = None
        for a, b in runs:
            best = a + int(np.argmax(margin[a:b + 1].max(1)))
            bits = 0
            for u in np.flatnonzero(inview[a:b + 1].any(0)):
                bits |= 1 << int(u)
            zen = solar_zenith_deg(float(jdt[best]), reg["centroid"][1], reg["centroid"][0])
            out.append(dict(s=SIDX[s], t=times[best].strftime("%Y-%m-%dT%H:%M:%SZ"), n=int(zen > 85.0), u=format(bits, "x"),
                            min_distance_km=round(float(d[best].min()), 1)))
    out.sort(key=lambda p: p["t"])
    return out


def nrt_detections(region: str, days: int = 5) -> tuple[dict, list[dict], str | None]:
    """Last few days of near-real-time hotspots via the FIRMS area API. Needs FIRMS_MAP_KEY; untested without a key."""
    from . import detections as det

    key = os.environ.get("FIRMS_MAP_KEY")
    if not key:
        return {}, [], None
    from .boundaries import assign_points
    cfg = region_cfg(region)
    units = load_units(region)
    w, s, e, n = cfg["bbox"]
    frames = []
    for kind, src in (("T+A", "MODIS_NRT"), ("N", "VIIRS_SNPP_NRT"), ("J1", "VIIRS_NOAA20_NRT"), ("J2", "VIIRS_NOAA21_NRT")):
        try:
            txt = http.get(f"{det.FIRMS}/api/area/csv/{key}/{src}/{w},{s},{e},{n}/{days}").text
            if txt.startswith("latitude") or txt.startswith("country_id"):
                import io
                frames.append(det.normalize(pd.read_csv(io.StringIO(txt)), kind, 1))
        except Exception as ex:
            print(f"  ! NRT {src}: {ex}")
    if not frames:
        return {}, [], None
    d = pd.concat(frames, ignore_index=True)
    d["unit"] = assign_points(units, d["lon"].values, d["lat"].values)
    d = d[d["unit"] >= 0]
    mask = set(map(tuple, pd.read_parquet(state_dir(region) / "static_mask.parquet").values.tolist()))
    static = (d["type"].values > 0) | det.apply_static(d, mask)
    d["x"] = np.where(static, 1, np.where(d["conf"].values == 0, 2, 0))
    ts = pd.Timestamp("1970-01-01") + pd.to_timedelta(d["t"].values, unit="m")
    prov = sorted({(int(y), int(min(46, (doy - 1) // 8 + 1))) for y, doy in zip(ts.year, ts.dayofyear)})
    cols = dict(lon=d["lon"].round(4).tolist(), lat=d["lat"].round(4).tolist(), s=d["s"].astype(int).tolist(),
                t=d["t"].astype(int).tolist(), frp=d["frp"].round(1).tolist(), c=d["conf"].astype(int).tolist(),
                x=d["x"].astype(int).tolist(), u=d["unit"].astype(int).tolist(), src=[1] * len(d))
    return cols, [dict(year=y, period=p) for y, p in prov], str(ts.max().date())


def run(region: str, out_dir: str | None = None):
    from .config import OUT
    from pathlib import Path
    from .export import write
    units = load_units(region)
    gen = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    passes = next_passes(units)
    det_cols, prov, through = nrt_detections(region)
    notes = ["Next passes are predicted from public TLEs with a simple swath model; orbit paths are approximate."]
    if not det_cols:
        notes.append("No near-real-time detections: FIRMS_MAP_KEY not set.")
    obj = dict(schema="afterglow/nrt@1", generated_at=gen, data_through=through, detections=det_cols, next_passes=passes,
               provisional=prov, notes=notes)
    (state_dir(region) / "nrt.json").write_text(json.dumps(obj, separators=(",", ":")), encoding="utf-8")
    out = Path(out_dir) if out_dir else OUT
    write(out / "nrt" / f"{region}.json", "nrt", obj)
    print(f"  next passes (24 h): {len(passes)}; NRT detections: {len(det_cols.get('lon', []))}")
    for p in passes[:6]:
        print("   ", SENSORS[p["s"]], p["t"], "night" if p["n"] else "day", f"min dist {p['min_distance_km']} km")
