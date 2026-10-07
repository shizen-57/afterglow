"""Adapter: write the 'calibrated model JSON' (version 1) that frontend/src/data.js parseDataset() imports.

Mapping (see frontend/README.md "Calibrated model JSON"):
  observations  <- detections.parquet (kept, static-excluded and low-confidence rows; static rows get excluded=true)
  estimates     <- harmonized index per district (and 'Bangladesh') x year x period (0-based period 0..45)
    value / lower / upper  = H and its 80% interval (detections per 1,000 clear-view km2-days, Aqua-MODIS scale)
    probability            = Pr(above the 90th percentile of the 2003-2022 baseline)  (the frontend's 'Pr(unusual)')
    coverage               = best clear-view share of any contributing satellite, percent (0-100)
    baselineMedian         = baseline median of H for that period
    grounded               = estimate recomputed with Terra, Aqua and S-NPP switched off (only where NOAA-20/21 data exist)
  Periods the satellites could not see (verdict 'not observed', coverage < 30%) carry value=lower=upper=probability=0 and the
  real coverage; the frontend reads coverage < 30 as 'Not observed'. Periods without a baseline are omitted.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import aggregate, science
from .boundaries import districts, load_units, state_dir
from .config import DEFAULT_BASELINE, OUT, P, Z80, judged
from .core import combine, verdict

MAX_BYTES = 48 * 1024 * 1024  # the frontend rejects files over 50 MB
EPOCH = pd.Timestamp("1970-01-01")
CONF = {0: "l", 1: "n", 2: "h"}


def run(region: str, out_dir: str | None = None, obs_years: str = "2022-2024"):
    A, pmeta = aggregate.load(region)
    Z, smeta = science.load(region)
    units = load_units(region)
    U = len(districts(units))
    y0, y1 = pmeta["years"]
    Y = y1 - y0 + 1
    names = [u["name"] for u in units]  # district names are geoBoundaries shapeName, identical to the frontend's; country = 'Bangladesh'
    base = {q: Z[f"base_{DEFAULT_BASELINE}_{q}"] for q in ("q10", "q50", "q90", "max", "n")}
    code = Z["code"]
    covmax = np.nanmax(np.where(A["active"], A["cov"], np.nan), axis=0)
    mu, sg, ph = Z["mu_c"], Z["sg_c"], Z["p_hi"]
    # grounded: Terra, Aqua and S-NPP off (as planned for 2027)
    r = smeta["r"]
    mu_g, sg_g, _ = combine(Z["per_mu"], Z["per_sg"], np.array([False, False, False, True, True]), r)
    code_g, ph_g, _ = verdict(mu_g, sg_g, base["q10"], base["q50"], base["q90"], base["max"], base["n"])

    est = []
    ok_year = (y0 + np.arange(Y)) >= 2003
    for u, k, p in zip(*np.nonzero((judged(code) | (code == 0)) & ok_year[None, :, None])):
        cv = covmax[u, k, p]
        if not np.isfinite(cv):
            continue
        year = int(y0 + k)
        q50 = base["q50"][u, k, p]
        if judged(code[u, k, p]):
            h, lo, hi = float(np.exp(mu[u, k, p])), float(np.exp(mu[u, k, p] - Z80 * sg[u, k, p])), float(np.exp(mu[u, k, p] + Z80 * sg[u, k, p]))
            rec = dict(district=names[u], year=year, period=int(p), value=round(h, 5), lower=round(min(lo, h), 5),
                       upper=round(max(hi, h), 5), probability=round(float(ph[u, k, p]), 4), coverage=round(float(cv) * 100, 1),
                       baselineMedian=round(float(q50), 5))
            if np.isfinite(mu_g[u, k, p]) and judged(code_g[u, k, p]):
                hg = float(np.exp(mu_g[u, k, p]))
                lg, ug = float(np.exp(mu_g[u, k, p] - Z80 * sg_g[u, k, p])), float(np.exp(mu_g[u, k, p] + Z80 * sg_g[u, k, p]))
                rec["grounded"] = dict(value=round(hg, 5), lower=round(min(lg, hg), 5), upper=round(max(ug, hg), 5),
                                       probability=round(float(ph_g[u, k, p]), 4))
        else:
            rec = dict(district=names[u], year=year, period=int(p), value=0, lower=0, upper=0, probability=0,
                       coverage=round(float(cv) * 100, 1), baselineMedian=round(float(q50), 5) if np.isfinite(q50) else 0)
        est.append(rec)

    d = pd.read_parquet(state_dir(region) / "detections.parquet")
    a, _, b = obs_years.partition("-")
    lo_y, hi_y = (0, 9999) if obs_years == "all" else (int(a), int(b or a))
    ts = EPOCH + pd.to_timedelta(d["t"].values, unit="m")
    d = d[(ts.year >= lo_y) & (ts.year <= hi_y)].copy()
    ts = EPOCH + pd.to_timedelta(d["t"].values, unit="m")
    sens = np.array(["T", "A", "N", "J1", "J2"])
    obs = pd.DataFrame({"latitude": d["lat"].round(5).values, "longitude": d["lon"].round(5).values,
                        "satellite": sens[d["s"].values], "acq_date": ts.strftime("%Y-%m-%d").values,
                        "acq_time": ts.strftime("%H%M").values, "confidence": d["conf"].map(CONF).values,
                        "frp": d["frp"].round(1).values, "district": [names[i] for i in d["unit"].values],
                        "excluded": (d["x"].values == 1)}).to_dict("records")

    prov = (f"Afterglow pipeline · FIRMS science-quality detections (MODIS C6.1, VIIRS C2) through {max(smeta['windows'][s][1] for s in smeta['windows'] if smeta['windows'][s])}"
            f" · clear-view coverage from MODIS L3 fire masks; VIIRS coverage {'proxied from Aqua' if smeta['cov_src'].get('N') == 'proxy_A' else 'native'}"
            f" · bridges trained on 2003-2022, held-out 2023+ · baseline {DEFAULT_BASELINE} · units: detections per 1,000 clear-view km2-days on the Aqua MODIS scale")
    model = dict(version=1, provenance=prov, observations=obs, estimates=est)
    raw = json.dumps(model, separators=(",", ":"), allow_nan=False)
    while len(raw) > MAX_BYTES and lo_y < hi_y:  # drop the oldest observation year until the file fits
        lo_y += 1
        obs = [o for o in obs if int(o["acq_date"][:4]) >= lo_y]
        model["observations"] = obs
        raw = json.dumps(model, separators=(",", ":"), allow_nan=False)
    out = (Path(out_dir) if out_dir else OUT.parents[1] / "frontend")
    out.mkdir(parents=True, exist_ok=True)
    path = out / "afterglow-model.json"
    path.write_text(raw, encoding="utf-8")
    ng = sum(1 for e in est if "grounded" in e)
    print(f"  wrote {path}  ({len(raw) / 1e6:.1f} MB): {len(obs):,} observations, {len(est):,} estimates ({ng:,} with grounded)")
    return path
