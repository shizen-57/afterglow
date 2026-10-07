"""S7: harmonization. Implements backend.md section 6 with one documented deviation:

  The NB2 regression is solved by a small NumPy IRLS routine with a weak Gaussian prior (slope ~ N(1, 1)) so that
  sparse counts (Terra) give stable slopes. Bridges are fitted on TOTAL counts with a night-share covariate (and seasonal terms), not as separate day and night
  fits, because chained bridges (J1 -> N -> A) only carry totals. The night share of the originating sensor is held
  fixed along a chain.

Rates use an additive floor (D/E + RATE_FLOOR, E = clear km2-days/1000) instead of a +0.5 pseudo-count: a pseudo-count
inflates the rate of zero-count periods whenever clouds shrink E, which is exactly the artifact this project must avoid.

Unit of the harmonized index H: detections per 1,000 clear-view km2-days on the Aqua-MODIS scale ("Aqua-eq.").
"""
from __future__ import annotations

import json
import warnings

import numpy as np

from . import aggregate, landcover
from .boundaries import districts, load_units, state_dir
from .config import (BASELINES, BOOTSTRAP_B, BRIDGES, CHAIN, DEFAULT_BASELINE, F_CALIB, F_COV_PROXY, F_HELD_OUT,
                     F_PARTIAL, HELD_OUT_FROM, MIN_BASELINE_N, MIN_COV, MIN_LAND_KM2D, P, RATE_FLOOR, REFERENCE, S, SENSORS, SIDX,
                     Z80, days_in_period)
from .core import combine, raw_class, verdict

warnings.filterwarnings("ignore")
STRATA = ["forest", "cropland", "other"]
MIN_ROWS = 150


# ------------------------------------------------------------------ rates
def valid_mask(A) -> np.ndarray:
    return A["active"] & (A["cov"] >= MIN_COV) & (A["land"][None] >= MIN_LAND_KM2D) & np.isfinite(A["D"])


def rate_arrays(A):
    V = valid_mask(A)
    clear = np.where(V, A["clear"], np.nan)
    rho = np.where(V, A["D"], np.nan) / (clear / 1000.0) + RATE_FLOOR
    ns = np.where(A["D"] > 0, A["Dn"] / np.where(A["D"] > 0, A["D"], 1), 0.5)
    return V, rho, ns


def _season(Y):
    p = np.arange(1, P + 1)
    return np.tile(np.sin(2 * np.pi * p / P), (Y, 1)), np.tile(np.cos(2 * np.pi * p / P), (Y, 1))


# ------------------------------------------------------------------ bridges
def _features(x, ns, sn, cs):
    return np.column_stack([np.ones_like(x), x, ns, sn, cs])


PRIOR_MEAN = np.array([0.0, 1.0, 0.0, 0.0, 0.0])
PRIOR_PREC = np.array([0.0, 1.0, 0.04, 0.04, 0.04])  # weak Gaussian prior: slope ~ N(1, 1), others ~ N(0, 5^2)


def _irls(y, X, off, alpha, beta=None, iters=40):
    """Log-link NB2 (alpha fixed; alpha=0 is Poisson) by IRLS with a weak Gaussian prior on the coefficients."""
    if beta is None:
        beta = np.zeros(X.shape[1])
        beta[0] = np.log(max(y.mean(), 1e-6) / max(np.exp(off).mean(), 1e-9))
    for _ in range(iters):
        eta = np.clip(off + X @ beta, -25, 25)
        mu = np.exp(eta)
        w = mu / (1.0 + alpha * mu)
        z = (eta - off) + (y - mu) / mu
        XtW = X.T * w
        new = np.linalg.solve(XtW @ X + np.diag(PRIOR_PREC), XtW @ z + PRIOR_PREC * PRIOR_MEAN)
        done = np.max(np.abs(new - beta)) < 1e-7
        beta = new
        if done:
            break
    return beta


def fit_nb(y, X, off):
    """Poisson fit -> moment estimate of alpha -> NB2 fit with fixed alpha (twice). Returns (params, alpha)."""
    b = _irls(y, X, off, 0.0)
    alpha = 0.5
    for _ in range(2):
        mu = np.exp(np.clip(off + X @ b, -25, 25))
        alpha = float(np.clip(((y - mu) ** 2 - y).sum() / (mu**2).sum(), 1e-3, 50.0))
        b = _irls(y, X, off, alpha, b)
    if not np.all(np.isfinite(b)):
        raise FloatingPointError("non-finite NB parameters")
    return b, alpha


def ratio_params(y, rho, clear_to):
    """Level-3 fallback: D_to ~ ratio * rho_s * exposure_to  (beta1 = 1, no other terms)."""
    ratio = y.sum() / max(1e-9, (rho * clear_to / 1000.0).sum())
    return np.array([np.log(max(ratio, 1e-6)), 1.0, 0.0, 0.0, 0.0]), 0.1


def fit_bridge(frm: str, to: str, A, rho, V, strata_u, y0: int, tr: tuple[int, int], B: int, rng):
    """Fit one bridge frm -> to on training years. Returns dict model_key -> {beta[B,5], alpha[B], level, n}."""
    Y = A["D"].shape[2]
    sn, cs = _season(Y)
    i, j = SIDX[frm], SIDX[to]
    U = A["D"].shape[1] - 1
    ok = V[i, :U] & V[j, :U]
    yrs = np.arange(tr[0], tr[1] + 1) - y0
    yrs = yrs[(yrs >= 0) & (yrs < Y)]
    mask = np.zeros_like(ok)
    mask[:, yrs, :] = True
    ok &= mask
    u, y, p = np.nonzero(ok)
    if len(u) < MIN_ROWS:
        return None
    x = np.log(rho[i, u, y, p])
    ns = np.where(A["D"][i, u, y, p] > 0, A["Dn"][i, u, y, p] / np.maximum(A["D"][i, u, y, p], 1), 0.5)
    X = _features(x, ns, sn[y, p], cs[y, p])
    yy = A["D"][j, u, y, p].astype(float)
    off = np.log(A["clear"][j, u, y, p] / 1000.0)
    rho_s = rho[i, u, y, p]
    clr_to = A["clear"][j, u, y, p]
    groups = {"pool": np.ones(len(u), bool)}
    for k, name in enumerate(STRATA):
        groups[name] = strata_u[u] == k
    out = {}
    for key, g in groups.items():
        n = int(g.sum())
        level = 0 if key != "pool" else 1
        if key != "pool" and n < MIN_ROWS:
            continue  # falls back to pool at prediction time
        gi = np.flatnonzero(g)
        by_year = {yr: gi[y[gi] == yr] for yr in np.unique(y[gi])}
        try:
            beta0, alpha0 = fit_nb(yy[gi], X[gi], off[gi])
        except Exception:
            beta0, alpha0 = ratio_params(yy[gi], rho_s[gi], clr_to[gi])
            level = 3
        betas, alphas = [beta0], [alpha0]
        years = np.array(list(by_year))
        for _ in range(B - 1):
            pick = rng.choice(years, size=len(years), replace=True)
            idx = np.concatenate([by_year[k] for k in pick])
            try:
                b, a = fit_nb(yy[idx], X[idx], off[idx]) if level != 3 else ratio_params(yy[idx], rho_s[idx], clr_to[idx])
            except Exception:
                b, a = ratio_params(yy[idx], rho_s[idx], clr_to[idx])
            betas.append(b)
            alphas.append(a)
        out[key] = dict(beta=np.array(betas), alpha=np.array(alphas), level=level, n=n)
    return out


def predict_sensor(s: str, A, rho, V, ns, models, strata_u, rng, B):
    """Chain a sensor's rate to the Aqua scale with bootstrap draws. Returns mu, sigma arrays [U1,Y,P] (NaN if invalid)."""
    shape = V[SIDX[s]].shape
    mu_o, sg_o = np.full(shape, np.nan), np.full(shape, np.nan)
    chain = CHAIN[s]
    links = list(zip(chain[:-1], chain[1:]))
    if any((f, t) not in models or models[(f, t)] is None for f, t in links):
        return mu_o, sg_o
    idx = np.flatnonzero(V[SIDX[s]].ravel())
    if len(idx) == 0:
        return mu_o, sg_o
    u, y, p = np.unravel_index(idx, shape)
    Y = shape[1]
    sn, cs = _season(Y)
    sin_, cos_ = sn[y, p], cs[y, p]
    clear_s = A["clear"][SIDX[s]].ravel()[idx] / 1000.0
    ns_s = ns[SIDX[s]].ravel()[idx]
    x = np.tile(np.log(rho[SIDX[s]].ravel()[idx]), (B, 1))
    su = strata_u[u]
    for f, t in links:
        mod = models[(f, t)]
        rate = np.empty_like(x)
        alpha_cell = np.empty_like(x)
        for k in (-1, 0, 1, 2):
            sel = su == k
            if not sel.any():
                continue
            key = "pool" if k == -1 or STRATA[k] not in mod else STRATA[k]
            m = mod[key]
            b = m["beta"][:B] if len(m["beta"]) >= B else np.resize(m["beta"], (B, 5))
            al = m["alpha"][:B] if len(m["alpha"]) >= B else np.resize(m["alpha"], B)
            eta = b[:, 0:1] + b[:, 1:2] * x[:, sel] + b[:, 2:3] * ns_s[sel] + b[:, 3:4] * sin_[sel] + b[:, 4:5] * cos_[sel]
            rate[:, sel] = np.exp(np.clip(eta, -20, 12))
            alpha_cell[:, sel] = al[:, None]
        mean = rate * clear_s
        n_par = 1.0 / alpha_cell
        cnt = rng.negative_binomial(n_par, n_par / (n_par + mean))
        x = np.log(cnt / clear_s + RATE_FLOOR)
    mu_o.ravel()[idx] = x.mean(0)
    sg_o.ravel()[idx] = x.std(0, ddof=1)
    return mu_o, sg_o


# ------------------------------------------------------------------ baselines
def _neighbour_index(Y, P_):
    """idx[y', p, k] flat timeline index of (y', p) shifted by k in {-1,0,1}; -1 if outside the record."""
    base = np.arange(Y)[:, None] * P_ + np.arange(P_)[None, :]
    out = np.stack([base - 1, base, base + 1], -1)
    out[(out < 0) | (out >= Y * P_)] = -1
    return out


def baseline_stats(H, y0: int, window: tuple[int, int], per_target: bool = True):
    """Quantiles of H over the baseline window (+-1 period), excluding the target year itself.

    H: [U1, Y, P] with NaN where not judged. Returns dict of [U1, Y, P] arrays (per_target) or [U1, P] (all window years).
    """
    U1, Y, P_ = H.shape
    nb = _neighbour_index(Y, P_)
    Hf = np.concatenate([H.reshape(U1, Y * P_), np.full((U1, 1), np.nan)], axis=1)  # index -1 -> NaN column
    win = [k for k in range(Y) if window[0] <= y0 + k <= window[1]]

    def stats(excl):
        ys = [k for k in win if k != excl]
        if not ys:
            return [np.full((U1, P_), np.nan)] * 4 + [np.zeros((U1, P_))]
        g = Hf[:, nb[ys].reshape(len(ys), P_, 3)]  # [U1, ny, P, 3]
        g = np.moveaxis(g, 2, 1).reshape(U1, P_, -1) if False else g.transpose(0, 2, 1, 3).reshape(U1, P_, -1)
        n = np.isfinite(g).sum(-1)
        with np.errstate(all="ignore"):
            q = np.nanpercentile(g, [10, 50, 90], axis=-1)
            mx = np.nanmax(g, axis=-1)
        return q[0], q[1], q[2], mx, n

    keys = ["q10", "q50", "q90", "max", "n"]
    if not per_target:
        return dict(zip(keys, stats(-1)))
    out = {k: np.full((U1, Y, P_), np.nan if k != "n" else 0.0, dtype=np.float64) for k in keys}
    for k in range(Y):
        for name, v in zip(keys, stats(k)):
            out[name][:, k, :] = v
    return out


def calibrate_sigma_scale(s: str, per_mu, per_sg, V, rho, y0: int, years: tuple[int, int], sig_a):
    """Training-years-only interval calibration for sensor s against Aqua's own log-rate.

    Finds f so that |mu_s - log(rho_A)| <= Z80 * f * sqrt(sig_s^2 + sig_A^2) holds for exactly 80% of overlapping cells, then
    sets sig_s'^2 = max(f^2 (sig_s^2 + sig_A^2) - sig_A^2, (0.2 sig_s)^2). Held-out years are never used.
    """
    i, ia = SIDX[s], SIDX[REFERENCE]
    Y = V.shape[2]
    yrs = [k for k in range(Y) if years[0] <= y0 + k <= years[1]]
    sel = np.zeros_like(V[i])
    sel[:, yrs, :] = True
    sel &= V[i] & V[ia] & np.isfinite(per_mu[i])
    sel[-1] = False  # country unit excluded from calibration
    if sel.sum() < 200:
        return 1.0, int(sel.sum())
    z = np.abs(per_mu[i][sel] - np.log(rho[ia][sel])) / np.sqrt(per_sg[i][sel] ** 2 + sig_a[sel] ** 2)
    f = float(np.quantile(z, 0.80) / Z80)
    new = np.sqrt(np.maximum(f**2 * (per_sg[i] ** 2 + sig_a**2) - sig_a**2, (0.2 * per_sg[i]) ** 2))
    per_sg[i] = np.where(np.isfinite(per_sg[i]), new, np.nan)
    return f, int(sel.sum())


# ------------------------------------------------------------------ calibration of r
def calibrate_r(per_mu, per_sg, V, A, y0, train=(2013, 2018)):
    """Smallest r in {0,...,0.9} such that the {T,N} combination predicts Aqua's own log-rate with >=80% coverage."""
    i_t, i_n, i_a = SIDX["T"], SIDX["N"], SIDX["A"]
    Y = V.shape[2]
    yrs = [k for k in range(Y) if train[0] <= y0 + k <= train[1]]
    sel = np.zeros_like(V[i_a])
    sel[:, yrs, :] = True
    sel &= V[i_a] & np.isfinite(per_mu[i_t]) & np.isfinite(per_mu[i_n])
    if sel.sum() < 100:
        return 0.3, dict(note="too few overlap cells; default r=0.3", n=int(sel.sum()))
    mu_a, sg_a = per_mu[i_a][sel], per_sg[i_a][sel]
    best, rows = None, []
    for r in np.round(np.arange(0, 1.0, 0.1), 1):
        mu_c, sg_c, _ = combine(np.stack([per_mu[i_t][sel], per_mu[i_n][sel]]), np.stack([per_sg[i_t][sel], per_sg[i_n][sel]]),
                                np.array([True, True]), r)
        z = np.abs(mu_c - mu_a) / np.sqrt(sg_c**2 + sg_a**2)
        cov = float(np.mean(z <= Z80))
        rows.append((float(r), cov))
        if best is None and cov >= 0.80:
            best = float(r)
    return (best if best is not None else 0.9), dict(coverage_by_r=rows, n=int(sel.sum()))


# ------------------------------------------------------------------ main
def run(region: str):
    A, meta = aggregate.load(region)
    y0, y1 = meta["years"]
    units = load_units(region)
    U = len(districts(units))
    Y = y1 - y0 + 1
    lc = landcover.load(region)
    strata_u = np.full(U + 1, -1, np.int8)
    for u in districts(units):
        st = lc["units"].get(u["id"], {}).get("stratum", "other")
        strata_u[u["idx"]] = STRATA.index(st) if lc.get("available") else -1
    rng = np.random.default_rng(20261114)
    V, rho, ns = rate_arrays(A)
    B = BOOTSTRAP_B
    print(f"  bootstrap draws B={B}; strata counts: { {n: int((strata_u == k).sum()) for k, n in enumerate(STRATA)} }")

    # --- bridges
    models, bmeta = {}, []
    for frm, to, t0, t1 in BRIDGES:
        if not V[SIDX[frm]].any() or not V[SIDX[to]].any():
            print(f"  bridge {frm}->{to}: skipped (no valid data for a sensor)")
            continue
        m = fit_bridge(frm, to, A, rho, V, strata_u, y0, (t0, t1), B, rng)
        models[(frm, to)] = m
        if m is None:
            print(f"  bridge {frm}->{to}: too few overlapping rows, skipped")
            continue
        lvl = max(v["level"] for v in m.values())
        print(f"  bridge {frm}->{to} train {t0}-{t1}: " + ", ".join(
            f"{k}: n={v['n']} b1={np.median(v['beta'][:, 1]):.2f} a={np.median(v['alpha']):.2f} L{v['level']}" for k, v in m.items()))
        bmeta.append(dict(**{"from": frm, "to": to}, train=[t0, t1], fallback_level=int(lvl),
                          models={k: dict(n=v["n"], level=v["level"], beta_median=np.median(v["beta"], 0).round(4).tolist(),
                                          alpha_median=float(np.median(v["alpha"]))) for k, v in m.items()}))
    # --- per-sensor estimates on the Aqua scale
    per_mu = np.full((S, U + 1, Y, P), np.nan)
    per_sg = np.full((S, U + 1, Y, P), np.nan)
    na = models.get(("N", "A"))
    alpha_A = float(np.median(na["pool"]["alpha"])) if na else 0.3
    ia = SIDX[REFERENCE]
    DA = np.where(V[ia], A["D"][ia], np.nan)
    per_mu[ia] = np.log(rho[ia])
    per_sg[ia] = np.sqrt(1.0 / (DA + 0.5) + alpha_A)
    for s in SENSORS:
        if s == REFERENCE:
            continue
        mu, sg = predict_sensor(s, A, rho, V, ns, models, strata_u, rng, B)
        per_mu[SIDX[s]], per_sg[SIDX[s]] = mu, sg
        print(f"  {s}: valid cells={int(V[SIDX[s]].sum()):,}  estimated={int(np.isfinite(mu).sum()):,}")
    # --- interval calibration on training years (before the combination); Aqua's own sigma is the reference noise
    sig_a = np.where(np.isfinite(per_sg[ia]), per_sg[ia], 0.0)
    # DISABLED: calibrate_sigma_scale is dominated by zero-count cells (collapses sigma to its floor) and needs a
    # count-aware version before use. Kept for reference; intervals are therefore the uncalibrated bootstrap ones.
    cal_years = {}
    scale_info = {}
    for s_, yr in cal_years.items():
        if np.isfinite(per_mu[SIDX[s_]]).any():
            f_, n_ = calibrate_sigma_scale(s_, per_mu, per_sg, V, rho, y0, yr, sig_a)
            scale_info[s_] = dict(factor=round(f_, 4), n=n_, years=list(yr))
            print(f"  sigma calibration {s_}: factor={f_:.3f} (n={n_:,}, years {yr[0]}-{yr[1]})")
    # --- combination (full fleet)
    r, rinfo = calibrate_r(per_mu, per_sg, V, A, y0)
    print(f"  inter-sensor error correlation r={r}")
    enabled = np.ones(S, bool)
    mu_c, sg_c, n_used = combine(per_mu, per_sg, enabled, r)
    H = np.exp(mu_c)
    # --- baselines + verdicts (default baseline + alternatives)
    base = {k: baseline_stats(H, y0, w, True) for k, w in BASELINES.items()}
    base_all = {k: baseline_stats(H, y0, w, False) for k, w in BASELINES.items()}
    b = base[DEFAULT_BASELINE]
    code, p_hi, p_lo = verdict(mu_c, sg_c, b["q10"], b["q50"], b["q90"], b["max"], b["n"])
    # --- raw (naive) totals + baseline
    Dn_ = np.where(V, A["D"], np.nan)
    raw_total = np.where(np.isfinite(Dn_).any(0), np.nansum(Dn_, 0), np.nan)
    rb = {k: baseline_stats(raw_total, y0, w, True) for k, w in BASELINES.items()}
    rb_all = {k: baseline_stats(raw_total, y0, w, False) for k, w in BASELINES.items()}
    rcode = raw_class(raw_total, rb[DEFAULT_BASELINE]["q10"], rb[DEFAULT_BASELINE]["q90"], rb[DEFAULT_BASELINE]["n"])
    # --- annual totals, ranks, peak windows
    land = A["land"]
    judged = (code >= 1) & (code <= 6)
    contrib = np.where(judged, H * land / 1000.0, 0.0)
    total = np.where(judged.any(2), contrib.sum(2), np.nan)
    sd = np.sqrt(((contrib * np.where(judged, sg_c, 0.0)) ** 2).sum(2))
    lo80, hi80 = np.maximum(0, total - Z80 * sd), total + Z80 * sd
    complete = np.where(land.sum(2) > 0, (land * judged).sum(2) / np.maximum(land.sum(2), 1e-9), 0.0)
    rank = np.full(total.shape, np.nan)
    for u in range(U + 1):
        okc = complete[u] >= 0.8
        t = np.where(okc, total[u], -np.inf)
        order = (-t).argsort(kind="stable")
        rk = np.empty(Y)
        rk[order] = np.arange(1, Y + 1)
        rank[u] = np.where(okc, rk, np.nan)
    peak = np.full((U + 1, 2), -1, np.int16)
    for u in range(U + 1):
        med = base_all[DEFAULT_BASELINE]["q50"][u]
        if np.isfinite(med).sum() < 20:
            continue
        thr = np.nanpercentile(med, 75)
        run_start, best = None, (0, -1, -1)
        for p in range(P + 1):
            on = p < P and np.isfinite(med[p]) and med[p] > thr
            if on and run_start is None:
                run_start = p
            if not on and run_start is not None:
                if p - run_start > best[0]:
                    best = (p - run_start, run_start + 1, p)
                run_start = None
        if best[1] > 0:
            peak[u] = (best[1], best[2])
    # --- flags
    flags = np.zeros((U + 1, Y, P), np.int16)
    years = y0 + np.arange(Y)
    flags |= np.where((years >= HELD_OUT_FROM)[None, :, None], F_HELD_OUT, F_CALIB).astype(np.int16)
    partial = (A["n_days"] < np.array([[days_in_period(y0 + k, p + 1) for p in range(P)] for k in range(Y)])[None, None]) & A["active"]
    flags |= np.where(partial.any(0), F_PARTIAL, 0).astype(np.int16)
    proxy = [SIDX[s] for s in SENSORS if meta["cov_src"].get(s) == "proxy_A"]
    if proxy:
        used_proxy = np.isfinite(per_mu[proxy]).any(0)
        flags |= np.where(used_proxy, F_COV_PROXY, 0).astype(np.int16)

    sd_ = state_dir(region)
    np.savez_compressed(sd_ / "science.npz", per_mu=per_mu, per_sg=per_sg, mu_c=mu_c, sg_c=sg_c, n_used=n_used,
                        code=code, p_hi=p_hi, p_lo=p_lo, flags=flags, raw_total=raw_total, rcode=rcode,
                        total=total, lo80=lo80, hi80=hi80, rank=rank, complete=complete, peak=peak, V=V,
                        **{f"base_{k}_{q}": base[k][q] for k in BASELINES for q in base[k]},
                        **{f"baseall_{k}_{q}": base_all[k][q] for k in BASELINES for q in base_all[k]},
                        **{f"rbase_{k}_{q}": rb[k][q] for k in BASELINES for q in rb[k]},
                        **{f"rbaseall_{k}_{q}": rb_all[k][q] for k in BASELINES for q in rb_all[k]})
    # keep bridge draws for validation (small)
    np.savez_compressed(sd_ / "bridges.npz", **{f"{f}_{t}_{k}_{q}": v[q] for (f, t), m in models.items() if m
                                               for k, v in m.items() for q in ("beta", "alpha")})
    (sd_ / "science_meta.json").write_text(json.dumps(dict(
        years=[y0, y1], r=r, r_info=rinfo, sigma_scale=scale_info, alpha_A=alpha_A, bootstrap_B=B, bridges=bmeta,
        strata_source="ESA WorldCover 2021" if lc.get("available") else "unavailable (pooled bridges)",
        strata_counts={n: int((strata_u == k).sum()) for k, n in enumerate(STRATA)},
        cov_src=meta["cov_src"], windows=meta["windows"])), encoding="utf-8")
    c = np.bincount(code[:U][judged[:U] | (code[:U] == 0)].ravel() + 0, minlength=9)
    print("  verdict counts over districts (code 0..8):", c.tolist())


def load(region: str):
    sd = state_dir(region)
    z = np.load(sd / "science.npz")
    return {k: z[k] for k in z.files}, json.loads((sd / "science_meta.json").read_text())
