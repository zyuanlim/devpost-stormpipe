"""Data Quality Remediator sub-agent — rebuilds + cleans GHCN-Daily data in BigQuery.

The raw `noaa_ghcn.observations` table is misparsed (the headerless CSV's first row
was consumed as the header). This agent reconstructs the canonical 8-column schema
from the scattered per-file columns and applies GHCN-Daily data-quality rules.
"""

from google.adk.agents import Agent
from google.adk.models import Gemini

from app.tools.bigquery_tool import (
    bigquery_create_table_if_not_exists,
    bigquery_get_schema,
    bigquery_run_dml,
    bigquery_run_query,
)
from app.tools.schema_comparator import build_reconstruction_mapping

PROJECT = "stormpipe-hackathon"
DATASET = "noaa_ghcn"
RAW_TABLE = "observations"
CLEAN_TABLE = "observations_clean"

# GHCN elements whose DATA_VALUE is stored in tenths and their SI unit after /10.
TENTHS_C = {"TMAX", "TMIN", "TAVG", "TOBS", "MDTX", "MDTN", "MNPN", "MXPN", "ADPT", "AWBT"}
TENTHS_MM = {"PRCP", "WESD", "WESF"}
TENTHS_MS = {"AWND", "WSF2", "WSF5", "WSFG"}
WHOLE_MM = {"SNOW", "SNWD", "THIC"}

AUDIT_LOG_DDL = f"""
CREATE TABLE IF NOT EXISTS `{PROJECT}.{DATASET}._audit_log` (
  RUN_ID STRING,
  AGENT_NAME STRING,
  ACTION STRING,
  SQL_EXECUTED STRING,
  ROWS_AFFECTED INT64,
  DETAILS STRING,
  EXECUTED_AT TIMESTAMP
)
"""

QUARANTINE_DDL = f"""
CREATE TABLE IF NOT EXISTS `{PROJECT}.{DATASET}._quarantine` (
  ID STRING,
  DATE STRING,
  ELEMENT STRING,
  DATA_VALUE INT64,
  DQ_ISSUE STRING,
  DQ_REASON STRING,
  DQ_CONFIDENCE FLOAT64,
  QUARANTINED_AT TIMESTAMP
)
"""


def _quoted(items: set[str]) -> str:
    return ", ".join(f"'{e}'" for e in sorted(items))


def _unit_case() -> str:
    return f"""CASE
      WHEN ELEMENT IN ({_quoted(TENTHS_C)}) THEN 'degC'
      WHEN ELEMENT IN ({_quoted(TENTHS_MM | WHOLE_MM)}) THEN 'mm'
      WHEN ELEMENT IN ({_quoted(TENTHS_MS)}) THEN 'm/s'
      ELSE 'raw'
    END"""


def _clean_value_case() -> str:
    # DATA_VALUE is already NULL when it equals the -9999 missing sentinel.
    return f"""CASE
      WHEN DATA_VALUE IS NULL THEN NULL
      WHEN ELEMENT IN ({_quoted(TENTHS_C | TENTHS_MM | TENTHS_MS)}) THEN DATA_VALUE / 10.0
      ELSE CAST(DATA_VALUE AS FLOAT64)
    END"""


def _assign_flags(flag_candidates: list[str]) -> dict:
    """Assign ambiguous single-char flag columns to M_FLAG / S_FLAG by fill density.

    GHCN S_FLAG (source) is populated on almost every row; M_FLAG (measurement) is
    sparse. So the densest flag column is S_FLAG, the sparser one M_FLAG.
    """
    if not flag_candidates:
        return {"M_FLAG": "CAST(NULL AS STRING)", "S_FLAG": "CAST(NULL AS STRING)"}
    counts = []
    for col in flag_candidates:
        rows = bigquery_run_query(
            f"SELECT COUNTIF(`{col}` IS NOT NULL) AS n FROM `{PROJECT}.{DATASET}.{RAW_TABLE}`"
        )
        counts.append((col, rows[0]["n"]))
    counts.sort(key=lambda x: x[1], reverse=True)
    s_flag = f"`{counts[0][0]}`"
    m_flag = f"`{counts[1][0]}`" if len(counts) > 1 else "CAST(NULL AS STRING)"
    return {"M_FLAG": m_flag, "S_FLAG": s_flag}


def build_clean_table_sql(dry_run: bool = True) -> dict:
    """Compose (and optionally run) the CTAS that rebuilds observations_clean.

    Reconstructs canonical ID/DATE/ELEMENT/DATA_VALUE from the misparsed raw table,
    converts tenths-encoded values to SI units, tags trace precipitation, and records
    which canonical fields were lost in the misparse.

    Args:
        dry_run: If True, return the SQL and plan without executing. If False, run
            the CTAS and return row counts.

    Returns:
        Dict with the generated SQL, the column mapping, lost_columns, and (when run)
        rows_written.
    """
    schema = bigquery_get_schema(DATASET, RAW_TABLE)
    mapping = build_reconstruction_mapping(schema)
    if not mapping["misparse_detected"]:
        # Reconstruction only applies to the misparsed table. On a canonical schema the
        # role columns are empty, so the COALESCE expressions collapse to NULL — running
        # the CTAS would overwrite observations_clean with all-NULL core fields.
        return {
            "dry_run": dry_run,
            "skipped": True,
            "misparse_detected": False,
            "reason": (
                f"`{RAW_TABLE}` has the canonical GHCN schema (no header-as-data "
                "misparse detected). This tool reconstructs only from a misparsed "
                "table; it would overwrite observations_clean with NULL ID/DATE/"
                "ELEMENT/DATA_VALUE. Clean the canonical table directly instead."
            ),
        }
    flags = _assign_flags(mapping["flag_candidates"])

    sql = f"""CREATE OR REPLACE TABLE `{PROJECT}.{DATASET}.{CLEAN_TABLE}` AS
WITH recon AS (
  SELECT
    {mapping['ID']} AS ID,
    {mapping['DATE']} AS DATE,
    {mapping['ELEMENT']} AS ELEMENT,
    NULLIF({mapping['DATA_VALUE']}, -9999) AS DATA_VALUE,
    {flags['M_FLAG']} AS M_FLAG,
    CAST(NULL AS STRING) AS Q_FLAG,   -- lost in misparse (empty in source header row)
    {flags['S_FLAG']} AS S_FLAG,
    CAST(NULL AS STRING) AS OBS_TIME, -- lost in misparse
    CAST(REGEXP_EXTRACT(_file, r'by_year/(\\d{{4}})') AS INT64) AS SOURCE_YEAR
  FROM `{PROJECT}.{DATASET}.{RAW_TABLE}`
)
SELECT
  ID, DATE, ELEMENT, DATA_VALUE,
  {_clean_value_case()} AS DATA_VALUE_CLEAN,
  {_unit_case()} AS UNIT,
  M_FLAG, Q_FLAG, S_FLAG, OBS_TIME, SOURCE_YEAR,
  (DATA_VALUE IS NULL OR M_FLAG = 'T') AS DQ_FLAGGED,
  CASE
    WHEN M_FLAG = 'T' THEN 'TRACE_PRECIP'
    WHEN DATA_VALUE IS NULL THEN 'MISSING_SENTINEL'
    ELSE NULL
  END AS DQ_NOTE
FROM recon"""

    result = {
        "dry_run": dry_run,
        "sql": sql,
        "column_mapping": {
            "ID": mapping["ID"],
            "DATE": mapping["DATE"],
            "ELEMENT": mapping["ELEMENT"],
            "DATA_VALUE": mapping["DATA_VALUE"],
            "M_FLAG": flags["M_FLAG"],
            "S_FLAG": flags["S_FLAG"],
        },
        "lost_columns": mapping["lost_columns"],
    }
    if not dry_run:
        bigquery_run_dml(sql)
        counts = bigquery_run_query(
            f"SELECT COUNT(*) AS total, COUNTIF(DQ_FLAGGED) AS flagged, "
            f"COUNT(DISTINCT ELEMENT) AS elements "
            f"FROM `{PROJECT}.{DATASET}.{CLEAN_TABLE}`"
        )
        result["rows_written"] = counts[0]
    return result


def ensure_dq_tables() -> dict:
    """Create the audit-log and quarantine tables if they don't exist."""
    results = {}
    for name, ddl in [("_audit_log", AUDIT_LOG_DDL), ("_quarantine", QUARANTINE_DDL)]:
        results[name] = bigquery_create_table_if_not_exists(DATASET, name, ddl)
    return results


dq_remediator_agent = Agent(
    name="dq_remediator",
    model=Gemini(model="gemini-3.5-flash"),
    description=(
        "Rebuilds and cleans GHCN-Daily data in BigQuery. Reconstructs the canonical "
        "8-column schema from the misparsed raw table (COALESCE of scattered per-file "
        "columns), converts tenths-encoded values to SI units, tags trace precipitation, "
        "and writes observations_clean. Reports which fields (Q_FLAG, OBS_TIME) were lost "
        "in the misparse and require a source re-sync."
    ),
    instruction=open("app/prompts/dq_remediator.md").read(),
    tools=[
        ensure_dq_tables,
        build_clean_table_sql,
        bigquery_run_query,
        bigquery_run_dml,
        bigquery_create_table_if_not_exists,
    ],
)
