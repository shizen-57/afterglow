"""S10: terrain tiles for the 3D scene (Terrarium-encoded PNG, MapLibre raster-dem).

Source: AWS Terrain Tiles (public dataset; composed from SRTM, GMTED2010, NED and other open elevation sources).
These are fetched ready-made. The NASADEM route described in backend.md S10 (Earthdata token + mosaic) is NOT
implemented here; provenance records the real source used.

MapLibre source: {"type":"raster-dem","encoding":"terrarium","tiles":[".../tiles/terrain/{z}/{x}/{y}.png"],"tileSize":256,"maxzoom":10}
"""
from __future__ import annotations

import datetime as dt
import json
import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

from . import http
from .boundaries import region_cfg
from .config import OUT

URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"


def lonlat_to_tile(lon: float, lat: float, z: int) -> tuple[int, int]:
    n = 2**z
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
    return min(max(x, 0), n - 1), min(max(y, 0), n - 1)


def tiles_for_bbox(bbox, zmin: int, zmax: int):
    w, s, e, n = bbox
    for z in range(zmin, zmax + 1):
        x0, y0 = lonlat_to_tile(w, n, z)
        x1, y1 = lonlat_to_tile(e, s, z)
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                yield z, x, y


def decode_terrarium(png: np.ndarray) -> np.ndarray:
    """Terrarium: height = R*256 + G + B/256 - 32768 (metres)."""
    p = png.astype(np.float64)
    return p[..., 0] * 256.0 + p[..., 1] + p[..., 2] / 256.0 - 32768.0


def encode_terrarium(h: np.ndarray) -> np.ndarray:
    v = np.asarray(h, np.float64) + 32768.0
    r = np.floor(v / 256.0)
    g = np.floor(v) % 256
    b = np.floor((v - np.floor(v)) * 256.0)
    return np.stack([r, g, b], -1).astype(np.uint8)


def run(region: str, out_dir: str | None = None, zmin: int = 5, zmax: int = 10, workers: int = 12):
    cfg = region_cfg(region)
    base = (Path(out_dir) if out_dir else OUT) / "tiles" / "terrain"
    jobs = list(tiles_for_bbox(cfg["bbox"], zmin, zmax))
    done = failed = 0

    def one(j):
        z, x, y = j
        p = base / str(z) / str(x) / f"{y}.png"
        if p.exists() and p.stat().st_size > 0:
            return True
        try:
            r = http.get(URL.format(z=z, x=x, y=y), retries=3)
            Image.open(__import__("io").BytesIO(r.content)).verify()  # reject corrupt downloads
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(r.content)
            return True
        except Exception:
            return False

    with ThreadPoolExecutor(workers) as ex:
        for ok in ex.map(one, jobs):
            done += ok
            failed += not ok
    base.mkdir(parents=True, exist_ok=True)
    (base / "provenance.json").write_text(json.dumps(dict(
        source="AWS Terrain Tiles (Terrarium encoding)", url=URL, zoom=[zmin, zmax], tiles=done, failed=failed,
        license="Public dataset; composed from SRTM (NASA/USGS), GMTED2010, NED and other sources. Attribution: Mapzen/AWS Terrain Tiles",
        note="NASADEM was not used. Elevation exaggeration is applied in the front end.",
        accessed=dt.datetime.now(dt.timezone.utc).date().isoformat())), encoding="utf-8")
    print(f"  terrain tiles z{zmin}-{zmax}: {done} ok, {failed} failed -> {base}")
    if failed:
        print("  re-run to retry failed tiles (completed tiles are skipped)")
