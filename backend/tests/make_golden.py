"""Generate tests/golden/combine.json: 200 cases for the shared combine()/verdict() formulas.

The front end must reproduce every `expect` value (tolerance 1e-9 for numbers, exact for verdict codes) with its own
implementation of backend.md 6.3 / 6.4. Run: python tests/make_golden.py
Cases 0-9 are hand-built edge cases whose results are also asserted analytically in test_core.py.
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from afterglow.core import combine, verdict  # noqa: E402


def nn(x):
    return None if x is None or not np.isfinite(float(x)) else float(x)


def case(mu, sg, en, r, base):
    mu_a = np.array([np.nan if v is None else v for v in mu], float)
    sg_a = np.array([np.nan if v is None else v for v in sg], float)
    mc, sc, n = combine(mu_a, sg_a, np.array(en, bool), r)
    code, p_hi, p_lo = verdict(mc, sc, base["q10"], base["q50"], base["q90"], base["max"], base["n"])
    return dict(mu=mu, sigma=sg, enabled=en, r=r, baseline=base,
                expect=dict(mu_c=nn(mc), sigma_c=nn(sc), n_used=int(n), verdict=int(code), p_hi=nn(p_hi), p_lo=nn(p_lo)))


def main():
    rng = np.random.default_rng(42)
    B = lambda q10, q50, q90, mx, n=40: dict(q10=q10, q50=q50, q90=q90, max=mx, n=n)  # noqa: E731
    base0 = B(1.0, 2.0, 4.0, 8.0)
    cases = [
        case([0.7, None, None, None, None], [0.3, None, None, None, None], [1, 1, 1, 1, 1], 0.0, base0),            # single sensor
        case([0.7, 0.7, None, None, None], [0.3, 0.3, None, None, None], [1, 1, 1, 1, 1], 0.0, base0),              # two equal, independent
        case([0.7, 0.7, None, None, None], [0.3, 0.3, None, None, None], [1, 1, 1, 1, 1], 1.0, base0),              # two equal, fully correlated
        case([None] * 5, [None] * 5, [1] * 5, 0.0, base0),                                                         # nothing observed -> 0
        case([0.7, 0.9, None, None, None], [0.3, 0.2, None, None, None], [0, 0, 1, 1, 1], 0.0, base0),               # all contributors disabled -> 0
        case([float(np.log(4.0)) + 1.3 * 0.2, None, None, None, None], [0.2, None, None, None, None], [1] * 5, 0.0, base0),  # unusually high
        case([float(np.log(8.0)) + 2.0, None, None, None, None], [0.1, None, None, None, None], [1] * 5, 0.0, base0),       # record
        case([float(np.log(1.0)) - 1.3 * 0.2, None, None, None, None], [0.2, None, None, None, None], [1] * 5, 0.0, base0),  # unusually low
        case([0.7, None, None, None, None], [0.3, None, None, None, None], [1] * 5, 0.0, B(1.0, 2.0, 4.0, 8.0, 10)),        # insufficient baseline
        case([float(np.log(0.3)) - 3.0, None, None, None, None], [0.2, None, None, None, None], [1] * 5, 0.0, B(0.2, 0.3, 0.6, 1.0)),  # q10 below Q_MIN -> no low verdict
    ]
    for _ in range(190):
        mu = [None if rng.random() < 0.35 else float(np.round(rng.normal(0.5, 1.2), 4)) for _ in range(5)]
        sg = [None if m is None else float(np.round(rng.uniform(0.08, 0.9), 4)) for m in mu]
        en = [int(rng.random() > 0.25) for _ in range(5)]
        q10 = float(np.round(rng.uniform(0.05, 1.5), 4))
        q50 = float(np.round(q10 * rng.uniform(1.2, 3.0), 4))
        q90 = float(np.round(q50 * rng.uniform(1.2, 4.0), 4))
        mx = float(np.round(q90 * rng.uniform(1.0, 2.5), 4))
        cases.append(case(mu, sg, en, float(rng.choice([0.0, 0.2, 0.5, 0.9])), B(q10, q50, q90, mx, int(rng.integers(5, 60)))))
    out = Path(__file__).parent / "golden" / "combine.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(dict(schema="afterglow/golden-combine@1", cases=cases), indent=0), encoding="utf-8")
    print(f"wrote {len(cases)} cases -> {out}")


if __name__ == "__main__":
    main()
