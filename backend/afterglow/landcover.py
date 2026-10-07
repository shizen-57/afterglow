"""S2: land-cover strata per district from ESA WorldCover 2021 v200 (CC BY 4.0), read from the public COGs.

Stratum = majority group among forest (class 10), cropland (40) and other land (everything else except water 80 and
snow/ice 70). If WorldCover cannot be read, strata are set to 'other' and the pipeline pools across units (level-1 bridges).
"""
from __future__ import annotations

import json
import math

import numpy as np
import rasterio
import rasterio.features
from rasterio.transform import from_origin

from . import http
from .boundaries import districts, load_units, region_cfg, state_dir

BASE = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_{name}_Map.tif"
DEC = 2250  # decimated tile size: 3 deg / 2250 = 0.00133 deg (~148 m)
CLASSES = {10: "tree_cover", 20: "shrubland", 30: "grassland", 40: "cropland", 50: "built_up", 60: "bare",
           70: "snow_ice", 80: "water", 90: "wetland", 95: "mangroves", 100: "moss_lichen"}


def tile_names(bbox):
    w, s, e, n = bbox
    out = []
    for la in range(int(math.floor(s / 3) * 3), int(math.floor(n / 3) * 3) + 3, 3):
        for lo in range(int(math.floor(w / 3) * 3), int(math.floor(e / 3) * 3) + 3, 3):
            out.append((la, lo))
    return out


def read_tile(la: int, lo: int) -> np.ndarray:
    name = f"{'N' if la >= 0 else 'S'}{abs(la):02d}{'E' if lo >= 0 else 'W'}{abs(lo):03d}"
    last = None
    for _ in range(3):
        try:
            with rasterio.Env(GDAL_HTTP_TIMEOUT=60, GDAL_HTTP_MAX_RETRY=3, GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
                with rasterio.open(BASE.format(name=name)) as ds:
                    return ds.read(1, out_shape=(DEC, DEC), resampling=rasterio.enums.Resampling.mode)
        except Exception as e:  # tile may not exist over open ocean
            last = e
    print(f"  worldcover tile {name} unavailable ({last}); treated as no data")
    return np.zeros((DEC, DEC), np.uint8)


def run(region: str):
    cfg = region_cfg(region)
    units = load_units(region)
    tiles = tile_names(cfg["bbox"])
    las = sorted({t[0] for t in tiles})
    los = sorted({t[1] for t in tiles})
    mosaic = np.zeros((len(las) * DEC, len(los) * DEC), np.uint8)
    for la, lo in tiles:
        r, c = (len(las) - 1 - las.index(la)), los.index(lo)
        mosaic[r * DEC:(r + 1) * DEC, c * DEC:(c + 1) * DEC] = read_tile(la, lo)
    res = 3.0 / DEC
    tr = from_origin(los[0], las[-1] + 3, res, res)
    shapes = [(u["geom"], u["idx"] + 1) for u in districts(units)]
    idx = rasterio.features.rasterize(shapes, out_shape=mosaic.shape, transform=tr, fill=0, dtype="int32")
    out = {}
    ok_any = bool((mosaic > 0).any())
    for u in units:
        if u["kind"] == "country":
            m = idx > 0
        else:
            m = idx == (u["idx"] + 1)
        vals, cnt = np.unique(mosaic[m], return_counts=True)
        frac = {CLASSES.get(int(v), str(int(v))): round(float(c) / max(1, cnt.sum()), 4) for v, c in zip(vals, cnt) if v > 0}
        land = {k: v for k, v in frac.items() if k not in ("water", "snow_ice")}
        forest = land.get("tree_cover", 0.0)
        crop = land.get("cropland", 0.0)
        other = max(0.0, sum(land.values()) - forest - crop)
        stratum = "other"
        if ok_any and land:
            stratum = max([("forest", forest), ("cropland", crop), ("other", other)], key=lambda x: x[1])[0]
        out[u["id"]] = dict(stratum=stratum, landcover=frac)
    (state_dir(region) / "landcover.json").write_text(json.dumps(dict(
        units=out, source="ESA WorldCover 2021 v200 (CC BY 4.0)", available=ok_any, resolution_deg=round(res, 6))), encoding="utf-8")
    from collections import Counter
    print("  strata:", dict(Counter(v["stratum"] for k, v in out.items() if "-ADM" in k)), "available:", ok_any)


def load(region: str) -> dict:
    p = state_dir(region) / "landcover.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"units": {}, "available": False}
