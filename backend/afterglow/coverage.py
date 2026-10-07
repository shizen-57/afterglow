"""S4: clear-view coverage per district per day.

MODIS (Terra MOD14A1, Aqua MYD14A1) daily fire masks come from the Microsoft Planetary Computer COG copies of the
NASA LP DAAC products. No NASA login is needed (URLs are signed via the public /sign endpoint).
VIIRS daily masks (VNP14A1 / VJ114A1 / VJ214A1) live on LP DAAC and need an Earthdata token; see ingest_viirs().
That VIIRS path has NOT been exercised against live data in this environment (no credentials were available).

Definitions (backend.md S4): clear = land pixels whose daily max-composite class is 5 (non-fire land) or 7-9 (fire);
cloud = class 4; land is a static mask from the QA layer (state land or coast). Pixels are 0.858634 km2.
"""
from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import rasterio
import rasterio.features
import shapely
from rasterio.transform import Affine

from . import http
from .boundaries import districts, load_units, region_cfg, state_dir
from .config import CACHE, NPX, PX_M, R_SIN, TILE_M

PC = "https://planetarycomputer.microsoft.com/api"
COLLECTION = "modis-14A1-061"
SAT_OF_PREFIX = {"MOD14A1": "T", "MYD14A1": "A"}
CLEAR_CLASSES = (5, 7, 8, 9)
CLOUD_CLASS = 4


# --- grid geometry ---------------------------------------------------------------------------
def to_sin(geom):
    def f(xy):
        lon, lat = np.radians(xy[:, 0]), np.radians(xy[:, 1])
        return np.column_stack([R_SIN * lon * np.cos(lat), R_SIN * lat])
    return shapely.transform(geom, f)


def tile_transform(h: int, v: int) -> Affine:
    return Affine(PX_M, 0, -18 * TILE_M + h * TILE_M, 0, -PX_M, 9 * TILE_M - v * TILE_M)


def tile_of(lon: float, lat: float) -> tuple[int, int]:
    x = R_SIN * np.radians(lon) * np.cos(np.radians(lat))
    y = R_SIN * np.radians(lat)
    return int((x + 18 * TILE_M) // TILE_M), int((9 * TILE_M - y) // TILE_M)


def tiles_for_bbox(bbox) -> list[tuple[int, int]]:
    w, s, e, n = bbox
    return sorted({tile_of(lo, la) for lo in np.linspace(w, e, 25) for la in np.linspace(s, n, 25)})


def unit_index(region: str, tile: tuple[int, int], units: list[dict]) -> np.ndarray:
    """int16 (NPX*NPX) district index per pixel (-1 outside); cached on disk."""
    p = state_dir(region) / f"unit_index_h{tile[0]:02d}v{tile[1]:02d}.npy"
    if p.exists():
        return np.load(p)
    tr = tile_transform(*tile)
    shapes = [(to_sin(u["geom"]), u["idx"]) for u in districts(units)]
    arr = rasterio.features.rasterize(shapes, out_shape=(NPX, NPX), transform=tr, fill=-1, dtype="int16")
    np.save(p, arr.ravel())
    return arr.ravel()


# --- Planetary Computer access ------------------------------------------------------------------
class Signer:
    """Container-level SAS tokens obtained once via /sign and reused until close to expiry."""

    def __init__(self):
        self._lock = threading.Lock()
        self._tok: dict[str, tuple[str, float]] = {}

    @staticmethod
    def _key(base: str) -> str:
        u = urlparse(base)
        return u.netloc + "/" + u.path.split("/")[1]

    def sign(self, href: str) -> str:
        base = href.split("?")[0]
        key = self._key(base)
        with self._lock:
            ent = self._tok.get(key)
            if ent is None or ent[1] - time.time() < 120:
                j = http.get(f"{PC}/sas/v1/sign", params={"href": base}).json()
                q = j["href"].split("?", 1)[1]
                exp = pd.Timestamp(j["msft:expiry"]).timestamp()
                self._tok[key] = ent = (q, exp)
        return base + "?" + ent[0]

    def invalidate(self, href: str):
        with self._lock:
            self._tok.pop(self._key(href.split("?")[0]), None)


SIGNER = Signer()


def fetch_cog(href: str) -> bytes:
    for attempt in range(2):
        try:
            return http.get(SIGNER.sign(href)).content
        except http.AuthError:
            SIGNER.invalidate(href)
            if attempt:
                raise
    raise RuntimeError("unreachable")


def stac_items(bbox, start: str, end: str) -> list[dict]:
    body = {"collections": [COLLECTION], "bbox": list(bbox), "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z", "limit": 500}
    items, url = [], f"{PC}/stac/v1/search"
    while True:
        j = http.post_json(url, body)
        items += j["features"]
        nxt = next((l for l in j.get("links", []) if l.get("rel") == "next"), None)
        if not nxt or not j["features"]:
            return items
        body = {**body, **nxt.get("body", {})} if nxt.get("merge") else nxt.get("body", body)


def land_mask(region: str, tile: tuple[int, int]) -> np.ndarray:
    """Static land mask per tile from QA bits 0-1 (01 coast, 10 land), union over one mid-year file's 8 days."""
    p = state_dir(region) / f"land_h{tile[0]:02d}v{tile[1]:02d}.npy"
    if p.exists():
        return np.load(p)
    w = tile_transform(*tile)
    lon, lat = _tile_center_lonlat(tile)
    items = [i for i in stac_items([lon - .01, lat - .01, lon + .01, lat + .01], "2019-06-01", "2019-07-15")
             if f"h{tile[0]:02d}v{tile[1]:02d}" in i["id"]]
    if not items:
        raise RuntimeError(f"no STAC item to derive land mask for tile {tile}")
    qa = fetch_cog(items[0]["assets"]["QA"]["href"])
    with rasterio.MemoryFile(qa) as mf, mf.open() as ds:
        q = ds.read() & 3
    land = ((q == 1) | (q == 2)).any(axis=0).ravel()
    np.save(p, land)
    return land


def _tile_center_lonlat(tile):
    x = -18 * TILE_M + (tile[0] + 0.5) * TILE_M
    y = 9 * TILE_M - (tile[1] + 0.5) * TILE_M
    lat = y / R_SIN
    return float(np.degrees(x / (R_SIN * np.cos(lat)))), float(np.degrees(lat))


# --- counting ---------------------------------------------------------------------------------
def count_mask(fm: np.ndarray, idx: np.ndarray, land: np.ndarray, U: int):
    """fm: (nb, NPX*NPX) uint8. Returns clear, cloud (nb, U) and land_px (U,)."""
    ok = (idx >= 0) & land
    sel = np.flatnonzero(ok)
    u = idx[sel].astype(np.int64)
    land_px = np.bincount(u, minlength=U).astype(np.int32)
    clear = np.zeros((fm.shape[0], U), np.int32)
    cloud = np.zeros((fm.shape[0], U), np.int32)
    for b in range(fm.shape[0]):
        f = fm[b][sel]
        clear[b] = np.bincount(u[np.isin(f, CLEAR_CLASSES)], minlength=U)
        cloud[b] = np.bincount(u[f == CLOUD_CLASS], minlength=U)
    return clear, cloud, land_px


def _rows(sat: str, tile, start: date, clear, cloud, land_px) -> pd.DataFrame:
    nb, U = clear.shape
    us = np.flatnonzero(land_px > 0)
    d0 = (start - date(1970, 1, 1)).days
    return pd.DataFrame({
        "sat": np.full(nb * len(us), sat),
        "tile": np.full(nb * len(us), tile[0] * 100 + tile[1], np.int16),
        "date": np.repeat(np.arange(d0, d0 + nb, dtype=np.int32), len(us)),
        "unit": np.tile(us.astype(np.int16), nb),
        "clear": clear[:, us].ravel(), "cloud": cloud[:, us].ravel(),
        "land": np.tile(land_px[us], nb)})


def process_item(item: dict, ctx: dict) -> pd.DataFrame | None:
    m = re.search(r"h(\d\d)v(\d\d)", item["id"])
    tile = (int(m.group(1)), int(m.group(2)))
    if tile not in ctx["tiles"]:
        return None
    sat = SAT_OF_PREFIX[item["id"].split(".")[0]]
    idx, land = ctx["tiles"][tile]
    b = fetch_cog(item["assets"]["FireMask"]["href"])
    with rasterio.MemoryFile(b) as mf, mf.open() as ds:
        arr = ds.read()
    nb = arr.shape[0]
    start = date.fromisoformat(item["properties"]["start_datetime"][:10])
    end = date.fromisoformat(item["properties"]["end_datetime"][:10])
    if (end - start).days + 1 != nb:
        return None  # band/date mismatch: refuse to guess
    clear, cloud, land_px = count_mask(arr.reshape(nb, -1), idx, land, ctx["U"])
    return _rows(sat, tile, start, clear, cloud, land_px)


def ingest_modis(region: str, years: tuple[int, int], workers: int = 16, batch: int = 100, log=print) -> int:
    cfg = region_cfg(region)
    units = load_units(region)
    U = len(districts(units))
    sd = state_dir(region)
    parts = sd / "coverage_parts"
    parts.mkdir(exist_ok=True)
    done_p = sd / "coverage_done.json"
    done = set(json.loads(done_p.read_text())) if done_p.exists() else set()
    tiles = {}
    for t in tiles_for_bbox(cfg["bbox"]):
        tiles[t] = (unit_index(region, t, units), land_mask(region, t))
    if all((idx < 0).all() for idx, _ in tiles.values()):
        raise RuntimeError("no tile overlaps any district")
    tiles = {t: v for t, v in tiles.items() if (v[0] >= 0).any()}
    log(f"tiles with districts: {sorted(tiles)}")
    ctx = {"tiles": tiles, "U": U}
    items = []
    for y in range(years[0], years[1] + 1):
        its = stac_items(cfg["bbox"], f"{y}-01-01", f"{y}-12-31")
        its = [i for i in its if i["id"].split(".")[0] in SAT_OF_PREFIX]
        log(f"  STAC {y}: {len(its)} items")
        items += its
    todo = [i for i in items if i["id"] not in done]
    log(f"coverage items total={len(items)} todo={len(todo)}")
    n_ok, t0, buf, ids = 0, time.time(), [], []
    nxt = len(list(parts.glob("part_*.parquet")))

    def flush():
        nonlocal buf, ids, nxt
        if not buf:
            return
        pd.concat(buf).to_parquet(parts / f"part_{nxt:05d}.parquet", index=False)
        nxt += 1
        done.update(ids)
        done_p.write_text(json.dumps(sorted(done)))
        buf, ids = [], []

    with ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(process_item, i, ctx): i for i in todo}
        for k, f in enumerate(as_completed(futs), 1):
            it = futs[f]
            try:
                df = f.result()
            except Exception as e:  # keep going; failed items stay in `todo` for the next run
                log(f"  ! {it['id']}: {e}")
                continue
            if df is not None:
                buf.append(df)
                n_ok += 1
            ids.append(it["id"])
            if len(ids) >= batch:
                flush()
                log(f"  {k}/{len(todo)} items  {time.time() - t0:.0f}s")
    flush()
    return n_ok


def load_coverage(region: str) -> pd.DataFrame:
    """Daily per-district counts, one row per (sat, date, unit), summed across tiles."""
    parts = sorted((state_dir(region) / "coverage_parts").glob("part_*.parquet"))
    if not parts:
        return pd.DataFrame(columns=["sat", "date", "unit", "clear", "cloud", "land"])
    df = pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
    df = df.drop_duplicates(["sat", "tile", "date", "unit"])
    g = df.groupby(["sat", "date", "unit"], as_index=False)[["clear", "cloud", "land"]].sum()
    return g


# --- VIIRS native coverage (needs an Earthdata token; untested here) ------------------------
def viirs_firemask_from_h5(path_or_file) -> np.ndarray:
    """Find the FireMask dataset (1200x1200 uint8) anywhere in a VIIRS L3 HDF5 file."""
    import h5py
    found = []
    with h5py.File(path_or_file, "r") as f:
        def visit(name, obj):
            if isinstance(obj, h5py.Dataset) and name.split("/")[-1] == "FireMask" and obj.shape[-2:] == (NPX, NPX):
                found.append(name)
        f.visititems(visit)
        if not found:
            raise RuntimeError("no FireMask dataset in file")
        return np.asarray(f[found[0]][...], dtype=np.uint8).reshape(-1, NPX * NPX)


def ingest_viirs(region: str, sensor: str, years: tuple[int, int], token: str, workers: int = 8, log=print) -> int:
    """VIIRS daily L3 via CMR + LP DAAC bearer-token download. Not exercised against live data in this environment."""
    import io

    short, ver = {"N": ("VNP14A1", "002"), "J1": ("VJ114A1", "002"), "J2": ("VJ214A1", "002")}[sensor]
    cfg = region_cfg(region)
    units = load_units(region)
    U = len(districts(units))
    tiles = {t: (unit_index(region, t, units), land_mask(region, t)) for t in tiles_for_bbox(cfg["bbox"])}
    tiles = {t: v for t, v in tiles.items() if (v[0] >= 0).any()}
    sd = state_dir(region) / "coverage_viirs"
    sd.mkdir(exist_ok=True)
    rows = []
    for y in range(years[0], years[1] + 1):
        page = 1
        while True:
            r = http.get("https://cmr.earthdata.nasa.gov/search/granules.json", params={
                "short_name": short, "version": ver, "bounding_box": ",".join(map(str, cfg["bbox"])),
                "temporal": f"{y}-01-01T00:00:00Z,{y}-12-31T23:59:59Z", "page_size": 2000, "page_num": page}).json()
            ents = r["feed"]["entry"]
            if not ents:
                break
            for e in ents:
                href = next((l["href"] for l in e["links"] if l["href"].endswith(".h5") and l["href"].startswith("https://data.")), None)
                m = re.search(r"h(\d\d)v(\d\d)", e["title"])
                if not href or not m or (int(m.group(1)), int(m.group(2))) not in tiles:
                    continue
                rows.append((sensor, e["time_start"][:10], (int(m.group(1)), int(m.group(2))), href))
            page += 1

    def one(row):
        s, d, tile, href = row
        b = http.get(href, headers={"Authorization": f"Bearer {token}"}).content
        fm = viirs_firemask_from_h5(io.BytesIO(b))
        idx, land = tiles[tile]
        clear, cloud, land_px = count_mask(fm, idx, land, U)
        return _rows(s, tile, date.fromisoformat(d), clear, cloud, land_px)

    out, n = [], 0
    with ThreadPoolExecutor(workers) as ex:
        for f in as_completed([ex.submit(one, r) for r in rows]):
            try:
                out.append(f.result())
                n += 1
            except Exception as e:
                log(f"  ! viirs item failed: {e}")
    if out:
        pd.concat(out).to_parquet(sd / f"{sensor}_{years[0]}_{years[1]}.parquet", index=False)
    return n


def load_viirs_coverage(region: str) -> pd.DataFrame:
    d = state_dir(region) / "coverage_viirs"
    parts = sorted(d.glob("*.parquet")) if d.exists() else []
    if not parts:
        return pd.DataFrame(columns=["sat", "date", "unit", "clear", "cloud", "land"])
    df = pd.concat([pd.read_parquet(p) for p in parts]).drop_duplicates(["sat", "tile", "date", "unit"])
    return df.groupby(["sat", "date", "unit"], as_index=False)[["clear", "cloud", "land"]].sum()
