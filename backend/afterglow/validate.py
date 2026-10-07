"""S8: validation -> state/{region}/validation.json (backend.md section 7).

Every number comes from the published bridges and the shared combine/verdict code. Held-out = years >= HELD_OUT_FROM that
have data. With few held-out years the year-block CI is unreliable; a unit-block CI is reported next to it and a warning
is written into the file.
"""
from __future__ import annotations

import datetime as dt
import json

import numpy as np
from scipy.stats import spearmanr

from . import aggregate, science
from .boundaries import districts, load_units, state_dir
from .config import (DEFAULT_BASELINE, HELD_OUT_FROM, MIN_COV, RATE_FLOOR, REFERENCE, S, SIDX, Z80, Z95, class3, judged)
from .core import combine, kappa, raw_class, verdict


def _cls(code):
    return class3(code)


def _kappa_ci(ref, cand, units, years, B=1000, seed=7):
    """kappa with year-block and unit-block bootstrap CIs over aligned cell arrays."""
    rng = np.random.default_rng(seed)
    k0 = kappa(ref, cand)
    out = {"kappa": k0, "n": int(len(ref))}
    for name, grp in (("ci_year", years), ("ci_unit", units)):
        keys = np.unique(grp)
        if len(keys) < 2 or len(ref) < 20:
            out[name] = None
            continue
        idx_by = {k: np.flatnonzero(grp == k) for k in keys}
        ks = []
        for _ in range(B):
            pick = rng.choice(keys, size=len(keys), replace=True)
            idx = np.concatenate([idx_by[k] for k in pick])
            ks.append(kappa(ref[idx], cand[idx]))
        ks = np.array(ks)
        out[name] = [float(np.nanpercentile(ks, 2.5)), float(np.nanpercentile(ks, 97.5))]
    return out


def run(region: str):
    A, pmeta = aggregate.load(region)
    Z, smeta = science.load(region)
    units = load_units(region)
    U = len(districts(units))
    y0, y1 = pmeta["years"]
    Y = y1 - y0 + 1
    years = y0 + np.arange(Y)
    r = smeta["r"]
    V, rho, ns = science.rate_arrays(A)
    per_mu, per_sg = Z["per_mu"], Z["per_sg"]
    dflt = DEFAULT_BASELINE
    base = {q: Z[f"base_{dflt}_{q}"] for q in ("q10", "q50", "q90", "max", "n")}
    rbase = {q: Z[f"rbase_{dflt}_{q}"] for q in ("q10", "q50", "q90", "max", "n")}
    ia, ij1, it, in_ = SIDX["A"], SIDX["J1"], SIDX["T"], SIDX["N"]
    alphaA = smeta["alpha_A"]
    warnings_ = []

    def vcode(mu, sg, b=base):
        return verdict(mu, sg, b["q10"], b["q50"], b["q90"], b["max"], b["n"])[0]

    # ---------- H1: continuity of NOAA-20-only verdicts vs Aqua-only verdicts on held-out years
    ho_years = [k for k in range(Y) if years[k] >= HELD_OUT_FROM and V[ij1, :, k].any() and V[ia, :, k].any()]
    h1 = {"held_out_years": [int(years[k]) for k in ho_years]}
    cand_results = {}
    if ho_years and V[ij1].any() and np.isfinite(per_mu[ij1]).any():
        sel = np.zeros((U + 1, Y, 46), bool)
        sel[:U, ho_years, :] = True
        sel &= V[ia] & V[ij1]
        ref_code = vcode(per_mu[ia], per_sg[ia])
        judged_ref = sel & judged(ref_code)
        uu, yy, pp = np.nonzero(judged_ref)
        ref = _cls(ref_code[judged_ref])

        # candidate predictions (all return class arrays over cells + judged mask)
        cands = {}
        # ours: NOAA-20 through the bridges
        c_code = vcode(per_mu[ij1], per_sg[ij1])
        cands["afterglow_bridges"] = c_code
        # (a) raw NOAA-20 counts vs raw MODIS-era baseline
        d_raw = np.where(V[ij1], A["D"][ij1], np.nan)
        a_code = raw_class(d_raw, rbase["q10"], rbase["q90"], rbase["n"])
        cands["a_raw_counts"] = a_code
        # (b) one constant ratio fitted on 2018-2022 overlap
        trn = np.zeros_like(V[ia])
        trn[:U, [k for k in range(Y) if 2018 <= years[k] <= 2022], :] = True
        trn &= V[ia] & V[ij1]
        if trn.any():
            ratio = A["D"][ia][trn].sum() / max(1e-9, (rho[ij1][trn] * A["clear"][ia][trn] / 1000.0).sum())
            mu_b = np.log(ratio * rho[ij1])
            sg_b = np.sqrt(1.0 / (np.where(V[ij1], A["D"][ij1], np.nan) + 0.5) + alphaA)
            cands["b_constant_ratio"] = vcode(mu_b, sg_b)
            # (c) per-month ratio of raw counts, no coverage normalisation
            months = (np.arange(46) * 8 // 30.5).astype(int).clip(0, 11)
            rate_c = np.full_like(rho[ij1], np.nan)
            for m in range(12):
                cols = months == m
                tm = trn.copy()
                tm[:, :, ~cols] = False
                if tm.sum() < 30:
                    continue
                rm = A["D"][ia][tm].sum() / max(1.0, A["D"][ij1][tm].sum())
                dc = np.where(V[ij1], A["D"][ij1], np.nan)[:, :, cols] * rm
                rate_c[:, :, cols] = dc / (A["land"][:, :, cols] / 1000.0) + RATE_FLOOR
            sg_c = np.sqrt(1.0 / (rate_c * A["land"] / 1000.0) + alphaA)
            cands["c_month_ratio_no_coverage"] = vcode(np.log(rate_c), sg_c)
        # (d) NOAA-20-only baseline from its own 2018-2022 record (no bridge, min baseline n relaxed to 10)
        rho_j1 = np.where(V[ij1], rho[ij1], np.nan)
        bj = science.baseline_stats(rho_j1, y0, (2018, 2022), True)
        bj_n = np.where(bj["n"] >= 10, 100, bj["n"])
        sg_d = np.sqrt(1.0 / (np.where(V[ij1], A["D"][ij1], np.nan) + 0.5) + alphaA)
        cands["d_noaa20_only_baseline"] = verdict(np.log(rho_j1), sg_d, bj["q10"], bj["q50"], bj["q90"], bj["max"], bj_n)[0]
        for name, code in cands.items():
            both = judged_ref & judged(code)
            res = {"judged_share": float(both.sum() / max(1, judged_ref.sum()))}
            if both.sum() >= 20:
                u2, y2, _ = np.nonzero(both)
                res.update(_kappa_ci(_cls(ref_code[both]), _cls(code[both]), u2, y2))
            else:
                res.update({"kappa": None, "n": int(both.sum()), "ci_year": None, "ci_unit": None})
            cand_results[name] = res
        h1.update(n_reference_cells=int(judged_ref.sum()), reference="Aqua-only verdict vs combined-fleet baseline",
                  candidates=cand_results)
        # same comparison on the national series: district-period counts are mostly 0-3, so district kappa is mostly noise
        sel_c = np.zeros_like(sel)
        sel_c[U, ho_years, :] = True
        sel_c &= V[ia] & V[ij1]
        ref_c = sel_c & judged(ref_code)
        country = {"n_reference_cells": int(ref_c.sum())}
        both = sel_c & np.isfinite(per_mu[ij1])
        if both.sum() >= 20:
            country["corr_log_rate"] = float(np.corrcoef(per_mu[ij1][both], np.log(rho[ia][both]))[0, 1])
            country["mean_log_bias"] = float((per_mu[ij1][both] - np.log(rho[ia][both])).mean())
        for name, code in cands.items():
            bc = ref_c & judged(code)
            if bc.sum() >= 20:
                _, y2, _ = np.nonzero(bc)
                country[name] = _kappa_ci(_cls(ref_code[bc]), _cls(code[bc]), np.zeros_like(y2), y2)
        h1["country_level"] = country
        # interval calibration. z uses the bridged sigma plus Aqua's count noise only (the chain sigma already holds the
        # sensor-to-sensor overdispersion). 'informative' = cells where the bridge predicts >= 3 Aqua detections.
        both = sel & np.isfinite(per_mu[ij1]) & np.isfinite(per_mu[ia])
        z = (per_mu[ij1][both] - np.log(rho[ia][both])) / np.sqrt(per_sg[ij1][both] ** 2 + 1.0 / (A["D"][ia][both] + 0.5))
        exp_a = np.exp(per_mu[ij1][both]) * A["clear"][ia][both] / 1000.0
        calib = {"noaa20_via_bridges": {"n": int(both.sum()), "coverage80": float(np.mean(np.abs(z) <= Z80)),
                                        "coverage95": float(np.mean(np.abs(z) <= Z95))},
                 "noaa20_via_bridges_informative": {"n": int((exp_a >= 3).sum()),
                                                    "coverage80": float(np.mean(np.abs(z[exp_a >= 3]) <= Z80)) if (exp_a >= 3).any() else None}}
        no_a = np.array([s != "A" for s in ["T", "A", "N", "J1", "J2"]])
        mu_nc, sg_nc, n_nc = combine(per_mu, per_sg, no_a, r)
        both2 = sel & np.isfinite(mu_nc)
        z2 = (mu_nc[both2] - np.log(rho[ia][both2])) / np.sqrt(sg_nc[both2] ** 2 + per_sg[ia][both2] ** 2)
        calib["fleet_without_aqua"] = {"n": int(both2.sum()), "coverage80": float(np.mean(np.abs(z2) <= Z80)),
                                       "coverage95": float(np.mean(np.abs(z2) <= Z95))}
        h1["calibration"] = calib
        if len(ho_years) < 4:
            warnings_.append(f"Only {len(ho_years)} held-out year(s) with data ({h1['held_out_years']}); year-block "
                             "confidence intervals are unreliable. The unit-block interval is the more informative one.")
    else:
        warnings_.append("H1 could not be evaluated: no held-out years with both Aqua and NOAA-20 data.")

    # ---------- step change when VIIRS (S-NPP) joins: 2012-2018, cells where T, A, N are all valid
    stp = {}
    ys = [k for k in range(Y) if 2012 <= years[k] <= 2018]
    sel = np.zeros((U + 1, Y, 46), bool)
    sel[:U, ys, :] = True
    sel &= V[it] & V[ia] & V[in_]
    if sel.sum() > 50:
        en3 = np.array([True, True, True, False, False])
        en2 = np.array([True, True, False, False, False])
        m3, _, _ = combine(per_mu, per_sg, en3, r)
        m2, _, _ = combine(per_mu, per_sg, en2, r)
        d_ours = (m3 - m2)[sel]
        dsum3 = (np.where(V[it], A["D"][it], 0) + np.where(V[ia], A["D"][ia], 0) + np.where(V[in_], A["D"][in_], 0))[sel]
        dsum2 = (np.where(V[it], A["D"][it], 0) + np.where(V[ia], A["D"][ia], 0))[sel]
        d_raw = np.log((dsum3 + 0.5) / (dsum2 + 0.5))
        uu = np.nonzero(sel)[0]
        rng = np.random.default_rng(11)

        def ci(d):
            keys = np.unique(uu)
            by = {k: d[uu == k] for k in keys}
            ms = [np.concatenate([by[k] for k in rng.choice(keys, len(keys))]).mean() for _ in range(500)]
            return [float(np.percentile(ms, 2.5)), float(np.percentile(ms, 97.5))]

        stp = {"n": int(sel.sum()), "afterglow": {"mean_log_ratio": float(d_ours.mean()), "ci95": ci(d_ours)},
               "raw_counts": {"mean_log_ratio": float(d_raw.mean()), "ci95": ci(d_raw)}}
    # ---------- cloud artifact: Spearman rho between anomaly and coverage in low-activity periods
    low = np.isfinite(Z["mu_c"]) & (base["q50"] < np.nanmedian(base["q50"][:U]))
    low[U] = False
    covm = np.nanmean(np.where(A["active"], A["cov"], np.nan), axis=0)
    zo = (Z["mu_c"] - np.log(np.maximum(base["q50"], 1e-6))) / Z["sg_c"]
    cl = {}
    sel = low & np.isfinite(covm) & np.isfinite(zo)
    if sel.sum() > 50:
        cl["afterglow"] = {"n": int(sel.sum()), "spearman_rho": float(spearmanr(zo[sel], covm[sel])[0])}
    naive = np.nansum(np.where(A["active"], A["D"], np.nan), axis=0)
    zr = np.log(naive + 0.5) - np.log(np.maximum(rbase["q50"], 0.5))
    sel2 = np.isfinite(zr) & np.isfinite(covm) & (np.arange(U + 1)[:, None, None] < U) & (covm > 0.02) & (base["q50"] < np.nanmedian(base["q50"][:U]))
    if sel2.sum() > 50:
        cl["raw_counts"] = {"n": int(sel2.sum()), "spearman_rho": float(spearmanr(zr[sel2], covm[sel2])[0])}
    # ---------- Terra control (Terra bridge trained 2003-2018; test on 2019-2022)
    tc = {}
    ys = [k for k in range(Y) if 2019 <= years[k] <= 2022]
    sel = np.zeros((U + 1, Y, 46), bool)
    sel[:U, ys, :] = True
    sel &= V[it] & V[ia]
    if sel.sum() > 50:
        rc, tcode = vcode(per_mu[ia], per_sg[ia]), vcode(per_mu[it], per_sg[it])
        both = sel & judged(rc) & judged(tcode)
        z = (per_mu[it][sel] - np.log(rho[ia][sel])) / np.sqrt(per_sg[it][sel] ** 2 + per_sg[ia][sel] ** 2)
        u2, y2, _ = np.nonzero(both)
        tc = {"n": int(both.sum()), "kappa": kappa(_cls(rc[both]), _cls(tcode[both])) if both.sum() > 20 else None,
              "coverage80": float(np.mean(np.abs(z) <= Z80))}
    # ---------- stress test cross-check (exact front-end computation): T, A and N switched off
    ho = [k for k in range(Y) if years[k] >= HELD_OUT_FROM]
    full_code = Z["code"]
    en_off = np.array([False, False, False, True, True])
    mu_s, sg_s, _ = combine(per_mu, per_sg, en_off, r)
    st_code = vcode(mu_s, sg_s)
    raw_full = Z["raw_total"]
    d_on = np.where(V, A["D"], np.nan)
    raw_off = np.where(np.isfinite(d_on[SIDX["J1"]]) | np.isfinite(d_on[SIDX["J2"]]),
                       np.nansum(d_on[3:], axis=0), np.nan)
    rc_full = raw_class(raw_full, rbase["q10"], rbase["q90"], rbase["n"])
    rc_off = raw_class(raw_off, rbase["q10"], rbase["q90"], rbase["n"])
    kept = {"units": {}, "region": {}}
    msk = np.zeros((U + 1, Y, 46), bool)
    msk[:, ho, :] = True
    jm = msk & judged(full_code) & V[ij1]
    rj = msk & judged(rc_full) & V[ij1]

    def frac(m, full, off):
        n = int(m.sum())
        if n == 0:
            return None
        return dict(n=n, kept=float((_cls(full[m]) == _cls(off[m])).mean()))

    for u in units:
        i = u["idx"]
        a, rr = frac(jm[i:i + 1], full_code[i:i + 1], st_code[i:i + 1]), frac(rj[i:i + 1], rc_full[i:i + 1], rc_off[i:i + 1])
        kept["units"][u["id"]] = dict(adj=None if a is None else round(a["kept"], 4), raw=None if rr is None else round(rr["kept"], 4),
                                     n=0 if a is None else a["n"])
    a, rr = frac(jm[:U], full_code[:U], st_code[:U]), frac(rj[:U], rc_full[:U], rc_off[:U])
    kept["region"] = dict(adj=None if a is None else round(a["kept"], 4), raw=None if rr is None else round(rr["kept"], 4),
                          n=0 if a is None else a["n"], sensors_off=["T", "A", "N"], years=[int(years[k]) for k in ho
                                                                                          if jm[:U, k].any()])
    if kept["region"]["n"] == 0:
        warnings_.append("Stress-test cross-check has no held-out judged periods.")
    # ---------- write
    try:
        import subprocess
        commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=state_dir(region)).stdout.strip() or "uncommitted"
    except Exception:
        commit = "uncommitted"
    out = dict(schema="afterglow/validation@1", generated_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
               commit=commit, region=region, years=[y0, y1], held_out_from=HELD_OUT_FROM, bootstrap_B=smeta["bootstrap_B"],
               combine_r=r, coverage_source=pmeta["cov_src"], h1=h1, step_change=stp, cloud_artifact=cl,
               terra_control=tc, verdicts_kept=kept, warnings=warnings_)
    (state_dir(region) / "validation.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    print("  H1 candidates:", {k: (None if v["kappa"] is None else round(v["kappa"], 3)) for k, v in cand_results.items()})
    print("  H1 country-level:", h1.get("country_level"))
    print("  calibration:", h1.get("calibration"))
    print("  step change:", stp)
    print("  cloud artifact:", cl)
    print("  terra control:", tc)
    print("  verdicts kept (region):", kept["region"])
    for w in warnings_:
        print("  WARNING:", w)
