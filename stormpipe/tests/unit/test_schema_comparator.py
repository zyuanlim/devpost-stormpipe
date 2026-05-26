"""Unit tests for GHCN schema drift + header-as-data misparse detection."""

from app.tools.schema_comparator import (
    KNOWN_GHCN_SCHEMA,
    build_reconstruction_mapping,
    compare_schemas,
    detect_header_as_data_misparse,
    schema_fingerprint,
)

# The actual mangled schema produced by Fivetran misparsing the headerless GHCN CSV.
MISPARSED_SCHEMA = [
    {"name": "_file", "field_type": "STRING", "mode": "NULLABLE"},
    {"name": "_line", "field_type": "INTEGER", "mode": "NULLABLE"},
    {"name": "_modified", "field_type": "TIMESTAMP", "mode": "NULLABLE"},
    {"name": "_fivetran_synced", "field_type": "TIMESTAMP", "mode": "NULLABLE"},
    {"name": "ae_000041196", "field_type": "STRING", "mode": "NULLABLE"},
    {"name": "_20210101", "field_type": "INTEGER", "mode": "NULLABLE"},
    {"name": "tmax", "field_type": "STRING", "mode": "NULLABLE"},
    {"name": "_278", "field_type": "INTEGER", "mode": "NULLABLE"},
    {"name": "s", "field_type": "STRING", "mode": "NULLABLE"},
    {"name": "_20240101", "field_type": "INTEGER", "mode": "NULLABLE"},
    {"name": "_20200101", "field_type": "INTEGER", "mode": "NULLABLE"},
    {"name": "tmin", "field_type": "STRING", "mode": "NULLABLE"},
    {"name": "_168", "field_type": "INTEGER", "mode": "NULLABLE"},
    {"name": "_20220101", "field_type": "INTEGER", "mode": "NULLABLE"},
    {"name": "tavg", "field_type": "STRING", "mode": "NULLABLE"},
    {"name": "_204", "field_type": "INTEGER", "mode": "NULLABLE"},
    {"name": "h", "field_type": "STRING", "mode": "NULLABLE"},
    {"name": "_20230101", "field_type": "INTEGER", "mode": "NULLABLE"},
    {"name": "_252", "field_type": "INTEGER", "mode": "NULLABLE"},
]


def test_detects_misparse_on_real_mangled_schema() -> None:
    d = detect_header_as_data_misparse(MISPARSED_SCHEMA)
    assert d["misparse_detected"] is True
    assert d["pathology"] == "HEADER_AS_DATA"
    assert d["confidence"] >= 0.9


def test_misparse_role_mapping() -> None:
    roles = detect_header_as_data_misparse(MISPARSED_SCHEMA)["role_columns"]
    assert roles["ID"] == ["ae_000041196"]
    assert set(roles["DATE"]) == {"_20200101", "_20210101", "_20220101", "_20230101", "_20240101"}
    assert set(roles["ELEMENT"]) == {"tmax", "tmin", "tavg"}
    assert set(roles["DATA_VALUE"]) == {"_278", "_168", "_204", "_252"}
    assert set(roles["FLAG"]) == {"s", "h"}


def test_misparse_marks_qflag_obstime_lost() -> None:
    d = detect_header_as_data_misparse(MISPARSED_SCHEMA)
    assert "Q_FLAG" in d["lost_columns"]
    assert "OBS_TIME" in d["lost_columns"]
    # ID/DATE/ELEMENT/DATA_VALUE are recoverable, so never lost.
    for col in ("ID", "DATE", "ELEMENT", "DATA_VALUE"):
        assert col not in d["lost_columns"]


def test_clean_schema_is_not_a_misparse() -> None:
    d = detect_header_as_data_misparse(KNOWN_GHCN_SCHEMA)
    assert d["misparse_detected"] is False
    assert d["pathology"] is None


def test_fivetran_metadata_alone_is_not_a_misparse() -> None:
    schema = [*KNOWN_GHCN_SCHEMA, {"name": "_fivetran_synced", "field_type": "TIMESTAMP", "mode": "NULLABLE"}]
    assert detect_header_as_data_misparse(schema)["misparse_detected"] is False


def test_reconstruction_mapping_builds_coalesce() -> None:
    m = build_reconstruction_mapping(MISPARSED_SCHEMA)
    assert m["misparse_detected"] is True
    assert m["ID"] == "`ae_000041196`"
    assert m["ID"].count("`") == 2
    # DATE coalesces all five per-year columns, in sorted order, wrapped in CAST.
    assert m["DATE"].startswith("CAST(COALESCE(")
    for yr in ("_20200101", "_20210101", "_20220101", "_20230101", "_20240101"):
        assert yr in m["DATE"]
    assert "COALESCE(" in m["ELEMENT"]
    assert "COALESCE(" in m["DATA_VALUE"]
    assert m["flag_candidates"] == ["h", "s"]


def test_compare_schemas_flags_additive_and_destructive() -> None:
    current = [c for c in KNOWN_GHCN_SCHEMA if c["name"] != "OBS_TIME"] + [
        {"name": "_fivetran_synced", "field_type": "TIMESTAMP", "mode": "NULLABLE"}
    ]
    result = compare_schemas(current, KNOWN_GHCN_SCHEMA)
    assert result["drift_detected"] is True
    added = {c["name"] for c in result["added"]}
    removed = {c["name"] for c in result["removed"]}
    assert "_fivetran_synced" in added
    assert "OBS_TIME" in removed


def test_schema_fingerprint_stable_and_order_independent() -> None:
    a = schema_fingerprint(KNOWN_GHCN_SCHEMA)
    b = schema_fingerprint(list(reversed(KNOWN_GHCN_SCHEMA)))
    assert a == b
    assert len(a) == 16
