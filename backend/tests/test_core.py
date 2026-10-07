import json
from pathlib import Path

import numpy as np
import pytest
from scipy.stats import norm

from afterglow.core import combine, kappa, raw_class, verdict

GOLDEN = Path(__file__).parent / "golden" / "combine.json"
BASE = dict(q10=1.0, q50=2.0, q90=4.0, max=8.0, n=40)


def v(mu, sg, **b):
    b = {**BASE, **b}
    return verdict(np.array(mu), np.array(sg), b["q10"], b["q50"], b["q90"], b["max"], b["n"])


def test_single_sensor_passthrough():
    mc, sc, n = combine([[0.7], [np.nan]], [[0.3], [np.nan]], [True, True], 0.0)
    assert mc[0] == pytest.approx(0.7) and sc[0] == pytest.approx(0.3) and n[0] == 1


def test_two_equal_sensors_independent_and_correlated():
    _, s0, _ = combine([0.7, 0.7], [0.3, 0.3], [True, True], 0.0)
    _, s1, _ = combine([0.7, 0.7], [0.3, 0.3], [True, True], 1.0)
    assert s0 == pytest.approx(0.3 / np.sqrt(2)) and s1 == pytest.approx(0.3)


def test_disabled_and_missing_sensors_do_not_contribute():
    mc, sc, n = combine([0.5, 5.0, np.nan], [0.2, 0.2, np.nan], [True, False, True], 0.0)
    assert mc == pytest.approx(0.5) and n == 1
    mc, sc, n = combine([np.nan, np.nan], [np.nan, np.nan], [True, True], 0.0)
    assert np.isnan(mc) and n == 0


def test_verdict_boundaries():
    # exactly at q90: P(high) = 0.5 -> typical
    code, p_hi, _ = v(np.log(4.0), 0.2)
    assert code == 3 and p_hi == pytest.approx(0.5)
    assert v(np.log(4.0) + 1.3 * 0.2, 0.2)[0] == 5          # P > 0.9 -> unusually high
    assert v(np.log(4.0) + 0.3 * 0.2, 0.2)[0] == 4          # 0.6 < P < 0.9 -> possibly high
    assert v(np.log(8.0) + 2.0, 0.1)[0] == 6                # lower 80% bound above the baseline maximum -> record
    assert v(np.log(1.0) - 1.3 * 0.2, 0.2)[0] == 1          # unusually low
    assert v(np.nan, np.nan)[0] == 0                        # not observed
    assert v(0.7, 0.3, n=10)[0] == 7                        # insufficient baseline


def test_low_verdict_needs_meaningful_baseline_activity():
    # q10 = 0.2 detections / 1000 km2-days is below Q_MIN=0.5: never an 'unusually low' call
    assert v(np.log(0.05), 0.1, q10=0.2, q50=0.3, q90=0.6, max=1.0)[0] == 3


def test_probabilities_match_normal_cdf():
    mu, sg = 0.9, 0.35
    _, p_hi, p_lo = v(mu, sg)
    assert p_hi == pytest.approx(1 - norm.cdf((np.log(4.0) - mu) / sg))
    assert p_lo == pytest.approx(norm.cdf((np.log(1.0) - mu) / sg))


def test_raw_class():
    c = raw_class(np.array([0.0, 3.0, 9.0, np.nan]), 1.0, 5.0, 40)
    assert c.tolist() == [1, 3, 5, 0]


def test_kappa():
    a = np.array([0, 1, 2, 0, 1, 2])
    assert kappa(a, a) == pytest.approx(1.0)
    assert kappa(np.array([0, 0, 1, 1]), np.array([0, 1, 0, 1]), 2) == pytest.approx(0.0)
    assert kappa(np.array([0, 0, 1, 1]), np.array([1, 1, 0, 0]), 2) == pytest.approx(-1.0)


def test_golden_cases_reproduce():
    if not GOLDEN.exists():
        pytest.skip("run tests/make_golden.py first")
    cases = json.loads(GOLDEN.read_text())["cases"]
    assert len(cases) == 200
    for c in cases:
        mu = np.array([np.nan if x is None else x for x in c["mu"]], float)
        sg = np.array([np.nan if x is None else x for x in c["sigma"]], float)
        mc, sc, n = combine(mu, sg, np.array(c["enabled"], bool), c["r"])
        b = c["baseline"]
        code, p_hi, p_lo = verdict(mc, sc, b["q10"], b["q50"], b["q90"], b["max"], b["n"])
        e = c["expect"]
        assert int(code) == e["verdict"] and int(n) == e["n_used"]
        for got, want in ((mc, e["mu_c"]), (sc, e["sigma_c"]), (p_hi, e["p_hi"]), (p_lo, e["p_lo"])):
            assert (want is None and not np.isfinite(got)) or got == pytest.approx(want, abs=1e-9)
