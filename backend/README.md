# Afterglow backend

Python pipeline that turns real NASA fire data into a static JSON API (`out/data/v1/…`) and a file the frontend can import
(`out/frontend/afterglow-model.json`). Design and formulas: [`../backend.md`](../backend.md). No mock data anywhere.

## Run

```sh
pip install -e .[dev]                    # Python >= 3.11
python -m afterglow units                # districts (geoBoundaries)
python -m afterglow landcover            # strata (ESA WorldCover)
python -m afterglow detections           # FIRMS science-quality hotspots (no key needed through the last published year)
python -m afterglow coverage             # MODIS L3 clear-view coverage (Planetary Computer, no login) ~20 min, resumable
python -m afterglow passes               # real overpass times from NASA CMR
python -m afterglow aggregate && python -m afterglow science && python -m afterglow validate
python -m afterglow export               # -> out/data/v1
python -m afterglow export-frontend      # -> out/frontend/afterglow-model.json  (import it in the frontend)
python -m afterglow terrain              # 3D terrain tiles
python -m afterglow nrt                  # next passes (+ near-real-time hotspots if FIRMS_MAP_KEY is set)
python -m pytest
```

## Connecting to the frontend

The frontend (`../frontend`) does **not** read `/data/v1`. It loads the live 7-day FIRMS feed itself and takes model results
through its **Import → calibrated model JSON**. `export-frontend` writes exactly that format (observations + per-district,
per-period estimates with value/lower/upper/probability/coverage/baselineMedian and `grounded` fleet-removal estimates).
Import `out/frontend/afterglow-model.json` in the UI. To use the richer `/data/v1` files (clouds, real pass times, terrain),
the frontend would need a small loader; that is not done yet.

## What is real, and what is not

* Detections: FIRMS yearly country files (MODIS C6.1, S-NPP, NOAA-20) 2001-2024. **2025-2026 and NOAA-21 are missing** until a
  `FIRMS_MAP_KEY` is provided (that code path is written but untested).
* Coverage: Terra/Aqua from MOD14A1/MYD14A1 fire masks. **VIIRS coverage is a proxy copied from same-day Aqua** (flag 32,
  `coverage_source: proxy_A`). The native VIIRS path (`coverage-viirs`, needs `EARTHDATA_TOKEN`) is written but untested.
* Terrain: AWS Terrain Tiles (SRTM-based), not NASADEM.
* Static heat sources (likely brick kilns/industry): 70 learned 400 m cells; their detections are flagged, not deleted.

## Validation (Bangladesh, held-out 2023-2024) - read before claiming anything

Written to `out/data/v1/validation.json`. The headline claim H1 (NOAA-20 verdicts via bridges agree with Aqua better than a
constant ratio) is **not supported** by this build: kappa about 0.01 vs 0.19 for a constant ratio. Intervals are too wide
(coverage80 about 0.97, target 0.80). The Terra control also shows no agreement. Only two held-out years exist, so year-block
CIs are unreliable. What does hold: the S-NPP step change shrinks (log-ratio +0.26 raw vs -0.07 harmonized), and the cloud
artifact was removed by replacing a +0.5 pseudo-count with a constant rate floor.
A count-aware interval calibration is the next fix (a first attempt was disabled; see `science.py`).

Deviation from backend.md: bridges use total counts with a night-share covariate, solved by a small NumPy IRLS with a weak
prior; annual intervals are a delta-method approximation.

Data: NASA FIRMS/LANCE, LP DAAC (MOD14A1/MYD14A1), CMR; geoBoundaries (CC BY 3.0 IGO); ESA WorldCover (CC BY 4.0);
CelesTrak. Not affiliated with or endorsed by NASA.
