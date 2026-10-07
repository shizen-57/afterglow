"""Shared formulas (backend.md 6.3 / 6.4). The browser re-implements exactly these two steps for the stress test and
baseline switch; tests/golden/combine.json locks Python and TypeScript to identical results.
All functions are pure numpy and accept arbitrary leading dimensions.
"""
from __future__ import annotations

import numpy as np
from scipy.special import ndtr

from .config import (MIN_BASELINE_N, P_MAYBE, P_SURE, Q_MIN, V_INSUFFICIENT, V_NOT_OBS, V_POSSIBLY_HIGH, V_POSSIBLY_LOW,
                     V_RECORD, V_TYPICAL, V_UNUSUALLY_HIGH, V_UNUSUALLY_LOW, Z80, Z95)


def combine(mu, sigma, enabled, r):
    """Inverse-variance combination in log space with inter-sensor correlation r.

    mu, sigma: arrays [S, ...] (NaN where a sensor has no valid estimate); enabled: bool [S] or [S, ...].
    Returns mu_c, sigma_c, n_used (NaN / 0 where no sensor contributes).
    """
    mu = np.asarray(mu, dtype=np.float64)
    sigma = np.asarray(sigma, dtype=np.float64)
    en = np.asarray(enabled, dtype=bool)
    en = en.reshape(en.shape + (1,) * (mu.ndim - en.ndim)) if en.ndim < mu.ndim else en
    ok = en & np.isfinite(mu) & np.isfinite(sigma) & (sigma > 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        w = np.where(ok, 1.0 / np.where(ok, sigma, 1.0) ** 2, 0.0)
        sw = w.sum(0)
        mu_c = np.where(sw > 0, (w * np.where(ok, mu, 0.0)).sum(0) / np.where(sw > 0, sw, 1.0), np.nan)
        n = ok.sum(0)
        var = (1.0 / np.where(sw > 0, sw, np.nan)) * (1.0 + (n - 1) * r)
    return mu_c, np.sqrt(var), n


def verdict(mu, sigma, q10, q50, q90, qmax, n_base):
    """Verdict code, P(above q90), P(below q10) for log-scale estimate (mu, sigma) against a baseline (H scale).

    Codes: 0 not observed (mu is NaN) · 1 unusually low · 2 possibly low · 3 typical · 4 possibly high ·
    5 unusually high · 6 record · 7 insufficient baseline.
    """
    mu, sigma = np.asarray(mu, np.float64), np.asarray(sigma, np.float64)
    q10, q90, qmax = (np.asarray(a, np.float64) for a in (q10, q90, qmax))
    with np.errstate(divide="ignore", invalid="ignore"):
        p_hi = 1.0 - ndtr((np.log(q90) - mu) / sigma)
        p_lo = ndtr((np.log(q10) - mu) / sigma)
        lo80 = np.exp(mu - Z80 * sigma)
    code = np.full(mu.shape, V_TYPICAL, dtype=np.int8)
    low_ok = q10 >= Q_MIN
    code[(p_lo >= P_MAYBE) & low_ok] = V_POSSIBLY_LOW
    code[(p_lo >= P_SURE) & low_ok] = V_UNUSUALLY_LOW
    code[p_hi >= P_MAYBE] = V_POSSIBLY_HIGH
    code[p_hi >= P_SURE] = V_UNUSUALLY_HIGH
    code[lo80 > qmax] = V_RECORD
    code[np.asarray(n_base) < MIN_BASELINE_N] = V_INSUFFICIENT
    code[~np.isfinite(mu) | ~np.isfinite(sigma)] = V_NOT_OBS
    p_hi = np.where(np.isfinite(p_hi), p_hi, np.nan)
    p_lo = np.where(np.isfinite(p_lo), p_lo, np.nan)
    return code, p_hi, p_lo


def intervals(mu, sigma):
    return {"H": np.exp(mu), "lo80": np.exp(mu - Z80 * sigma), "hi80": np.exp(mu + Z80 * sigma),
            "lo95": np.exp(mu - Z95 * sigma), "hi95": np.exp(mu + Z95 * sigma)}


def raw_class(value, q10, q90, n_base):
    """Naive classification of a raw count against raw baseline quantiles (no uncertainty): 1 low, 3 typical, 5 high."""
    value = np.asarray(value, np.float64)
    code = np.full(value.shape, V_TYPICAL, dtype=np.int8)
    code[value < np.asarray(q10)] = V_UNUSUALLY_LOW
    code[value > np.asarray(q90)] = V_UNUSUALLY_HIGH
    code[np.asarray(n_base) < MIN_BASELINE_N] = V_INSUFFICIENT
    code[~np.isfinite(value)] = V_NOT_OBS
    return code


def kappa(a, b, k: int = 3) -> float:
    """Cohen's kappa for two integer label arrays with labels 0..k-1."""
    a, b = np.asarray(a).ravel(), np.asarray(b).ravel()
    if len(a) == 0:
        return float("nan")
    m = np.zeros((k, k))
    np.add.at(m, (a, b), 1)
    n = m.sum()
    po = np.trace(m) / n
    pe = (m.sum(0) * m.sum(1)).sum() / n**2
    return float((po - pe) / (1 - pe)) if pe < 1 else float("nan")
