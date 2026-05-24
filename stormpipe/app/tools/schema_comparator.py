"""Schema comparison utilities for detecting GHCN-Daily drift."""

import hashlib
import json


KNOWN_GHCN_SCHEMA = [
    {"name": "ID", "field_type": "STRING", "mode": "NULLABLE"},
    {"name": "DATE", "field_type": "STRING", "mode": "NULLABLE"},
    {"name": "ELEMENT", "field_type": "STRING", "mode": "NULLABLE"},
    {"name": "DATA_VALUE", "field_type": "INTEGER", "mode": "NULLABLE"},
    {"name": "M_FLAG", "field_type": "STRING", "mode": "NULLABLE"},
    {"name": "Q_FLAG", "field_type": "STRING", "mode": "NULLABLE"},
    {"name": "S_FLAG", "field_type": "STRING", "mode": "NULLABLE"},
    {"name": "OBS_TIME", "field_type": "STRING", "mode": "NULLABLE"},
]

QUALITY_FLAGS = {
    "D": "failed duplicate check",
    "G": "failed gap check",
    "I": "failed internal consistency check",
    "K": "failed streak/frequent-value check",
    "M": "failed mega-consistency check",
    "N": "failed naught check",
    "O": "failed climatological outlier check",
    "R": "failed lagged range check",
    "S": "failed spatial consistency check",
    "T": "failed temporal consistency check",
    "W": "temperature too warm for snow",
    "X": "failed bounds check",
    "Z": "flagged as a result of an official Datzilla investigation",
}

MEASUREMENT_FLAGS = {
    "B": "precipitation total formed from two 12-hour totals",
    "D": "precipitation total formed from four 6-hour totals",
    "H": "represents highest or lowest hourly temperature",
    "K": "converted from knots",
    "L": "temperature appears to be lagged with respect to reported hour",
    "O": "converted from oktas",
    "P": "identified as missing presumed zero in DSI 3200 and 3206",
    "T": "trace of precipitation, snowfall, or snow depth",
    "W": "converted from 16-point WBAN code",
}

ELEMENT_UNITS = {
    "TMAX": ("tenths of degrees C", 10.0, "°C"),
    "TMIN": ("tenths of degrees C", 10.0, "°C"),
    "TAVG": ("tenths of degrees C", 10.0, "°C"),
    "PRCP": ("tenths of mm", 10.0, "mm"),
    "SNOW": ("mm", 1.0, "mm"),
    "SNWD": ("mm", 1.0, "mm"),
    "AWND": ("tenths of meters per second", 10.0, "m/s"),
    "PGTM": ("HHMM", 1.0, "HHMM"),
    "WSFG": ("tenths of meters per second", 10.0, "m/s"),
    "WESD": ("tenths of mm", 10.0, "mm"),
    "WESF": ("tenths of mm", 10.0, "mm"),
}

MISSING_VALUE_SENTINEL = -9999


def schema_fingerprint(schema: list[dict]) -> str:
    """SHA-256 fingerprint of a schema for change detection."""
    canonical = sorted(schema, key=lambda x: x["name"])
    return hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()[:16]


def compare_schemas(current: list[dict], expected: list[dict]) -> dict:
    """Diff two schemas, classify each change.

    Args:
        current: Schema from BigQuery INFORMATION_SCHEMA.
        expected: Expected/baseline schema.

    Returns:
        Dict with added, removed, type_changed, and summary.
    """
    curr_map = {c["name"]: c for c in current}
    exp_map = {c["name"]: c for c in expected}

    added = [c for name, c in curr_map.items() if name not in exp_map]
    removed = [c for name, c in exp_map.items() if name not in curr_map]
    type_changed = [
        {
            "name": name,
            "old_type": exp_map[name]["field_type"],
            "new_type": curr_map[name]["field_type"],
        }
        for name in curr_map
        if name in exp_map and curr_map[name]["field_type"] != exp_map[name]["field_type"]
    ]

    changes = []
    for col in added:
        changes.append({"column": col["name"], "change_type": "ADDITIVE", "recommendation": "ACCEPT"})
    for col in removed:
        changes.append({"column": col["name"], "change_type": "DESTRUCTIVE", "recommendation": "ALERT_OPERATOR"})
    for col in type_changed:
        changes.append({"column": col["name"], "change_type": "TYPE_CHANGE", "recommendation": "QUARANTINE"})

    return {
        "added": added,
        "removed": removed,
        "type_changed": type_changed,
        "changes": changes,
        "fingerprint_current": schema_fingerprint(current),
        "fingerprint_expected": schema_fingerprint(expected),
        "drift_detected": bool(added or removed or type_changed),
    }
