"""Command line: python -m afterglow <stage> [--region BGD] ..."""
from __future__ import annotations

import argparse
import sys
import time

from .boundaries import region_cfg


def _years(s: str | None, cfg: dict):
    if not s:
        return tuple(cfg["years"])
    a, _, b = s.partition("-")
    return int(a), int(b or a)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="afterglow")
    ap.add_argument("stage", choices=["units", "landcover", "detections", "coverage", "coverage-viirs", "passes",
                                      "aggregate", "science", "validate", "export", "export-frontend", "terrain", "nrt", "all"])
    ap.add_argument("--region", default="BGD")
    ap.add_argument("--years", help="e.g. 2001-2026")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--sensor", default="N", help="VIIRS sensor for coverage-viirs: N|J1|J2")
    ap.add_argument("--out", help="output folder (default backend/out/data/v1)")
    ap.add_argument("--obs-years", default="2022-2024", help="observation years for export-frontend, or all")
    ap.add_argument("--zmin", type=int, default=5)
    ap.add_argument("--zmax", type=int, default=10)
    a = ap.parse_args(argv)
    cfg = region_cfg(a.region)
    yrs = _years(a.years, cfg)
    t0 = time.time()

    def run(stage):
        print(f"== {stage} [{a.region}] ==", flush=True)
        if stage == "units":
            from .boundaries import build_units
            u = build_units(a.region)
            print(f"{len(u) - 1} districts + country")
        elif stage == "landcover":
            from .landcover import run as f
            f(a.region)
        elif stage == "detections":
            from .detections import run as f
            f(a.region, yrs)
        elif stage == "coverage":
            from .coverage import ingest_modis
            print("ingested items:", ingest_modis(a.region, yrs, a.workers))
        elif stage == "coverage-viirs":
            import os
            from .coverage import ingest_viirs
            tok = os.environ.get("EARTHDATA_TOKEN")
            if not tok:
                sys.exit("EARTHDATA_TOKEN not set; VIIRS native coverage unavailable (pipeline falls back to Aqua proxy).")
            print("ingested items:", ingest_viirs(a.region, a.sensor, yrs, tok))
        elif stage == "passes":
            from .passes import run as f
            f(a.region, yrs, a.workers)
        elif stage == "aggregate":
            from .aggregate import run as f
            f(a.region, yrs)
        elif stage == "science":
            from .science import run as f
            f(a.region)
        elif stage == "validate":
            from .validate import run as f
            f(a.region)
        elif stage == "export":
            from .export import run as f
            f(a.region, a.out)
        elif stage == "export-frontend":
            from .frontend_export import run as f
            f(a.region, a.out, a.obs_years)
        elif stage == "terrain":
            from .terrain import run as f
            f(a.region, a.out, a.zmin, a.zmax)
        elif stage == "nrt":
            from .live import run as f
            f(a.region, a.out)

    if a.stage == "all":
        for st in ["units", "landcover", "detections", "coverage", "passes", "aggregate", "science", "validate",
                   "export", "export-frontend", "terrain", "nrt"]:
            run(st)
    else:
        run(a.stage)
    print(f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
