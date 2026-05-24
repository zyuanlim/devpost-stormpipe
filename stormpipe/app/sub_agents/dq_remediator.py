"""Data Quality Remediator sub-agent — fixes GHCN-Daily quality issues in BigQuery."""

from google.adk.agents import Agent
from google.adk.models import Gemini
from app.tools.bigquery_tool import (
    bigquery_create_table_if_not_exists,
    bigquery_run_dml,
    bigquery_run_query,
)

PROJECT = "stormpipe-hackathon"
DATASET = "noaa_ghcn"

QUARANTINE_DDL = f"""
CREATE TABLE IF NOT EXISTS `{PROJECT}.{DATASET}._quarantine` (
  ID STRING,
  DATE STRING,
  ELEMENT STRING,
  DATA_VALUE INT64,
  M_FLAG STRING,
  Q_FLAG STRING,
  S_FLAG STRING,
  OBS_TIME STRING,
  DQ_ISSUE STRING,
  DQ_REASON STRING,
  DQ_CONFIDENCE FLOAT64,
  QUARANTINED_AT TIMESTAMP
)
"""

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

OBSERVATIONS_CLEAN_DDL = f"""
CREATE TABLE IF NOT EXISTS `{PROJECT}.{DATASET}.observations_clean` (
  ID STRING,
  DATE STRING,
  ELEMENT STRING,
  DATA_VALUE INT64,
  DATA_VALUE_CLEAN FLOAT64,
  UNIT STRING,
  M_FLAG STRING,
  Q_FLAG STRING,
  S_FLAG STRING,
  OBS_TIME STRING,
  DQ_FLAGGED BOOL,
  DQ_NOTE STRING
)
"""


def ensure_dq_tables() -> dict:
    """Create quarantine, audit log, and observations_clean tables if they don't exist.

    Returns:
        Dict with table creation status for each table.
    """
    from app.tools.bigquery_tool import bigquery_create_table_if_not_exists
    results = {}
    for name, ddl in [
        ("_quarantine", QUARANTINE_DDL),
        ("_audit_log", AUDIT_LOG_DDL),
        ("observations_clean", OBSERVATIONS_CLEAN_DDL),
    ]:
        results[name] = bigquery_create_table_if_not_exists(DATASET, name, ddl)
    return results


dq_remediator_agent = Agent(
    name="dq_remediator",
    model=Gemini(model="gemini-2.5-pro"),
    description=(
        "Remediates GHCN-Daily data quality issues in BigQuery. "
        "Handles: -9999 missing sentinels → NULL, Q_FLAG failures → quarantine, "
        "tenths-of-unit encoding → DATA_VALUE_CLEAN, trace precipitation tagging. "
        "Writes results to observations_clean and _quarantine tables."
    ),
    instruction=open("app/prompts/dq_remediator.md").read(),
    tools=[
        ensure_dq_tables,
        bigquery_run_query,
        bigquery_run_dml,
        bigquery_create_table_if_not_exists,
    ],
)
