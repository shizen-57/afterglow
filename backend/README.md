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

Connected. `python -m afterglow export-frontend` writes `out/frontend/afterglow-model.json`; the frontend's Node server
(`../frontend/server.mjs`) validates and indexes it on the server (observations 2022-2024 plus per-district,
per-period estimates, including fleet-removal `grounded` estimates). The browser loads only metadata, boundaries,
and the selected eight-day period from `/api/workspace/*`, rather than downloading the complete archive.
Filtering, district/pass summaries, retention, calendar aggregation, imports, and exports run in the Node query layer.
Scientific fitting and data preparation remain in this Python pipeline. The path can be changed with `AFTERGLOW_MODEL`.
If the file does not exist the query server uses the real saved/live FIRMS feed. Restart `npm run dev` after exporting.
The richer `/data/v1` files (clouds, real pass times, terrain) are not used by the frontend yet.

## What is real, and what is not

* Detections: FIRMS yearly country files (MODIS C6.1, S-NPP, NOAA-20) 2001-2024. **2025-2026 and NOAA-21 are missing** until a
  `FIRMS_MAP_KEY` is provided (that code path is written but untested).
* Coverage: Terra/Aqua from MOD14A1/MYD14A1 fire masks. **VIIRS coverage is a proxy copied from same-day Aqua** (flag 32,
  `coverage_source: proxy_A`). The native VIIRS path (`coverage-viirs`, needs `EARTHDATA_TOKEN`) is written but untested.
* Terrain: AWS Terrain Tiles (SRTM-based), not NASADEM.
* Static heat sources (likely brick kilns/industry): 70 learned 400 m cells; their detections are flagged, not deleted.

## Validation (Bangladesh, held-out 2023-2024) - read before claiming anything

Written to `out/data/v1/validation.json`. Only two held-out years exist, so every year-block CI is unreliable.

What holds:
* **Rate continuity.** At national level the bridged NOAA-20 log-rate tracks Aqua's with correlation 0.97 (mean log bias -0.13).
* **Step change.** When S-NPP joins, raw counts jump by +0.26 in log terms; the harmonized series moves +0.03.
* **Cloud artifact.** Spearman rho between anomaly and clear-view fraction in quiet periods: 0.14 for raw counts, 0.01 harmonized.

What does not hold, or cannot be judged:
* **H1 (verdict agreement) is not supported at district level.** kappa 0.013 for the bridges vs 0.11 for a constant ratio. Most
  district-periods in Bangladesh have 0-3 detections, so about 98% of cells are "typical" for both sensors and kappa is mostly
  noise. At national level the held-out years contain no unusual periods, so kappa is degenerate (0.0). It needs a region with
  more fires or more held-out years.
* **Intervals.** Coverage of the 80% interval is 0.98 over all cells (zero-count cells are trivially covered) but only 0.63
  (n = 57) in cells where the bridge predicts at least 3 Aqua detections. So intervals are too wide when counts are tiny and a
  little too narrow when they are not; a count-aware calibration is still open (a first, naive attempt was disabled; see `science.py`).
* The Terra control shows no verdict agreement (kappa 0.02): Terra's counts are too sparse per district-period.

The chain no longer draws synthetic counts at each link (that biased log-rates low and double-counted Poisson noise); it
propagates the expected rate and adds delta-method variance (`predict_sensor`, covered by a test).

Deviation from backend.md: bridges use total counts with a night-share covariate, solved by a small NumPy IRLS with a weak
prior; annual intervals are a delta-method approximation.

Data: NASA FIRMS/LANCE, LP DAAC (MOD14A1/MYD14A1), CMR; geoBoundaries (CC BY 3.0 IGO); ESA WorldCover (CC BY 4.0);
CelesTrak. Not affiliated with or endorsed by NASA.
