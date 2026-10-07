"""S9: export the static JSON API (backend.md section 8). Every file is schema-validated and gate-checked first."""
from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
from jsonschema import Draft202012Validator

from . import aggregate, landcover, passes as passes_mod, science
from .boundaries import districts, geojson_export, load_units, load_units_source, region_cfg, state_dir
from .config import (BASELINES, DEFAULT_BASELINE, F_CALIB, F_COV_PROXY, F_HELD_OUT, F_PARTIAL, F_PROVISIONAL,
                     F_COV_PENDING, HELD_OUT_FROM, MIN_BASELINE_N, MIN_COV, OUT, P, P_MAYBE, P_SURE, Q_MIN, S,
                     SENSORS, SENSOR_INFO, SIDX, START_DOY, VERDICT_CODES, Z80, Z95)
from .schemas import BY_KIND

EPOCH = pd.Timestamp("1970-01-01")


class GateError(RuntimeError):
    pass


def jl(a, nd=3):
    """ndarray -> nested list; NaN/inf -> None; floats rounded."""
    a = np.asarray(a, dtype=np.float64)
    out = np.round(a, nd).astype(object)
    out[~np.isfinite(a)] = None
    return out.tolist()


def il(a):
    return np.asarray(a).astype(np.int64).tolist()


def ilnull(a):
    a = np.asarray(a, dtype=np.float64)
    out = np.where(np.isfinite(a), a, 0).astype(np.int64).astype(object)
    out[~np.isfinite(a)] = None
    return out.tolist()


def commit_hash() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              cwd=Path(__file__).resolve().parents[1]).stdout.strip() or "uncommitted"
    except Exception:
        return "uncommitted"


def write(path: Path, kind: str, obj: dict, validate: bool = True):
    if validate:
        errs = sorted(Draft202012Validator(BY_KIND[kind]).iter_errors(obj), key=lambda e: list(e.path))
        if errs:
            e = errs[0]
            raise GateError(f"{kind} schema violation at {'/'.join(map(str, e.path))}: {e.message[:200]}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, separators=(",", ":"), allow_nan=False, ensure_ascii=False), encoding="utf-8")


def run(region: str, out_dir: str | None = None):
    out = Path(out_dir) if out_dir else OUT
    cfg = region_cfg(region)
    A, pmeta = aggregate.load(region)
    Z, smeta = science.load(region)
    units = load_units(region)
    U = len(districts(units))
    y0, y1 = pmeta["years"]
    Y = y1 - y0 + 1
    years = y0 + np.arange(Y)
    lc = landcover.load(region)
    gen = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    commit = commit_hash()
    dflt = DEFAULT_BASELINE
    sd = state_dir(region)
    dmeta = json.loads((sd / "detections_meta.json").read_text())
    pdf = passes_mod.load(region)

    # verdict: -1 when no sensor had any data for the period, 0 when sensors existed but none could see the ground
    code = Z["code"].astype(np.int16).copy()
    code[~A["active"].any(0)] = -1
    judged_ = (code >= 1) & (code <= 6)
    nd = int(np.isfinite(Z["mu_c"]).sum())

    # ---------------- gates (before anything is written)
    bad = []
    cov = A["cov"]
    if np.nanmax(cov) > 1.0001 or np.nanmin(cov) < -1e-6:
        bad.append(f"coverage outside [0,1]: min={np.nanmin(cov)}, max={np.nanmax(cov)}")
    for nm in ("p_hi", "p_lo"):
        v = Z[nm][np.isfinite(Z[nm])]
        if len(v) and (v.min() < -1e-9 or v.max() > 1 + 1e-9):
            bad.append(f"{nm} outside [0,1]")
    if not set(np.unique(code)).issubset(set(VERDICT_CODES.values())):
        bad.append("verdict codes out of range")
    if nd == 0:
        bad.append("no harmonized estimates at all")
    # reconciliation of detections: kept+static+lowconf per sensor-year vs rows loaded (dedupe/offshore drops only)
    rec = dmeta.get("reconciliation", {})
    for key, f in rec.items():
        if f["dropped_frac"] > 0.15:
            bad.append(f"detections reconciliation {key}: {f['dropped_frac']:.1%} rows dropped (offshore/dedupe)")
    if bad:
        raise GateError("; ".join(bad))

    # ---------------- geo
    geo = geojson_export(units)
    (out / "geo").mkdir(parents=True, exist_ok=True)
    (out / "geo" / f"{region}.geojson").write_text(json.dumps(geo, separators=(",", ":")), encoding="utf-8")

    # ---------------- meta
    vm = json.loads((sd / "periods_meta.json").read_text())
    sensors = []
    for s in SENSORS:
        inf = SENSOR_INFO[s]
        sensors.append(dict(id=s, name=inf["name"], instrument=inf["instrument"], data_start=inf["data_start"],
                            planned_end=inf["planned_end"], end_note=inf["end_note"],
                            coverage_source=vm["cov_src"].get(s, "none"), window=vm["windows"].get(s)))
    last_sp = {k: v for k, v in dmeta["series_end"].items()}
    src_unit = load_units_source(region)
    unit_meta = []
    for u in units:
        info = lc["units"].get(u["id"], {})
        unit_meta.append(dict(id=u["id"], idx=u["idx"], name=u["name"], adm1=u["adm1"], kind=u["kind"], area_km2=u["area_km2"],
                              centroid=u["centroid"], bbox=u["bbox"], stratum=info.get("stratum", "other"),
                              landcover=info.get("landcover", {})))
    meta = dict(schema="afterglow/meta@1", generated_at=gen, commit=commit,
                periods=dict(count=P, start_doy=START_DOY), sensors=sensors, reference="A",
                bridges=smeta["bridges"],
                combine=dict(min_cov=MIN_COV, r=smeta["r"], z80=Z80, z95=Z95),
                verdict=dict(p_sure=P_SURE, p_maybe=P_MAYBE, q_min=Q_MIN, min_baseline_n=MIN_BASELINE_N, window=1,
                             codes=VERDICT_CODES),
                baselines=list(BASELINES), default_baseline=dflt, held_out=[HELD_OUT_FROM, int(y1)],
                flags=dict(provisional=F_PROVISIONAL, held_out=F_HELD_OUT, used_for_calibration=F_CALIB, partial_period=F_PARTIAL,
                           coverage_pending=F_COV_PENDING, coverage_proxy=F_COV_PROXY),
                regions=[dict(id=region, name=cfg["name"], tz=cfg["tz"], bbox=cfg["bbox"],
                              centroid=[round((cfg["bbox"][0] + cfg["bbox"][2]) / 2, 3), round((cfg["bbox"][1] + cfg["bbox"][3]) / 2, 3)],
                              years=[y0, y1], data_through=dict(sp=max(last_sp.values()) if last_sp else None, nrt=None,
                                                                 per_sensor=last_sp, l3={s: (vm["windows"].get(s) or [None, None])[1] for s in SENSORS}),
                              units=unit_meta)],
                sources=[dict(id="firms_country", last_success=gen, ok=True), dict(id="pc_modis_l3", last_success=gen, ok=True),
                         dict(id="cmr_passes", last_success=gen, ok=bool(vm.get("passes_available"))),
                         dict(id="geoboundaries", last_success=gen, ok=True)],
                notes=["Heights/verdicts are harmonized to the Aqua MODIS scale (detections per 1,000 clear-view km2-days).",
                       "coverage_source 'proxy_A' means that VIIRS clear-view coverage is copied from same-day Aqua MODIS.",
                       "Detections after the last published FIRMS yearly file are absent until a FIRMS MAP_KEY run."])
    write(out / "meta.json", "meta", meta)

    # ---------------- snapshots
    clear = A["clear"]
    land = A["land"]
    cloud_share = np.nanmean(np.where(A["active"], A["cloud"] / np.where(land[None] > 0, land[None], np.nan), np.nan), axis=0)
    snap_sizes = []
    for k, y in enumerate(years):
        sl = lambda a: a[..., k, :]  # noqa: E731
        s3 = lambda a, nd=3: [[jl(a[s, u, k], nd) for u in range(U + 1)] for s in range(S)]  # noqa: E731
        snap = dict(schema="afterglow/snapshot@1", region=region, year=int(y), units=[u["id"] for u in units],
                    comb=dict(mu=jl(sl(Z["mu_c"])), sigma=jl(sl(Z["sg_c"]))),
                    verdict=il(sl(code)), p_hi=jl(sl(Z["p_hi"])), p_lo=jl(sl(Z["p_lo"])), flags=il(sl(Z["flags"])),
                    cov=s3(A["cov"], 2), cloud=jl(sl(cloud_share), 2),
                    raw=[[ilnull(A["D"][s, u, k]) for u in range(U + 1)] for s in range(S)],
                    excl=dict(static=[[ilnull(A["ex_static"][s, u, k]) for u in range(U + 1)] for s in range(S)],
                              lowconf=[[ilnull(A["ex_low"][s, u, k]) for u in range(U + 1)] for s in range(S)]),
                    per=dict(mu=s3(Z["per_mu"]), sigma=s3(Z["per_sg"])),
                    base=dict(q10=jl(Z[f"base_{dflt}_q10"][:, k]), q50=jl(Z[f"base_{dflt}_q50"][:, k]),
                              q90=jl(Z[f"base_{dflt}_q90"][:, k]), max=jl(Z[f"base_{dflt}_max"][:, k]),
                              n=il(Z[f"base_{dflt}_n"][:, k])),
                    raw_base=dict(q10=jl(Z[f"rbase_{dflt}_q10"][:, k], 1), q90=jl(Z[f"rbase_{dflt}_q90"][:, k], 1)),
                    land_km2d=jl(land[:, k], 0), clear_km2d=s3(clear, 0), n_passes=il(A["n_passes"][:, :, k]))
        p = out / "snapshots" / region / f"{int(y)}.json"
        write(p, "snapshot", snap)
        snap_sizes.append(p.stat().st_size)

    # ---------------- series
    flat = lambda a: a.reshape(a.shape[:-2] + (Y * P,))  # noqa: E731
    for u in units:
        i = u["idx"]
        per_s = lambda arr_, nd=3: {s: jl(flat(arr_[SIDX[s], i]), nd) for s in SENSORS}  # noqa: E731
        series = dict(schema="afterglow/series@1", unit=u["id"], y0=int(y0), y1=int(y1),
                      raw={s: ilnull(flat(A["D"][SIDX[s], i])) for s in SENSORS}, cov=per_s(A["cov"], 2),
                      per_mu=per_s(Z["per_mu"]), per_sigma=per_s(Z["per_sg"]),
                      comb_mu=jl(flat(Z["mu_c"][i])), comb_sigma=jl(flat(Z["sg_c"][i])),
                      verdict=il(flat(code[i])), p_hi=jl(flat(Z["p_hi"][i])), p_lo=jl(flat(Z["p_lo"][i])), flags=il(flat(Z["flags"][i])),
                      excl_static={s: ilnull(flat(A["ex_static"][SIDX[s], i])) for s in SENSORS},
                      excl_lowconf={s: ilnull(flat(A["ex_low"][SIDX[s], i])) for s in SENSORS},
                      land_km2d=jl(flat(land[i]), 0),
                      baseline={b: dict(q10=jl(Z[f"baseall_{b}_q10"][i]), q50=jl(Z[f"baseall_{b}_q50"][i]),
                                        q90=jl(Z[f"baseall_{b}_q90"][i]), max=jl(Z[f"baseall_{b}_max"][i]),
                                        n=il(Z[f"baseall_{b}_n"][i])) for b in BASELINES},
                      raw_baseline={b: dict(q10=jl(Z[f"rbaseall_{b}_q10"][i], 1), q90=jl(Z[f"rbaseall_{b}_q90"][i], 1)) for b in BASELINES},
                      annual=dict(total=jl(Z["total"][i], 1), lo80=jl(Z["lo80"][i], 1), hi80=jl(Z["hi80"][i], 1),
                                  rank=ilnull(Z["rank"][i]), complete=jl(Z["complete"][i])),
                      peak_window=None if Z["peak"][i][0] < 0 else dict(start_p=int(Z["peak"][i][0]), end_p=int(Z["peak"][i][1])))
        write(out / "series" / f"{u['id']}.json", "series", series)

    # ---------------- detections per period + daily
    det = pd.read_parquet(sd / "detections.parquet")
    ts = EPOCH + pd.to_timedelta(det["t"].values, unit="m")
    det["year"] = ts.year.values
    det["p"] = np.minimum(P, (ts.dayofyear.values - 1) // 8 + 1)
    n_det_files = 0
    for (y, p), g in det.groupby(["year", "p"]):
        obj = dict(schema="afterglow/detections@1", region=region, year=int(y), period=int(p),
                   lon=g["lon"].round(4).tolist(), lat=g["lat"].round(4).tolist(), s=g["s"].astype(int).tolist(),
                   t=g["t"].astype(int).tolist(), frp=g["frp"].round(1).tolist(), c=g["conf"].astype(int).tolist(),
                   x=g["x"].astype(int).tolist(), u=g["unit"].astype(int).tolist(), src=g["src"].astype(int).tolist())
        write(out / "detections" / region / str(int(y)) / f"{int(p):02d}.json", "detections", obj)
        n_det_files += 1
    if pdf is not None:
        t = EPOCH + pd.to_timedelta(pdf["t"].values, unit="m")
        pdf = pdf.assign(year=t.year.values, doy=t.dayofyear.values, mod=(t.hour * 60 + t.minute).values)
    for k, y in enumerate(years):
        ndays = 366 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 365
        seen = [[il(A["seen"][s, k, d]) for d in range(ndays)] for s in range(S)]
        passes = []
        if pdf is not None:
            g = pdf[pdf.year == y]
            passes = [dict(d=int(r.doy) - 1, s=int(r.s), t=int(r.mod), n=int(r.night), u=r.bits) for r in g.itertuples()]
        write(out / "daily" / region / f"{int(y)}.json", "daily",
              dict(schema="afterglow/daily@1", region=region, year=int(y), days=ndays, seen=seen, passes=passes))

    # ---------------- validation, provenance, health, nrt passthrough
    vp = sd / "validation.json"
    if vp.exists():
        write(out / "validation.json", "validation", json.loads(vp.read_text(encoding="utf-8")))
    prov = provenance(region, dmeta, pmeta, smeta, src_unit, lc, gen, commit)
    write(out / "provenance.json", "provenance", prov)
    write(out / "health.json", "health", dict(schema="afterglow/health@1", generated_at=gen, ok=True,
                                              stages={k: dict(ok=True, at=gen) for k in ("detections", "coverage", "passes", "science", "export")}))
    nrt = sd / "nrt.json"
    if nrt.exists():
        write(out / "nrt" / f"{region}.json", "nrt", json.loads(nrt.read_text(encoding="utf-8")))
    sizes = {"snapshot_max_kb": round(max(snap_sizes) / 1024, 1), "snapshot_mean_kb": round(np.mean(snap_sizes) / 1024, 1)}
    print(f"  exported to {out}  (snapshots {len(snap_sizes)}, series {len(units)}, detection files {n_det_files}); raw sizes: {sizes}")
    print(f"  harmonized cells: {nd:,}; judged: {int(judged_.sum()):,}")


def provenance(region, dmeta, pmeta, smeta, src_unit, lc, gen, commit) -> dict:
    today = gen[:10]
    ds = [
        dict(id="firms_country", short_name="MCD14ML / VNP14IMGML / VJ114IMGML yearly country files (FIRMS standard processing)",
             version="MODIS C6.1; VIIRS C2", provider="NASA FIRMS / LANCE", license="NASA open data",
             url="https://firms.modaps.eosdis.nasa.gov/country/", citation="NASA FIRMS (LANCE). doi:10.5067/FIRMS/MODIS/MCD14DL.NRT.0061; doi:10.5067/FIRMS/VIIRS/VNP14IMGT.NRT.002",
             temporal=str(dmeta["available_years"]), rows=dmeta["rows"], accessed=today),
        dict(id="modis_l3", short_name="MOD14A1 / MYD14A1 daily fire masks (COG copies)", version="061",
             provider="NASA LP DAAC via Microsoft Planetary Computer", license="NASA open data",
             url="https://planetarycomputer.microsoft.com/dataset/modis-14A1-061",
             citation="Giglio, L., Justice, C. MOD14A1/MYD14A1 v061. NASA LP DAAC. doi:10.5067/MODIS/MOD14A1.061; doi:10.5067/MODIS/MYD14A1.061",
             temporal="2000-2026", accessed=today),
        dict(id="viirs_l3", short_name="VNP14A1 / VJ114A1 / VJ214A1 daily fire masks", version="002", provider="NASA LP DAAC",
             license="NASA open data", url="https://www.earthdata.nasa.gov/data/catalog/lpcloud-vnp14a1-002",
             citation="NASA LP DAAC VIIRS thermal anomalies and fire daily L3 v002",
             temporal="not ingested in this build" if pmeta["cov_src"].get("N") != "native" else "ingested", accessed=today),
        dict(id="cmr_passes", short_name="L2 granule records MOD14, MYD14, VNP14IMG, VJ114IMG, VJ214IMG", version="061/002",
             provider="NASA CMR", license="NASA metadata", url="https://cmr.earthdata.nasa.gov/search/", citation="NASA Common Metadata Repository",
             temporal="2001-2026", accessed=today),
        dict(id="geoboundaries", short_name="geoBoundaries gbOpen ADM1/ADM2", version=str(src_unit.get("build_date")),
             provider="geoBoundaries / " + str(src_unit.get("source")), license=str(src_unit.get("license")),
             url="https://www.geoboundaries.org/", citation="Runfola et al. (2020) geoBoundaries. PLoS ONE 15(4): e0231866", accessed=today),
        dict(id="worldcover", short_name="ESA WorldCover 10 m", version="2021 v200", provider="ESA", license="CC BY 4.0",
             url="https://esa-worldcover.org/", citation="Zanaga et al. (2022) ESA WorldCover 10 m 2021 v200. doi:10.5281/zenodo.7254221",
             temporal="2021", available=bool(lc.get("available")), accessed=today),
    ]
    return dict(schema="afterglow/provenance@1", generated_at=gen, commit=commit, region=region, datasets=ds,
                coverage_source=pmeta["cov_src"], static_cells=dmeta["static_cells"], bootstrap_B=smeta["bootstrap_B"],
                notes=["Terrain tiles (if present) are listed in terrain provenance written by the terrain stage."])
