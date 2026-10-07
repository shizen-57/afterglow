import numpy as np
import pandas as pd
import pytest

from afterglow import config, coverage, detections, science, terrain
from afterglow.config import SIDX


# ---------------------------------------------------------------- periods and grid
def test_periods():
    assert config.period_of_doy(1) == 1 and config.period_of_doy(8) == 1 and config.period_of_doy(9) == 2
    assert config.period_of_doy(360) == 45 and config.period_of_doy(361) == 46 and config.period_of_doy(366) == 46
    assert config.days_in_period(2023, 46) == 5 and config.days_in_period(2024, 46) == 6 and config.days_in_period(2024, 3) == 8
    assert sum(config.days_in_period(2023, p) for p in range(1, 47)) == 365
    assert sum(config.days_in_period(2024, p) for p in range(1, 47)) == 366


def test_sin_grid():
    assert coverage.tile_of(90.4, 23.8) == (26, 6) and coverage.tile_of(88.1, 25.9) == (25, 6)
    tr = coverage.tile_transform(18, 9)  # tile whose top-left corner is the projection origin
    assert tr.c == pytest.approx(0.0) and tr.f == pytest.approx(0.0) and tr.a == pytest.approx(926.625433, abs=1e-5)
    assert config.PX_KM2 == pytest.approx(0.858634, abs=1e-6)


def test_count_mask_conserves_land_pixels():
    n = config.NPX * config.NPX
    idx = np.full(n, -1, np.int16)
    idx[:1000] = 0
    idx[1000:1500] = 1
    land = np.ones(n, bool)
    fm = np.full((2, n), 5, np.uint8)
    fm[0, :100] = 4           # cloud in unit 0, day 0
    fm[1, 1000:1100] = 8      # fire (counts as clear) in unit 1, day 1
    fm[1, :50] = 3            # 'water' class: neither clear nor cloud
    clear, cloud, land_px = coverage.count_mask(fm, idx, land, 2)
    assert land_px.tolist() == [1000, 500]
    assert cloud[0].tolist() == [100, 0] and clear[0].tolist() == [900, 500]
    assert clear[1].tolist() == [950, 500]


# ---------------------------------------------------------------- detections
def _firms(kind):
    if kind == "T+A":
        return pd.DataFrame(dict(latitude=[24.0, 24.0], longitude=[90.0, 90.1], acq_date=["2020-02-01"] * 2, acq_time=[730, 1630],
                                 satellite=["Aqua", "Terra"], confidence=[20, 85], frp=[3.0, 9.0], daynight=["D", "N"], type=[0, 0]))
    return pd.DataFrame(dict(latitude=[24.0, 24.0], longitude=[90.0, 90.1], acq_date=["2023-02-01"] * 2, acq_time=[748, 748],
                             satellite=["N20", "N"], confidence=["l", "h"], frp=[1.0, 2.0], daynight=["D", "D"], type=[0, 2]))


def test_normalize_mapping():
    m = detections.normalize(_firms("T+A"), "T+A")
    assert m["s"].tolist() == [SIDX["A"], SIDX["T"]] and m["conf"].tolist() == [0, 2] and m["night"].tolist() == [False, True]
    v = detections.normalize(_firms("N"), "N")
    assert v["s"].tolist() == [SIDX["J1"], SIDX["N"]] and v["conf"].tolist() == [0, 2] and v["type"].tolist() == [0, 2]


def test_dedupe_viirs_keeps_highest_frp_within_200m():
    base = dict(s=SIDX["N"], t=1000, night=False, conf=1, type=0, src=0)
    d = pd.DataFrame([dict(base, lat=24.0, lon=90.0, frp=1.0), dict(base, lat=24.0005, lon=90.0, frp=5.0),     # ~55 m apart: duplicates
                      dict(base, lat=24.1, lon=90.0, frp=2.0),                                                  # far away: kept
                      dict(base, lat=24.0, lon=90.0, frp=3.0, t=1001)])                                         # other minute: kept
    out = detections.dedupe_viirs(d)
    assert len(out) == 3 and 5.0 in out["frp"].values and 1.0 not in out["frp"].values


def test_static_mask_flags_repeated_kiln_but_not_one_off_burn():
    rows = []
    for year in (2015, 2016):  # a kiln: ~every other day, November to April
        for day in pd.date_range(f"{year}-01-01", f"{year}-04-30", freq="3D"):
            rows.append((day, 24.0, 90.0))
    rows += [(pd.Timestamp("2015-03-03"), 23.0, 89.0)] * 8   # a single-day burn: many detections, one day
    t = [int((pd.Timestamp(r[0]) - pd.Timestamp("1970-01-01")) / pd.Timedelta(minutes=1)) for r in rows]
    d = pd.DataFrame(dict(t=t, lat=[r[1] for r in rows], lon=[r[2] for r in rows], s=SIDX["N"]))
    mask = detections.learn_static_mask(d)
    cx, cy = int(np.floor(90.0 / config.STATIC_GRID_DEG)), int(np.floor(24.0 / config.STATIC_GRID_DEG))
    assert (cx, cy) in mask
    assert (int(np.floor(89.0 / config.STATIC_GRID_DEG)), int(np.floor(23.0 / config.STATIC_GRID_DEG))) not in mask


def test_static_mask_applies_with_dilation_for_modis_only():
    cx, cy = int(np.floor(90.0 / config.STATIC_GRID_DEG)), int(np.floor(24.0 / config.STATIC_GRID_DEG))
    d = pd.DataFrame(dict(lon=[90.0 + config.STATIC_GRID_DEG] * 2, lat=[24.0] * 2, s=[SIDX["A"], SIDX["N"]]))
    hit = detections.apply_static(d, {(cx, cy)})
    assert hit.tolist() == [True, False]  # MODIS (1 km pixel) matches the neighbouring cell, VIIRS does not


# ---------------------------------------------------------------- science
def test_irls_recovers_coefficients():
    rng = np.random.default_rng(0)
    n = 30000
    x = rng.normal(0, 1, n)
    X = np.column_stack([np.ones(n), x, rng.uniform(0, 1, n), rng.normal(size=n), rng.normal(size=n)])
    off = np.log(rng.uniform(0.5, 4, n))
    mu = np.exp(off + 0.3 + 0.8 * x)
    y = rng.negative_binomial(2.0, 2.0 / (2.0 + mu)).astype(float)
    b, a = science.fit_nb(y, X, off)
    assert b[0] == pytest.approx(0.3, abs=0.06) and b[1] == pytest.approx(0.8, abs=0.06) and a == pytest.approx(0.5, abs=0.12)


def test_baseline_excludes_the_target_year():
    U1, Y, P = 1, 24, 46
    H = np.ones((U1, Y, P))
    H[0, 10] = 100.0                      # year index 10 is extreme
    b = science.baseline_stats(H, 2001, (2003, 2022), True)
    assert b["q90"][0, 10, 5] == pytest.approx(1.0) and b["max"][0, 10, 5] == pytest.approx(1.0)  # target year is not in its own baseline
    assert b["q90"][0, 11, 5] > 1.0 or b["max"][0, 11, 5] == pytest.approx(100.0)                 # but it is in every other year's baseline
    assert b["n"][0, 5, 20] >= 20


# ---------------------------------------------------------------- terrain
def test_terrarium_roundtrip():
    h = np.array([[-10.0, 0.0, 12.5], [150.25, 3000.0, 8848.0]])
    back = terrain.decode_terrarium(terrain.encode_terrarium(h))
    assert np.abs(back - h).max() < 0.01


def test_tile_math():
    assert terrain.lonlat_to_tile(90.4, 23.8, 6) == (48, 27)
    z5 = list(terrain.tiles_for_bbox([88.0, 20.6, 92.7, 26.7], 5, 5))
    assert 0 < len(z5) < 20


def test_predict_sensor_propagates_mean_and_delta_variance():
    S, U1, Y, P = config.S, 1, 1, config.P
    D = np.zeros((S, U1, Y, P))
    D[SIDX["T"]] = 4.0
    A = dict(D=D, clear=np.full((S, U1, Y, P), 2000.0))
    V = np.zeros((S, U1, Y, P), bool)
    V[SIDX["T"]] = True
    rho = np.full((S, U1, Y, P), 2.0)
    B = 5
    pool = dict(beta=np.tile([0.0, 1.0, 0.0, 0.0, 0.0], (B, 1)), alpha=np.full(B, 0.2), level=1, n=1)
    mu, sg = science.predict_sensor("T", A, rho, V, np.zeros_like(rho), {("T", "A"): {"pool": pool}},
                                    np.array([-1], np.int8), np.random.default_rng(0), B)
    assert mu[0, 0, 0] == pytest.approx(np.log(2.0 + config.RATE_FLOOR))          # E[rate], no sampled counts
    assert sg[0, 0, 0] == pytest.approx(np.sqrt(1 / 4.5 + 0.2))                  # source count noise + overdispersion
