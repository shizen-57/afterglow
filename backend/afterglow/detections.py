"""S3: hotspot detections (FIRMS science-quality yearly country files, optional FIRMS API) -> detections.parquet.

Kept detections (x=0) are vegetation-fire pixels with nominal/high confidence. Excluded rows are counted, not dropped:
x=1 static source (FIRMS type 1-3, or inside the learned static mask), x=2 low confidence.
"""
from __future__ import annotations

import io
import os
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

from . import http
from .boundaries import assign_points, load_units, region_cfg, state_dir
from .config import (CACHE, DEDUPE_M, FIRMS_API_SOURCES, FIRMS_COUNTRY, SIDX, STATIC_GRID_DEG, STATIC_MIN_DAYS,
                     STATIC_MIN_DET, STATIC_MIN_MONTHS, STATIC_MIN_YEARS, STATIC_TRAIN_YEARS)

FIRMS = "https://firms.modaps.eosdis.nasa.gov"
EPOCH = np.datetime64("1970-01-01T00:00")


def country_url(kind: str, year: int, country: str) -> str:
    folder, prefix, _ = FIRMS_COUNTRY[kind]
    return f"{FIRMS}/data/country/{folder}/{year}/{prefix}_{year}_{country}.csv"


def normalize(df: pd.DataFrame, kind: str, src: int = 0) -> pd.DataFrame:
    """Raw FIRMS CSV -> internal schema. kind: 'T+A' (MODIS) or a VIIRS sensor id."""
    d = pd.DataFrame()
    hhmm = df["acq_time"].astype(str).str.zfill(4)
    t = pd.to_datetime(df["acq_date"].astype(str) + " " + hhmm.str[:2] + ":" + hhmm.str[2:], utc=False)
    d["t"] = ((t.values.astype("datetime64[m]") - EPOCH) // np.timedelta64(1, "m")).astype(np.int64)
    d["lat"], d["lon"] = df["latitude"].astype(float).values, df["longitude"].astype(float).values
    d["frp"] = pd.to_numeric(df["frp"], errors="coerce").fillna(0.0).values
    d["night"] = (df["daynight"].astype(str) == "N").values
    if kind == "T+A":
        sat = df["satellite"].astype(str).str.lower()
        d["s"] = np.where(sat.str.startswith("t"), SIDX["T"], SIDX["A"]).astype(np.int8)
        conf = pd.to_numeric(df["confidence"], errors="coerce").fillna(0).values
        d["conf"] = np.where(conf < 30, 0, np.where(conf < 80, 1, 2)).astype(np.int8)
    else:
        sat = df["satellite"].astype(str)
        sid = {"N": "N", "N20": "J1", "N21": "J2"}
        d["s"] = sat.map(lambda x: SIDX[sid.get(x, kind)]).astype(np.int8).values
        c = df["confidence"].astype(str).str.lower().str[0]
        d["conf"] = c.map({"l": 0, "n": 1, "h": 2}).fillna(1).astype(np.int8).values
    d["type"] = pd.to_numeric(df["type"], errors="coerce").fillna(-1).astype(np.int8).values if "type" in df else -1
    d["src"] = np.int8(src)
    return d


def dedupe_viirs(d: pd.DataFrame) -> pd.DataFrame:
    """Same sensor, same acquisition minute, centres within DEDUPE_M: keep the highest FRP (3-D KD-tree, O(n log n))."""
    out = []
    for s, g in d.groupby("s"):
        if len(g) < 2:
            out.append(g)
            continue
        y = g["lat"].values * 111.32
        x = g["lon"].values * 111.32 * np.cos(np.radians(g["lat"].values))
        z = (g["t"].values - g["t"].values.min()) * 1000.0  # km: different minutes are never neighbours
        pairs = cKDTree(np.column_stack([x, y, z])).query_pairs(DEDUPE_M / 1000.0, output_type="ndarray")
        if len(pairs) == 0:
            out.append(g)
            continue
        n = len(g)
        m = coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(n, n))
        _, comp = connected_components(m, directed=False)
        order = np.argsort(-g["frp"].values, kind="stable")
        _, first = np.unique(comp[order], return_index=True)
        out.append(g.iloc[np.sort(order[first])])
    return pd.concat(out, ignore_index=True)


def learn_static_mask(d: pd.DataFrame) -> set[tuple[int, int]]:
    """400 m cells with repeated, long-season activity in >= 2 training years (VIIRS only; sensor-agnostic cells)."""
    v = d[d["s"] >= SIDX["N"]]
    ts = (EPOCH + v["t"].values.astype("timedelta64[m]"))
    yr = ts.astype("datetime64[Y]").astype(int) + 1970
    v = v[(yr >= STATIC_TRAIN_YEARS[0]) & (yr <= STATIC_TRAIN_YEARS[1])]
    if v.empty:
        return set()
    ts = EPOCH + v["t"].values.astype("timedelta64[m]")
    k = pd.DataFrame({"cx": np.floor(v["lon"].values / STATIC_GRID_DEG).astype(np.int32),
                      "cy": np.floor(v["lat"].values / STATIC_GRID_DEG).astype(np.int32),
                      "year": ts.astype("datetime64[Y]").astype(int) + 1970,
                      "day": ts.astype("datetime64[D]").astype(np.int64),
                      "month": ts.astype("datetime64[M]").astype(int) % 12})
    g = k.groupby(["cx", "cy", "year"]).agg(n=("day", "size"), days=("day", "nunique"), months=("month", "nunique"))
    g = g[(g.n >= STATIC_MIN_DET) & (g.days >= STATIC_MIN_DAYS) & (g.months >= STATIC_MIN_MONTHS)]
    cy = g.reset_index().groupby(["cx", "cy"])["year"].nunique()
    return set(map(tuple, cy[cy >= STATIC_MIN_YEARS].reset_index()[["cx", "cy"]].values.tolist()))


def apply_static(d: pd.DataFrame, mask: set[tuple[int, int]]) -> np.ndarray:
    """Boolean per row. VIIRS: exact 400 m cell; MODIS (1 km pixels): the cell or any of its 8 neighbours."""
    if not mask:
        return np.zeros(len(d), bool)
    cx = np.floor(d["lon"].values / STATIC_GRID_DEG).astype(np.int64)
    cy = np.floor(d["lat"].values / STATIC_GRID_DEG).astype(np.int64)
    key = lambda a, b: a * 4_000_003 + b
    mk = np.array([key(a, b) for a, b in mask], dtype=np.int64)
    hit = np.isin(key(cx, cy), mk)
    modis = d["s"].values < SIDX["N"]
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx or dy:
                hit |= modis & np.isin(key(cx + dx, cy + dy), mk)
    return hit


def fetch_country_years(region: str, years: tuple[int, int], workers: int = 8):
    cfg = region_cfg(region)
    jobs = []
    for kind, (_, _, y0) in FIRMS_COUNTRY.items():
        for y in range(max(years[0], y0), years[1] + 1):
            jobs.append((kind, y))

    def one(job):
        kind, y = job
        p = CACHE / "firms_country" / f"{kind.replace('+', '')}_{y}_{cfg['firms_country']}.csv"
        got = http.download(country_url(kind, y, cfg["firms_country"]), p, allow_404=True)
        return job, got

    with ThreadPoolExecutor(workers) as ex:
        return list(ex.map(one, jobs))


def fetch_api_gap(region: str, kind: str, start, end, key: str) -> pd.DataFrame:
    """Fill dates after the last yearly country file via the FIRMS area API (needs FIRMS_MAP_KEY). Untested here (no key);
    the API CSV has no 'type' column, so the learned static mask is the only static filter for these rows."""
    cfg = region_cfg(region)
    w, s, e, n = cfg["bbox"]
    frames = []
    day = pd.Timestamp(start)
    while day <= pd.Timestamp(end):
        url = f"{FIRMS}/api/area/csv/{key}/{FIRMS_API_SOURCES[kind]}/{w},{s},{e},{n}/5/{day:%Y-%m-%d}"
        txt = http.get(url).text
        if txt.strip() and txt.lstrip().startswith("latitude") or txt.startswith("country_id"):
            frames.append(pd.read_csv(io.StringIO(txt)))
        day += pd.Timedelta(days=5)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def run(region: str, years: tuple[int, int]):
    cfg = region_cfg(region)
    units = load_units(region)
    w, s, e, n = cfg["bbox"]
    res = fetch_country_years(region, years)
    frames, avail, raw_rows = [], {}, {}
    for (kind, y), path in res:
        if path is None:
            print(f"  missing (not published): {kind} {y}")
            continue
        raw = pd.read_csv(path)
        if len(raw) == 0:
            continue
        raw_rows[(kind, y)] = len(raw)
        frames.append(normalize(raw, kind, 0))
        avail.setdefault(kind, []).append(y)
    key = os.environ.get("FIRMS_MAP_KEY")
    if key:
        for kind in ("T+A", "N", "J1", "J2"):
            last = max(avail.get(kind, [years[0] - 1]))
            start = pd.Timestamp(f"{last + 1}-01-01")
            end = min(pd.Timestamp.utcnow().tz_localize(None).normalize(), pd.Timestamp(f"{years[1]}-12-31"))
            if kind == "J2":
                start = max(start, pd.Timestamp("2024-01-17"))
            if start <= end:
                raw = fetch_api_gap(region, kind, start, end, key)
                if len(raw):
                    frames.append(normalize(raw, kind if kind != "T+A" else "T+A", 0))
                    avail.setdefault(kind, []).append(int(end.year))
    else:
        print("  FIRMS_MAP_KEY not set: data after the last published yearly file (and NOAA-21) is unavailable.")
    d = pd.concat(frames, ignore_index=True)
    d = d[(d["lon"] >= w) & (d["lon"] <= e) & (d["lat"] >= s) & (d["lat"] <= n)].reset_index(drop=True)
    d = d.drop_duplicates(["s", "t", "lat", "lon"])
    v = d["s"] >= SIDX["N"]
    d = pd.concat([d[~v], dedupe_viirs(d[v])], ignore_index=True)
    d["unit"] = assign_points(units, d["lon"].values, d["lat"].values)
    d = d[d["unit"] >= 0].reset_index(drop=True)
    mask = learn_static_mask(d)
    static = (d["type"].values > 0) | apply_static(d, mask)
    d["x"] = np.where(static, 1, np.where(d["conf"].values == 0, 2, 0)).astype(np.int8)
    d.sort_values("t", inplace=True, ignore_index=True)
    sd = state_dir(region)
    d.to_parquet(sd / "detections.parquet", index=False)
    pd.DataFrame(sorted(mask), columns=["cx", "cy"]).to_parquet(sd / "static_mask.parquet", index=False)
    ends = {k: f"{max(v)}-12-31" for k, v in avail.items()}
    import json
    ts = EPOCH + d["t"].values.astype("timedelta64[m]")
    d_year = ts.astype("datetime64[Y]").astype(int) + 1970
    rec = {}
    for (kind, y), nraw in raw_rows.items():
        sens = (SIDX["T"], SIDX["A"]) if kind == "T+A" else (SIDX[kind],)
        kept = int(((d_year == y) & np.isin(d["s"].values, sens)).sum())
        rec[f"{kind}:{y}"] = dict(raw=nraw, loaded=kept, dropped_frac=round(1 - kept / max(1, nraw), 4))
    (sd / "detections_meta.json").write_text(json.dumps(dict(
        available_years=avail, series_end=ends, static_cells=len(mask), rows=int(len(d)),
        kept=int((d.x == 0).sum()), static=int((d.x == 1).sum()), lowconf=int((d.x == 2).sum()),
        map_key_used=bool(key), reconciliation=rec)), encoding="utf-8")
    print(f"  rows={len(d):,} kept={int((d.x == 0).sum()):,} static={int((d.x == 1).sum()):,} "
          f"lowconf={int((d.x == 2).sum()):,} static_cells={len(mask)}")
    print("  available years:", {k: (min(v), max(v)) for k, v in avail.items()})
