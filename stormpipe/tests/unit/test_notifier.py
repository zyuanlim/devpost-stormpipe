"""Unit tests for the operator-facing pipeline summary formatter."""

from app.tools.notifier import format_pipeline_summary


def test_summary_includes_status_and_timestamp() -> None:
    out = format_pipeline_summary({"sync_state": "scheduled", "succeeded_at": "2026-05-24T23:38:46Z"})
    assert "StormPipe Health Report" in out
    assert "SCHEDULED" in out
    assert "2026-05-24T23:38:46Z" in out


def test_summary_reports_schema_drift() -> None:
    out = format_pipeline_summary(
        {"sync_state": "scheduled"},
        schema_findings={
            "drift_detected": True,
            "added": ["_fivetran_synced"],
            "removed": [],
            "type_changed": [],
            "changes": [
                {"column": "_fivetran_synced", "change_type": "ADDITIVE", "recommendation": "ACCEPT"}
            ],
        },
    )
    assert "Schema Drift Detected" in out
    assert "_fivetran_synced" in out


def test_summary_reports_clean_schema() -> None:
    out = format_pipeline_summary({"sync_state": "scheduled"}, schema_findings={"drift_detected": False})
    assert "No drift detected" in out


def test_summary_computes_dq_clean_percentage() -> None:
    out = format_pipeline_summary(
        {"sync_state": "scheduled"},
        dq_findings={
            "total_rows_processed": 1000,
            "quarantined_rows": 100,
            "remediated_rows": 200,
            "issues_found": [{"type": "MISSING_SENTINEL", "count": 50, "action": "set to NULL"}],
        },
    )
    assert "90.0% clean" in out
    assert "MISSING_SENTINEL" in out


def test_summary_handles_error_state() -> None:
    out = format_pipeline_summary({"sync_state": "error", "failed_at": "2026-05-24T22:32:24Z"})
    assert "ERROR" in out
    assert "2026-05-24T22:32:24Z" in out
