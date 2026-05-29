"""Schema comparison utilities for detecting GHCN-Daily drift."""

import hashlib
import json
import re

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

CANONICAL_COLUMNS = [c["name"] for c in KNOWN_GHCN_SCHEMA]

# Fivetran-injected metadata — always expected, never a misparse signal.
FIVETRAN_META_COLUMNS = {
    "_file",
    "_line",
    "_modified",
    "_fivetran_synced",
    "_fivetran_id",
    "_fivetran_deleted",
}

# GHCN element codes (lowercased) used to spot an element value masquerading as a column name.
GHCN_ELEMENT_NAMES = {
    "tmax", "tmin", "tavg", "tobs", "prcp", "snow", "snwd", "wesd", "wesf",
    "awnd", "wsf2", "wsf5", "wsfg", "wdf2", "wdf5", "wdfg", "pgtm", "evap",
    "mnpn", "mxpn", "dapr", "mdpr", "thic", "wdmv", "rhmx", "rhmn", "rhav",
    "awbt", "adpt", "aslp", "astp", "frgt", "frth", "psun", "tsun",
}

# A date value that became a column name, e.g. "_20210101".
_DATE_COL_RE = re.compile(r"^_?(19|20)\d{6}$")
# A bare integer reading that became a column name, e.g. "_278", "_-12".
_VALUE_COL_RE = re.compile(r"^_-?\d{1,5}$")
# A station id that became a column name, e.g. "ae_000041196" <- AE000041196.
_STATION_COL_RE = re.compile(r"^[a-z]{2}_?[a-z0-9]*\d{5,}$")


def _classify_misparsed_column(name: str) -> str | None:
    """Map a single mangled column name to the canonical role it actually holds.

    Returns one of ID / DATE / ELEMENT / DATA_VALUE / FLAG, or None if the name
    looks like a legitimate canonical/metadata column.
    """
    if name in CANONICAL_COLUMNS or name in FIVETRAN_META_COLUMNS:
        return None
    if _DATE_COL_RE.match(name):
        return "DATE"
    if name.lower() in GHCN_ELEMENT_NAMES:
        return "ELEMENT"
    if _STATION_COL_RE.match(name):
        return "ID"
    if _VALUE_COL_RE.match(name):
        return "DATA_VALUE"
    if len(name) == 1:
        return "FLAG"
    return None


def _col_name(c) -> str:
    """Extract a column name from a schema item regardless of its shape.

    These functions are exposed as agent tools, and the model sometimes supplies
    column descriptors keyed differently than BigQuery's `name` (e.g.
    `column_name`, or a bare string). Be tolerant so a stray arg shape can't
    crash the tool with KeyError.
    """
    if isinstance(c, str):
        return c
    if isinstance(c, dict):
        for k in ("name", "column_name", "field", "field_path", "column"):
            v = c.get(k)
            if v:
                return str(v)
        return json.dumps(c, sort_keys=True)
    return str(c)


def detect_header_as_data_misparse(schema: list[dict]) -> dict:
    """Detect the 'first data row consumed as CSV header' pathology.

    When a headerless CSV is loaded with header-detection enabled, each source
    file's first row of *values* becomes column *names*. A union across files then
    scatters one logical field across many per-file columns (e.g. a DATE column
    per year). This detects that signature and proposes a reconstruction mapping.

    Args:
        schema: Current BigQuery schema (list of column descriptors).

    Returns:
        Diagnosis dict with misparse_detected, pathology, role_columns,
        lost_columns, confidence, and a human-readable diagnosis.
    """
    names = [_col_name(c) for c in schema]
    roles: dict[str, list[str]] = {"ID": [], "DATE": [], "ELEMENT": [], "DATA_VALUE": [], "FLAG": []}
    for n in names:
        role = _classify_misparsed_column(n)
        if role:
            roles[role].append(n)

    canonical_present = [n for n in names if n in CANONICAL_COLUMNS]
    # Misparse signature: core canonical columns absent AND their values appear as column names.
    core_missing = {"ID", "DATE", "ELEMENT", "DATA_VALUE"} - set(canonical_present)
    data_as_header = sum(len(roles[r]) for r in ("ID", "DATE", "ELEMENT", "DATA_VALUE"))
    misparse = bool(core_missing) and data_as_header >= 3

    # Canonical fields with no recoverable source column are lost in the misparse.
    recoverable = set()
    if roles["ID"]:
        recoverable.add("ID")
    if roles["DATE"]:
        recoverable.add("DATE")
    if roles["ELEMENT"]:
        recoverable.add("ELEMENT")
    if roles["DATA_VALUE"]:
        recoverable.add("DATA_VALUE")
    # Flags are recoverable only as ambiguous candidates; Q_FLAG/OBS_TIME usually lost.
    lost = [c for c in CANONICAL_COLUMNS if c not in recoverable and c not in {"M_FLAG", "Q_FLAG", "S_FLAG", "OBS_TIME"}]
    if misparse:
        # Flag columns are too few to cover M/Q/S/OBS_TIME -> mark the uncovered ones lost.
        n_flags = len(roles["FLAG"])
        flag_targets = ["M_FLAG", "S_FLAG", "Q_FLAG", "OBS_TIME"]
        lost += flag_targets[n_flags:]

    confidence = 0.0
    if misparse:
        confidence = min(0.99, 0.6 + 0.1 * data_as_header)

    return {
        "misparse_detected": misparse,
        "pathology": "HEADER_AS_DATA" if misparse else None,
        "diagnosis": (
            "First data row consumed as CSV header: source files are headerless but were "
            "loaded with header-detection enabled (empty_header=false). Each file's first-row "
            "values became column names, and the multi-file union scattered each logical field "
            "across per-file columns."
            if misparse
            else "No header-as-data misparse signature found."
        ),
        "role_columns": roles,
        "recoverable_columns": sorted(recoverable),
        "lost_columns": sorted(set(lost)),
        "confidence": round(confidence, 2),
        "remediation": (
            "Reconstruct canonical schema in-warehouse via COALESCE of per-file columns, "
            "then fix the source connector (treat files as headerless) and re-sync to recover "
            "fields lost in the misparse (e.g. Q_FLAG, OBS_TIME)."
            if misparse
            else "None required."
        ),
    }


def build_reconstruction_mapping(schema: list[dict]) -> dict:
    """Build SQL expressions that rebuild canonical GHCN columns from a misparsed schema.

    Args:
        schema: Current (misparsed) BigQuery schema.

    Returns:
        Dict mapping each canonical column to a BigQuery SQL expression. Unambiguous
        fields (ID/DATE/ELEMENT/DATA_VALUE) get COALESCE expressions; ambiguous flag
        columns are returned under 'flag_candidates' for data-driven assignment.
    """
    diag = detect_header_as_data_misparse(schema)
    roles = diag["role_columns"]

    def _coalesce(cols: list[str]) -> str:
        ordered = sorted(cols)
        if not ordered:
            return "CAST(NULL AS STRING)"
        if len(ordered) == 1:
            return f"`{ordered[0]}`"
        return "COALESCE(" + ", ".join(f"`{c}`" for c in ordered) + ")"

    return {
        "misparse_detected": diag["misparse_detected"],
        "ID": _coalesce(roles["ID"]),
        "DATE": f"CAST({_coalesce(roles['DATE'])} AS STRING)",
        "ELEMENT": _coalesce(roles["ELEMENT"]),
        "DATA_VALUE": _coalesce(roles["DATA_VALUE"]),
        "flag_candidates": sorted(roles["FLAG"]),
        "lost_columns": diag["lost_columns"],
    }


def schema_fingerprint(schema: list[dict]) -> str:
    """SHA-256 fingerprint of a schema for change detection."""
    canonical = sorted(schema, key=_col_name)
    return hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()[:16]


def compare_schemas(current: list[dict], expected: list[dict]) -> dict:
    """Diff two schemas, classify each change.

    Args:
        current: Schema from BigQuery INFORMATION_SCHEMA.
        expected: Expected/baseline schema.

    Returns:
        Dict with added, removed, type_changed, and summary.
    """
    curr_map = {_col_name(c): c for c in current}
    exp_map = {_col_name(c): c for c in expected}

    def _ftype(c) -> str:
        return str(c.get("field_type", "")) if isinstance(c, dict) else ""

    added_names = [name for name in curr_map if name not in exp_map]
    removed_names = [name for name in exp_map if name not in curr_map]
    type_changed = [
        {
            "name": name,
            "old_type": _ftype(exp_map[name]),
            "new_type": _ftype(curr_map[name]),
        }
        for name in curr_map
        if name in exp_map and _ftype(curr_map[name]) != _ftype(exp_map[name])
    ]

    added = [curr_map[name] for name in added_names]
    removed = [exp_map[name] for name in removed_names]

    changes = []
    for name in added_names:
        changes.append({"column": name, "change_type": "ADDITIVE", "recommendation": "ACCEPT"})
    for name in removed_names:
        changes.append({"column": name, "change_type": "DESTRUCTIVE", "recommendation": "ALERT_OPERATOR"})
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
