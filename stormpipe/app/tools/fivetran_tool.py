"""Fivetran control tools — status, root-cause diagnosis, and source self-healing.

These call the Fivetran REST API directly (credentials from env or Secret Manager) so
the agent can fix the pipeline at the source: the headerless-CSV misparse is corrected
by enabling Fivetran's headerless mode and re-syncing, which restores all 8 GHCN columns
(including the Q_FLAG and OBS_TIME that the misparse destroyed).

All mutating calls are gated behind an explicit ``confirm`` flag. With ``confirm=False``
(the default) they return the planned action without changing anything.
"""

import base64
import json
import os
import urllib.error
import urllib.request

CONNECTOR_ID = "personified_hither"
GROUP_ID = "unconcerned_sweat"
PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "stormpipe-hackathon")
_API_BASE = "https://api.fivetran.com/v1"


def _creds() -> tuple[str, str]:
    key = os.environ.get("FIVETRAN_API_KEY")
    secret = os.environ.get("FIVETRAN_API_SECRET")
    if key and secret:
        return key, secret
    from google.cloud import secretmanager

    sm = secretmanager.SecretManagerServiceClient()

    def _get(name: str) -> str:
        path = f"projects/{PROJECT}/secrets/{name}/versions/latest"
        return sm.access_secret_version(name=path).payload.data.decode().strip()

    return _get("FIVETRAN_API_KEY"), _get("FIVETRAN_API_SECRET")


def _api(method: str, path: str, body: dict | None = None) -> dict:
    key, secret = _creds()
    token = base64.b64encode(f"{key}:{secret}".encode()).decode()
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{_API_BASE}{path}",
        data=data,
        method=method,
        headers={"Authorization": f"Basic {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": {"status": e.code, "message": e.read().decode()[:500]}}
    except urllib.error.URLError as e:
        return {"error": {"status": None, "message": str(e.reason)[:500]}}


def fivetran_connector_status() -> dict:
    """Get the current Fivetran connector status (sync state, setup state, errors).

    Returns:
        Dict with connector_id, setup_state, sync_state, succeeded_at, failed_at,
        is_historical_sync, and any blocking tasks/warnings.
    """
    resp = _api("GET", f"/connections/{CONNECTOR_ID}")
    if "error" in resp:
        return {"connector_id": CONNECTOR_ID, "error": resp["error"]}
    d = resp.get("data", {})
    status = d.get("status", {})
    return {
        "connector_id": CONNECTOR_ID,
        "service": d.get("service"),
        "setup_state": status.get("setup_state"),
        "sync_state": status.get("sync_state"),
        "succeeded_at": d.get("succeeded_at"),
        "failed_at": d.get("failed_at"),
        "is_historical_sync": status.get("is_historical_sync"),
        "tasks": status.get("tasks", []),
        "warnings": status.get("warnings", []),
    }


def fivetran_diagnose_csv_parsing() -> dict:
    """Inspect the S3 connector's CSV config and diagnose the header-as-data misparse.

    The NOAA GHCN ``by_year`` CSV files are headerless. If the connector has
    ``empty_header=false`` it treats each file's first data row as the header, mangling
    the schema. This returns the root cause and the exact config patch that fixes it.

    Returns:
        Dict with root_cause, current empty_header value, recommended patch, and whether
        a fix is needed.
    """
    resp = _api("GET", f"/connections/{CONNECTOR_ID}")
    if "error" in resp:
        return {
            "connector_id": CONNECTOR_ID,
            "needs_fix": None,
            "error": resp["error"],
            "root_cause": "Could not diagnose — the Fivetran API call failed.",
        }
    d = resp.get("data", {})
    cfg = d.get("config", {})
    empty_header = cfg.get("empty_header")
    needs_fix = empty_header is False or empty_header == "false"
    return {
        "connector_id": CONNECTOR_ID,
        "file_type": cfg.get("file_type"),
        "bucket": cfg.get("bucket"),
        "prefix": cfg.get("prefix"),
        "empty_header": empty_header,
        "needs_fix": needs_fix,
        "root_cause": (
            "Source files are headerless but empty_header=false, so Fivetran consumes the "
            "first data row of each file as column names — producing the mangled schema."
            if needs_fix
            else "CSV header handling looks correct."
        ),
        "recommended_patch": {"config": {"empty_header": True}} if needs_fix else None,
        "effect_of_fix": (
            "Fivetran will generate generic column names (column_0..column_7) for the "
            "headerless files. A re-sync then restores all 8 GHCN columns, including the "
            "Q_FLAG and OBS_TIME lost in the misparse."
        ),
    }


def fivetran_fix_csv_header_config(confirm: bool = False) -> dict:
    """Patch the connector to enable headerless CSV parsing (empty_header=true).

    Args:
        confirm: Must be True to actually apply the change. If False, returns the planned
            patch without modifying the connector.

    Returns:
        Dict with the patch applied (or planned) and the resulting empty_header value.
    """
    patch = {"config": {"empty_header": True}}
    if not confirm:
        return {"applied": False, "planned_patch": patch, "note": "Re-call with confirm=True to apply."}
    resp = _api("PATCH", f"/connections/{CONNECTOR_ID}", patch)
    if "error" in resp:
        return {"applied": False, "error": resp["error"]}
    new_cfg = resp.get("data", {}).get("config", {})
    return {
        "applied": resp.get("code") == "Success",
        "code": resp.get("code"),
        "empty_header": new_cfg.get("empty_header"),
        "message": resp.get("message"),
    }


def fivetran_resync(confirm: bool = False) -> dict:
    """Trigger a full historical re-sync of the connector.

    Use after fixing the CSV header config so the corrected parsing is applied to all
    data. A full re-sync of the GHCN by_year files takes roughly an hour.

    Args:
        confirm: Must be True to actually trigger the re-sync. If False, returns the plan.

    Returns:
        Dict describing the triggered (or planned) re-sync.
    """
    if not confirm:
        return {
            "triggered": False,
            "note": "Re-call with confirm=True to trigger a full historical re-sync (~1 hour).",
        }
    resp = _api("POST", f"/connections/{CONNECTOR_ID}/resync", {"scope": {"observations": []}})
    if "error" in resp:
        return {"triggered": False, "error": resp["error"]}
    return {
        "triggered": resp.get("code") == "Success",
        "code": resp.get("code"),
        "message": resp.get("message"),
    }
