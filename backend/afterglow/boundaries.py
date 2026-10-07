"""S1: administrative boundaries (geoBoundaries gbOpen) -> units.json + geometry helpers."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import shapely
import yaml
from pyproj import Geod
from shapely.geometry import mapping, shape
from shapely.ops import unary_union
from shapely.strtree import STRtree

from . import http
from .config import CACHE, REGIONS_YAML, STATE

GEOD = Geod(ellps="WGS84")


def region_cfg(region: str) -> dict:
    cfg = yaml.safe_load(REGIONS_YAML.read_text(encoding="utf-8"))["regions"][region]
    cfg["id"] = region
    return cfg


def state_dir(region: str) -> Path:
    d = STATE / region
    d.mkdir(parents=True, exist_ok=True)
    return d


def _fetch_adm(iso3: str, level: int) -> dict:
    meta = http.get(f"https://www.geoboundaries.org/api/current/gbOpen/{iso3}/ADM{level}/").json()
    path = CACHE / "boundaries" / f"{iso3}_ADM{level}.geojson"
    http.download(meta["simplifiedGeometryGeoJSON"], path)
    return {"meta": meta, "geojson": json.loads(path.read_text(encoding="utf-8"))}


def _area_km2(geom) -> float:
    polys = [geom] if geom.geom_type == "Polygon" else list(geom.geoms)
    return float(sum(abs(GEOD.geometry_area_perimeter(p)[0]) for p in polys) / 1e6)


def build_units(region: str) -> list[dict]:
    cfg = region_cfg(region)
    iso3 = cfg["iso3"]
    adm_u = _fetch_adm(iso3, cfg["adm_unit_level"])
    adm_p = _fetch_adm(iso3, cfg["adm_parent_level"])
    parents = [(f["properties"]["shapeName"], shape(f["geometry"]).buffer(0)) for f in adm_p["geojson"]["features"]]
    units = []
    for f in adm_u["geojson"]["features"]:
        g = shape(f["geometry"]).buffer(0)
        best = max(parents, key=lambda p: g.intersection(p[1]).area)
        units.append(dict(id=f"{iso3}-ADM{cfg['adm_unit_level']}-{f['properties']['shapeID']}",
                          name=f["properties"]["shapeName"], adm1=best[0], kind="district", geom=g))
    units.sort(key=lambda u: (u["adm1"], u["name"]))
    country = unary_union([u["geom"] for u in units])
    units.append(dict(id=iso3, name=cfg["name"], adm1=cfg["name"], kind="country", geom=country))
    out = []
    for i, u in enumerate(units):
        b = u["geom"].bounds
        c = u["geom"].representative_point() if u["kind"] == "country" else u["geom"].centroid
        out.append(dict(idx=i, id=u["id"], name=u["name"], adm1=u["adm1"], kind=u["kind"],
                        area_km2=round(_area_km2(u["geom"]), 1), centroid=[round(c.x, 4), round(c.y, 4)],
                        bbox=[round(x, 4) for x in b], wkt=u["geom"].wkt))
    lic = adm_u["meta"].get("boundaryLicense")
    (state_dir(region) / "units.json").write_text(json.dumps(dict(
        units=out, source=dict(name="geoBoundaries gbOpen", license=lic, build_date=adm_u["meta"].get("buildDate"),
                               source=adm_u["meta"].get("boundarySource"), unit_count=adm_u["meta"].get("admUnitCount"),
                               url=adm_u["meta"].get("gjDownloadURL"))), ensure_ascii=False), encoding="utf-8")
    return out


def load_units(region: str) -> list[dict]:
    p = state_dir(region) / "units.json"
    if not p.exists():
        build_units(region)
    d = json.loads(p.read_text(encoding="utf-8"))
    for u in d["units"]:
        u["geom"] = shapely.from_wkt(u["wkt"])
    return d["units"]


def load_units_source(region: str) -> dict:
    return json.loads((state_dir(region) / "units.json").read_text(encoding="utf-8"))["source"]


def districts(units: list[dict]) -> list[dict]:
    return [u for u in units if u["kind"] == "district"]


def assign_points(units: list[dict], lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    """District index per point (-1 outside). One STRtree query for all points."""
    geoms = [u["geom"] for u in districts(units)]
    tree = STRtree(geoms)
    pts = shapely.points(lon, lat)
    pi, gi = tree.query(pts, predicate="within")
    out = np.full(len(lon), -1, dtype=np.int16)
    out[pi[::-1]] = gi[::-1].astype(np.int16)  # first match wins on duplicates
    return out


def geojson_export(units: list[dict], tol: float = 0.004) -> dict:
    feats = []
    for u in units:
        g = shapely.simplify(u["geom"], tol)
        g = shapely.set_precision(g, 0.0001)
        if g.is_empty:
            g = u["geom"]
        feats.append(dict(type="Feature", geometry=mapping(g),
                          properties=dict(id=u["id"], idx=u["idx"], name=u["name"], adm1=u["adm1"], kind=u["kind"])))
    return dict(type="FeatureCollection", features=feats)
