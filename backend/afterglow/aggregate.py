"""S6: period aggregation -> state/{region}/periods.npz (dense arrays [S, U+1, Y, 46]; index U is the country).

Activity rule: a sensor contributes to a period only if the whole period lies inside that sensor's data window and
coverage records exist. Everything else is NaN (never zero).

VIIRS coverage: native LP DAAC masks when ingested (coverage-viirs), otherwise a PROXY copied from same-day Aqua MODIS
coverage (recorded in meta as cov_src='proxy_A' and flagged F_COV_PROXY downstream). The proxy is an approximation.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import coverage, passes as passes_mod
from .boundaries import districts, load_units, state_dir
from .config import P, PX_KM2, SENSORS, SIDX, S, days_in_period

EPOCH = pd.Timestamp("1970-01-01")


def _yp(day_int: np.ndarray):
    d = pd.to_datetime(day_int, unit="D")
    doy = d.dayofyear.values
    return d.year.values.astype(np.int32), np.minimum(P, (doy - 1) // 8 + 1).astype(np.int16), doy


def run(region: str, years: tuple[int, int]):
    sd = state_dir(region)
    units = load_units(region)
    U = len(districts(units))
    y0, y1 = years
    Y = y1 - y0 + 1
    det = pd.read_parquet(sd / "detections.parquet")
    dmeta = json.loads((sd / "detections_meta.json").read_text())
    series_end = dmeta["series_end"]  # {'T+A': '2024-12-31', 'N': ..., 'J1': ...}

    # ---------------- sensor data windows ----------------
    t_min = pd.to_datetime(det.groupby("s")["t"].min().values, unit="m")
    first_det = {SENSORS[s]: t.normalize() for s, t in zip(det.groupby("s")["t"].min().index, t_min)}
    cov_all = coverage.load_coverage(region)
    cov_v = coverage.load_viirs_coverage(region)
    first_cov = {s: pd.Timestamp(EPOCH + pd.Timedelta(days=int(cov_all[cov_all.sat == s]["date"].min()))) for s in "TA"
                 if (cov_all.sat == s).any()}
    win = {}
    for s in SENSORS:
        end = pd.Timestamp(series_end["T+A" if s in "TA" else s]) if ("T+A" if s in "TA" else s) in series_end else None
        if s in "TA":
            start = max(pd.Timestamp(f"{y0}-01-01"), first_cov.get(s, pd.Timestamp("2100-01-01")))
        else:
            start = first_det.get(s)
        if end is None or start is None:
            win[s] = None
        else:
            win[s] = (start, end)

    # ---------------- daily coverage per sensor ----------------
    daily, cov_src = {}, {}
    a_rows = cov_all[cov_all.sat == "A"]
    for s in SENSORS:
        if win[s] is None:
            cov_src[s] = "none"
            continue
        lo = (win[s][0] - EPOCH).days
        hi = (win[s][1] - EPOCH).days
        if s in "TA":
            rows = cov_all[cov_all.sat == s]
            cov_src[s] = "native"
        else:
            nat = cov_v[cov_v.sat == s]
            if len(nat):
                rows, cov_src[s] = nat, "native"
            else:
                rows, cov_src[s] = a_rows.assign(sat=s), "proxy_A"
        daily[s] = rows[(rows.date >= lo) & (rows.date <= hi)]

    shape = (S, U + 1, Y, P)
    nan = lambda: np.full(shape, np.nan, np.float32)
    clear, cloud, missing = nan(), nan(), nan()
    n_days = np.zeros(shape, np.int8)
    land_px_u = np.zeros(U, np.float64)
    for s in SENSORS:
        if s not in daily or daily[s].empty:
            continue
        r = daily[s].copy()
        r["year"], r["p"], _ = _yp(r["date"].values)
        r = r[(r.year >= y0) & (r.year <= y1)]
        g = r.groupby(["unit", "year", "p"]).agg(clear=("clear", "sum"), cloud=("cloud", "sum"), land=("land", "sum"),
                                                 nd=("date", "nunique")).reset_index()
        i = SIDX[s]
        u, yy, pp = g["unit"].values, (g["year"].values - y0), g["p"].values - 1
        clear[i, u, yy, pp] = g["clear"].values * PX_KM2
        cloud[i, u, yy, pp] = g["cloud"].values * PX_KM2
        missing[i, u, yy, pp] = g["land"].values * PX_KM2 - clear[i, u, yy, pp] - cloud[i, u, yy, pp]
        n_days[i, u, yy, pp] = g["nd"].values
        lp = r.groupby("unit")["land"].max()
        land_px_u[lp.index.values] = np.maximum(land_px_u[lp.index.values], lp.values)
    # period land area (same for every sensor)
    dip = np.array([[days_in_period(y0 + k, p + 1) for p in range(P)] for k in range(Y)], np.float64)
    land = np.zeros((U + 1, Y, P), np.float32)
    land[:U] = (land_px_u[:, None, None] * PX_KM2 * dip[None]).astype(np.float32)
    land[U] = land[:U].sum(0)
    # activity: full period inside the sensor window AND coverage recorded
    active = np.zeros(shape, bool)
    for s in SENSORS:
        if win[s] is None:
            continue
        for k in range(Y):
            for p in range(P):
                start = pd.Timestamp(f"{y0 + k}-01-01") + pd.Timedelta(days=(p * 8))
                end = start + pd.Timedelta(days=int(dip[k, p]) - 1)
                if start >= win[s][0] and end <= win[s][1]:
                    active[SIDX[s], :, k, p] = True
    # country = sum of districts
    for arr in (clear, cloud, missing):
        arr[:, U] = np.nansum(arr[:, :U], axis=1)
        arr[:, U][np.all(np.isnan(arr[:, :U]), axis=1)] = np.nan
    n_days[:, U] = n_days[:, :U].min(axis=1)
    active &= (n_days > 0)

    # ---------------- detections per period ----------------
    ts = EPOCH + pd.to_timedelta(det["t"].values, unit="m")
    det = det.assign(year=ts.year.values, p=np.minimum(P, (ts.dayofyear.values - 1) // 8 + 1))
    det = det[(det.year >= y0) & (det.year <= y1)]
    D, Dn = np.zeros(shape, np.float32), np.zeros(shape, np.float32)
    ex_static, ex_low = np.zeros(shape, np.float32), np.zeros(shape, np.float32)
    frp_sum = np.zeros(shape, np.float32)
    frp_p50 = np.full(shape, np.nan, np.float32)

    def acc(df, unit_col):
        kept = df[df.x == 0]
        for arr, sub in ((D, kept), (Dn, kept[kept.night])):
            g = sub.groupby(["s", unit_col, "year", "p"]).size()
            if len(g):
                idx = np.array(g.index.to_list())
                arr[idx[:, 0], idx[:, 1], idx[:, 2] - y0, idx[:, 3] - 1] = g.values
        for arr, sub in ((ex_static, df[df.x == 1]), (ex_low, df[df.x == 2])):
            g = sub.groupby(["s", unit_col, "year", "p"]).size()
            if len(g):
                idx = np.array(g.index.to_list())
                arr[idx[:, 0], idx[:, 1], idx[:, 2] - y0, idx[:, 3] - 1] = g.values
        g = kept.groupby(["s", unit_col, "year", "p"])["frp"].agg(["sum", "median"])
        if len(g):
            idx = np.array(g.index.to_list())
            frp_sum[idx[:, 0], idx[:, 1], idx[:, 2] - y0, idx[:, 3] - 1] = g["sum"].values
            frp_p50[idx[:, 0], idx[:, 1], idx[:, 2] - y0, idx[:, 3] - 1] = g["median"].values

    acc(det, "unit")
    det_c = det.assign(unit_c=U)
    acc(det_c, "unit_c")
    for arr in (D, Dn, ex_static, ex_low, frp_sum):
        arr[~active] = np.nan
    frp_p50[~active] = np.nan
    cov = np.where(active, clear / np.where(land[None] > 0, land[None], np.nan), np.nan).astype(np.float32)
    for arr in (clear, cloud, missing):
        arr[~active] = np.nan

    # ---------------- passes per period + daily "seen" ----------------
    n_passes = np.zeros(shape, np.int16)
    pdf = passes_mod.load(region)
    if pdf is not None and len(pdf):
        t = EPOCH + pd.to_timedelta(pdf["t"].values, unit="m")
        yy, pp = t.year.values - y0, np.minimum(P, (t.dayofyear.values - 1) // 8 + 1) - 1
        bits = [int(b, 16) for b in pdf["bits"].values]
        for u in range(U):
            has = np.array([(b >> u) & 1 for b in bits], bool)
            ok = has & (yy >= 0) & (yy < Y)
            np.add.at(n_passes, (pdf["s"].values[ok], u, yy[ok], pp[ok]), 1)
        anyu = np.array([b != 0 for b in bits], bool) & (yy >= 0) & (yy < Y)
        np.add.at(n_passes, (pdf["s"].values[anyu], U, yy[anyu], pp[anyu]), 1)
    seen = np.full((S, Y, 366, U), -1, np.int8)
    for s in SENSORS:
        if s not in daily or daily[s].empty:
            continue
        r = daily[s].copy()
        r["year"], _, r["doy"] = _yp(r["date"].values)
        r = r[(r.year >= y0) & (r.year <= y1) & (r.land > 0)]
        seen[SIDX[s], r["year"].values - y0, r["doy"].values - 1, r["unit"].values] = np.round(
            100.0 * r["clear"].values / r["land"].values).astype(np.int8)

    np.savez_compressed(sd / "periods.npz", D=D, Dn=Dn, ex_static=ex_static, ex_low=ex_low, frp_sum=frp_sum,
                        frp_p50=frp_p50, clear=clear, cloud=cloud, missing=missing, cov=cov, land=land,
                        n_days=n_days, n_passes=n_passes, active=active, seen=seen)
    (sd / "periods_meta.json").write_text(json.dumps(dict(
        years=[y0, y1], U=U, windows={k: (None if v is None else [str(v[0].date()), str(v[1].date())]) for k, v in win.items()},
        cov_src=cov_src, passes_available=pdf is not None and len(pdf) > 0)), encoding="utf-8")
    print("  windows:", {k: (None if v is None else (str(v[0].date()), str(v[1].date()))) for k, v in win.items()})
    print("  coverage source:", cov_src)
    for s in SENSORS:
        a = active[SIDX[s], :U]
        print(f"  {s}: active unit-periods={int(a.sum()):,}  median cov={np.nanmedian(cov[SIDX[s], :U]):.2f}  "
              f"kept detections={np.nansum(D[SIDX[s], :U]):,.0f}")


def load(region: str):
    sd = state_dir(region)
    z = np.load(sd / "periods.npz")
    meta = json.loads((sd / "periods_meta.json").read_text())
    return {k: z[k] for k in z.files}, meta
