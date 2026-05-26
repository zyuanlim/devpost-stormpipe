import os

from google.cloud import bigquery

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "stormpipe-hackathon")
BQ_DATASET = "noaa_ghcn"

_client: bigquery.Client | None = None


def _bq() -> bigquery.Client:
    global _client
    if _client is None:
        _client = bigquery.Client(project=PROJECT)
    return _client


def bigquery_run_query(sql: str) -> list[dict]:
    """Execute a BigQuery SQL query and return results as a list of dicts.

    Args:
        sql: Standard SQL query string.

    Returns:
        List of row dicts. Max 1000 rows.
    """
    job = _bq().query(sql)
    rows = list(job.result())
    return [dict(r) for r in rows[:1000]]


def bigquery_get_schema(dataset: str, table: str) -> list[dict]:
    """Get BigQuery table schema as list of column descriptors.

    Args:
        dataset: BigQuery dataset name.
        table: BigQuery table name.

    Returns:
        List of dicts with keys: name, field_type, mode, description.
    """
    ref = _bq().get_table(f"{PROJECT}.{dataset}.{table}")
    return [
        {
            "name": f.name,
            "field_type": f.field_type,
            "mode": f.mode,
            "description": f.description or "",
        }
        for f in ref.schema
    ]


def bigquery_list_tables(dataset: str = BQ_DATASET) -> list[str]:
    """List all tables in a BigQuery dataset.

    Args:
        dataset: Dataset name. Defaults to noaa_ghcn.

    Returns:
        List of table names.
    """
    tables = _bq().list_tables(f"{PROJECT}.{dataset}")
    return [t.table_id for t in tables]


def bigquery_run_dml(sql: str) -> dict:
    """Execute a BigQuery DML statement (INSERT, UPDATE, DELETE, MERGE).

    Args:
        sql: DML SQL statement.

    Returns:
        Dict with num_dml_affected_rows and job_id.
    """
    job = _bq().query(sql)
    job.result()
    return {
        "num_dml_affected_rows": job.num_dml_affected_rows,
        "job_id": job.job_id,
        "status": "completed",
    }


def bigquery_create_table_if_not_exists(dataset: str, table: str, schema_ddl: str) -> dict:
    """Create a BigQuery table if it does not already exist.

    Args:
        dataset: Dataset name.
        table: Table name.
        schema_ddl: Full CREATE TABLE IF NOT EXISTS DDL statement.

    Returns:
        Dict with table_id and created (bool).
    """
    full_id = f"{PROJECT}.{dataset}.{table}"
    try:
        _bq().get_table(full_id)
        return {"table_id": full_id, "created": False}
    except Exception:
        job = _bq().query(schema_ddl)
        job.result()
        return {"table_id": full_id, "created": True}
