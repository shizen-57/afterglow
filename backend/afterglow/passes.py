"""S5: real overpass times from NASA CMR L2 granule records (MOD14, MYD14, VNP14IMG, VJ114IMG, VJ214IMG).

A pass groups consecutive 6-minute granules of one sensor (gaps <= 12 min). Pass time = midpoint of the earliest granule
that touches a district; units_bits marks which districts any granule of the pass touches.
"""
from __future__ import annotations

import ast
import calendar
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import shapely
from shapely.geometry import Polygon
from shapely.strtree import STRtree

from . import http
from .boundaries import districts, load_units, region_cfg, state_dir
from .config import L2_PRODUCTS, SENSORS, SIDX

CMR = "https://cmr.earthdata.nasa.gov/search/granules.json"
EPOCH = np.datetime64("1970-01-01T00:00")


def parse_polygon(entry: dict):
    """CMR gives 'lat lon lat lon ...' rings. Returns a shapely polygon in (lon, lat) or None."""
    polys = entry.get("polygons")
    if polys:
        try:
            ring = polys[0][0] if isinstance(polys, list) else ast.literal_eval(polys)[0][0]
            v = [float(x) for x in ring.split()]
            pts = [(v[i + 1], v[i]) for i in range(0, len(v) - 1, 2)]
            g = Polygon(pts)
            return g if g.is_valid else g.buffer(0)
        except Exception:
            pass
    boxes = entry.get("boxes")
    if boxes:
        s, w, n, e = [float(x) for x in boxes[0].split()]
        return shapely.box(w, s, e, n)
    return None


def fetch_month(sensor: str, y: int, m: int, bbox) -> list[dict]:
    short, ver = L2_PRODUCTS[sensor]
    last = calendar.monthrange(y, m)[1]
    out, page = [], 1
    while True:
        r = http.get(CMR, params={"short_name": short, "version": ver, "bounding_box": ",".join(map(str, bbox)),
                                  "temporal": f"{y}-{m:02d}-01T00:00:00Z,{y}-{m:02d}-{last}T23:59:59Z",
                                  "page_size": 2000, "page_num": page}).json()
        ents = r["feed"]["entry"]
        out += ents
        if len(ents) < 2000:
            return out
        page += 1


def build_passes(sensor: str, entries: list[dict], tree: STRtree, n_units: int) -> list[dict]:
    gr = []
    for e in entries:
        poly = parse_polygon(e)
        if poly is None:
            continue
        hit = tree.query(poly, predicate="intersects")
        if len(hit) == 0:
            continue
        t0 = np.datetime64(e["time_start"][:16])
        t1 = np.datetime64(e["time_end"][:16])
        gr.append((t0, t1, e.get("day_night_flag", "") == "NIGHT", set(int(i) for i in hit)))
    gr.sort(key=lambda x: x[0])
    passes, cur = [], []
    for g in gr:
        if cur and (g[0] - cur[-1][1]) / np.timedelta64(1, "m") > 12:
            passes.append(cur)
            cur = []
        cur.append(g)
    if cur:
        passes.append(cur)
    out = []
    for p in passes:
        first = p[0]
        mid = first[0] + (first[1] - first[0]) // 2
        bits = 0
        for g in p:
            for i in g[3]:
                bits |= 1 << i
        t = int((mid - EPOCH) // np.timedelta64(1, "m"))
        out.append(dict(s=SIDX[sensor], t=t, night=bool(first[2]), bits=format(bits, "x")))
    return out


def run(region: str, years: tuple[int, int], workers: int = 8):
    cfg = region_cfg(region)
    units = load_units(region)
    dist = districts(units)
    tree = STRtree([u["geom"] for u in dist])
    jobs = []
    for sensor in SENSORS:
        for y in range(years[0], years[1] + 1):
            for m in range(1, 13):
                jobs.append((sensor, y, m))
    rows, empty = [], 0

    def one(j):
        sensor, y, m = j
        return j, fetch_month(sensor, y, m, cfg["bbox"])

    by = {}
    with ThreadPoolExecutor(workers) as ex:
        for k, f in enumerate(as_completed([ex.submit(one, j) for j in jobs]), 1):
            try:
                j, ents = f.result()
            except Exception as e:
                print("  ! CMR month failed:", e)
                continue
            by.setdefault(j[0], []).extend(ents)
            if k % 200 == 0:
                print(f"  CMR {k}/{len(jobs)}", flush=True)
    for sensor, ents in by.items():
        rows += build_passes(sensor, ents, tree, len(dist))
    df = pd.DataFrame(rows, columns=["s", "t", "night", "bits"]).drop_duplicates(["s", "t"]).sort_values(["s", "t"])
    df.to_parquet(state_dir(region) / "passes.parquet", index=False)
    print("  passes per sensor:", df.groupby("s").size().to_dict())
    return df


def load(region: str) -> pd.DataFrame | None:
    p = state_dir(region) / "passes.parquet"
    return pd.read_parquet(p) if p.exists() else None
