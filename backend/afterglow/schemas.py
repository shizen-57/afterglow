"""JSON Schemas for every published file (backend.md section 8). Structural, not exhaustive: required keys, types and
array nesting depth. Validated in export.py before anything is written to the output folder."""
from __future__ import annotations

NUM = {"type": ["number", "null"]}
INT = {"type": "integer"}
STR = {"type": "string"}


def arr(item, depth=1):
    s = {"type": "array", "items": item}
    for _ in range(depth - 1):
        s = {"type": "array", "items": s}
    return s


def obj(props: dict, required=None, extra=True):
    return {"type": "object", "properties": props, "required": list(props if required is None else required),
            "additionalProperties": extra}


def tag(name):
    return {"const": name}


SENSOR_REC = {"type": "object"}
META = obj({
    "schema": tag("afterglow/meta@1"), "generated_at": STR, "commit": STR,
    "periods": obj({"count": INT, "start_doy": arr(INT)}),
    "sensors": arr(obj({"id": STR, "name": STR, "instrument": STR, "data_start": STR,
                        "planned_end": {"type": ["string", "null"]}, "end_note": {"type": ["string", "null"]},
                        "coverage_source": STR, "window": {"type": ["array", "null"]}})),
    "reference": STR, "bridges": arr({"type": "object"}),
    "combine": obj({"min_cov": {"type": "number"}, "r": {"type": "number"}, "z80": {"type": "number"}, "z95": {"type": "number"}}),
    "verdict": obj({"p_sure": {"type": "number"}, "p_maybe": {"type": "number"}, "q_min": {"type": "number"},
                    "min_baseline_n": INT, "window": INT, "codes": {"type": "object"}}),
    "baselines": arr(STR), "default_baseline": STR, "held_out": arr(INT), "flags": {"type": "object"},
    "regions": arr(obj({"id": STR, "name": STR, "tz": STR, "bbox": arr({"type": "number"}), "centroid": arr({"type": "number"}),
                        "years": arr(INT), "data_through": {"type": "object"},
                        "units": arr(obj({"id": STR, "idx": INT, "name": STR, "adm1": STR, "kind": STR, "area_km2": {"type": "number"},
                                          "centroid": arr({"type": "number"}), "bbox": arr({"type": "number"}),
                                          "stratum": STR, "landcover": {"type": "object"}}))})),
    "sources": arr(obj({"id": STR, "last_success": STR, "ok": {"type": "boolean"}})),
})

S3 = arr(NUM, 3)  # [sensor][unit][period]
U2 = arr(NUM, 2)  # [unit][period]
SNAPSHOT = obj({
    "schema": tag("afterglow/snapshot@1"), "region": STR, "year": INT, "units": arr(STR),
    "comb": obj({"mu": U2, "sigma": U2}), "verdict": arr(INT, 2), "p_hi": U2, "p_lo": U2, "flags": arr(INT, 2),
    "cov": S3, "cloud": U2, "raw": S3, "excl": obj({"static": S3, "lowconf": S3}),
    "per": obj({"mu": S3, "sigma": S3}),
    "base": obj({"q10": U2, "q50": U2, "q90": U2, "max": U2, "n": arr(INT, 2)}),
    "raw_base": obj({"q10": U2, "q90": U2}), "land_km2d": U2, "clear_km2d": S3, "n_passes": arr(INT, 3),
})

SERIES_SENSOR = {"type": "object", "additionalProperties": arr(NUM)}
SERIES = obj({
    "schema": tag("afterglow/series@1"), "unit": STR, "y0": INT, "y1": INT,
    "raw": SERIES_SENSOR, "cov": SERIES_SENSOR, "per_mu": SERIES_SENSOR, "per_sigma": SERIES_SENSOR,
    "comb_mu": arr(NUM), "comb_sigma": arr(NUM), "verdict": arr(INT), "p_hi": arr(NUM), "p_lo": arr(NUM), "flags": arr(INT),
    "excl_static": SERIES_SENSOR, "excl_lowconf": SERIES_SENSOR, "land_km2d": arr(NUM),
    "baseline": {"type": "object"}, "raw_baseline": {"type": "object"},
    "annual": obj({"total": arr(NUM), "lo80": arr(NUM), "hi80": arr(NUM), "rank": arr(NUM), "complete": arr(NUM)}),
    "peak_window": {"type": ["object", "null"]},
})

DETECTIONS = obj({
    "schema": tag("afterglow/detections@1"), "region": STR, "year": INT, "period": INT,
    "lon": arr(NUM), "lat": arr(NUM), "s": arr(INT), "t": arr(INT), "frp": arr(NUM), "c": arr(INT), "x": arr(INT),
    "u": arr(INT), "src": arr(INT)})

DAILY = obj({
    "schema": tag("afterglow/daily@1"), "region": STR, "year": INT, "days": INT, "seen": arr(INT, 3),
    "passes": arr(obj({"d": INT, "s": INT, "t": INT, "n": INT, "u": STR}))})

NRT = obj({"schema": tag("afterglow/nrt@1"), "generated_at": STR, "data_through": {"type": ["string", "null"]},
           "detections": {"type": "object"}, "next_passes": arr({"type": "object"}), "provisional": arr({"type": "object"}),
           "notes": arr(STR)})

VALIDATION = obj({"schema": tag("afterglow/validation@1"), "generated_at": STR, "commit": STR, "h1": {"type": "object"},
                  "verdicts_kept": {"type": "object"}, "warnings": arr(STR)}, extra=True)
PROVENANCE = obj({"schema": tag("afterglow/provenance@1"), "generated_at": STR, "commit": STR,
                  "datasets": arr(obj({"id": STR, "provider": STR, "license": STR, "accessed": STR}, required=["id", "provider", "license", "accessed"]))})
HEALTH = obj({"schema": tag("afterglow/health@1"), "generated_at": STR, "stages": {"type": "object"}, "ok": {"type": "boolean"}})

BY_KIND = {"meta": META, "snapshot": SNAPSHOT, "series": SERIES, "detections": DETECTIONS, "daily": DAILY, "nrt": NRT,
           "validation": VALIDATION, "provenance": PROVENANCE, "health": HEALTH}
