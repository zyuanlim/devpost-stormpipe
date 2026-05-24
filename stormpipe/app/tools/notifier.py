"""Operator notification and summary generation."""

import json
from datetime import datetime, timezone


def format_pipeline_summary(
    sync_status: dict,
    schema_findings: dict | None = None,
    dq_findings: dict | None = None,
) -> str:
    """Format a natural-language pipeline health summary for the operator.

    Args:
        sync_status: Fivetran sync status dict.
        schema_findings: Schema drift detective output, or None.
        dq_findings: Data quality remediation output, or None.

    Returns:
        Markdown-formatted summary string.
    """
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"## StormPipe Health Report — {ts}", ""]

    state = sync_status.get("sync_state", "unknown")
    icon = {"syncing": "🔄", "scheduled": "✅", "paused": "⏸️", "error": "🔴"}.get(state, "❓")
    lines.append(f"**Pipeline Status:** {icon} {state.upper()}")

    if sync_status.get("succeeded_at"):
        lines.append(f"**Last Successful Sync:** {sync_status['succeeded_at']}")
    if sync_status.get("failed_at"):
        lines.append(f"**Last Failure:** {sync_status['failed_at']}")
    lines.append("")

    if schema_findings:
        if schema_findings.get("drift_detected"):
            added = len(schema_findings.get("added", []))
            removed = len(schema_findings.get("removed", []))
            changed = len(schema_findings.get("type_changed", []))
            lines.append(f"**Schema Drift Detected:** +{added} columns, -{removed} columns, {changed} type changes")
            for change in schema_findings.get("changes", []):
                lines.append(f"  - `{change['column']}`: {change['change_type']} → {change['recommendation']}")
        else:
            lines.append("**Schema:** ✅ No drift detected")
        lines.append("")

    if dq_findings:
        total = dq_findings.get("total_rows_processed", 0)
        quarantined = dq_findings.get("quarantined_rows", 0)
        remediated = dq_findings.get("remediated_rows", 0)
        clean_pct = round(100 * (total - quarantined) / total, 1) if total else 0
        lines.append(f"**Data Quality:** {clean_pct}% clean ({remediated} remediated, {quarantined} quarantined / {total} total)")
        for issue in dq_findings.get("issues_found", []):
            lines.append(f"  - {issue['type']}: {issue['count']} rows — {issue['action']}")
        lines.append("")

    lines.append("---")
    lines.append("*Ask me anything: \"Show quarantined rows\", \"Explain Q_FLAG distribution\", \"Trigger resync\"*")
    return "\n".join(lines)
