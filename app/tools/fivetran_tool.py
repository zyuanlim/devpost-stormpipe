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


def fivetran_list_connectors() -> dict:
    """List the Fivetran connectors (pipelines) available in the group.

    Use this to enumerate pipelines the operator can dive into. Each entry is a
    selectable pipeline; the operator picks one and the rest of the tools scope
    to its connector_id.

    Returns:
        Dict with ``connectors``: a list of {connector_id, service, schema,
        sync_state, setup_state, succeeded_at, failed_at}.
    """
    resp = _api("GET", f"/groups/{GROUP_ID}/connections")
    if "error" in resp:
        return {"group_id": GROUP_ID, "connectors": [], "error": resp["error"]}
    items = resp.get("data", {}).get("items", [])
    connectors = []
    for d in items:
        status = d.get("status", {})
        connectors.append(
            {
                "connector_id": d.get("id"),
                "service": d.get("service"),
                "schema": d.get("schema"),
                "sync_state": status.get("sync_state"),
                "setup_state": status.get("setup_state"),
                "succeeded_at": d.get("succeeded_at"),
                "failed_at": d.get("failed_at"),
            }
        )
    return {"group_id": GROUP_ID, "connectors": connectors}


def fivetran_connector_status(connector_id: str = "") -> dict:
    """Get the current Fivetran connector status (sync state, setup state, errors).

    Args:
        connector_id: Which connector to inspect. Defaults to the configured
            GHCN connector when empty.

    Returns:
        Dict with connector_id, setup_state, sync_state, succeeded_at, failed_at,
        is_historical_sync, and any blocking tasks/warnings.
    """
    connector_id = connector_id or CONNECTOR_ID
    resp = _api("GET", f"/connections/{connector_id}")
    if "error" in resp:
        return {"connector_id": connector_id, "error": resp["error"]}
    d = resp.get("data", {})
    status = d.get("status", {})
    return {
        "connector_id": connector_id,
        "service": d.get("service"),
        "setup_state": status.get("setup_state"),
        "sync_state": status.get("sync_state"),
        "succeeded_at": d.get("succeeded_at"),
        "failed_at": d.get("failed_at"),
        "is_historical_sync": status.get("is_historical_sync"),
        "tasks": status.get("tasks", []),
        "warnings": status.get("warnings", []),
    }


def fivetran_diagnose_csv_parsing(connector_id: str = "") -> dict:
    """Inspect the S3 connector's CSV config and diagnose the header-as-data misparse.

    The NOAA GHCN ``by_year`` CSV files are headerless. If the connector has
    ``empty_header=false`` it treats each file's first data row as the header, mangling
    the schema. This returns the root cause and the exact config patch that fixes it.

    Args:
        connector_id: Which connector to diagnose. Defaults to the configured GHCN
            connector when empty.

    Returns:
        Dict with root_cause, current empty_header value, recommended patch, and whether
        a fix is needed.
    """
    connector_id = connector_id or CONNECTOR_ID
    resp = _api("GET", f"/connections/{connector_id}")
    if "error" in resp:
        return {
            "connector_id": connector_id,
            "needs_fix": None,
            "error": resp["error"],
            "root_cause": "Could not diagnose — the Fivetran API call failed.",
        }
    d = resp.get("data", {})
    cfg = d.get("config", {})
    empty_header = cfg.get("empty_header")
    needs_fix = empty_header is False or empty_header == "false"
    return {
        "connector_id": connector_id,
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


def fivetran_fix_csv_header_config(confirm: bool = False, connector_id: str = "") -> dict:
    """Patch the connector to enable headerless CSV parsing (empty_header=true).

    Args:
        confirm: Must be True to actually apply the change. If False, returns the planned
            patch without modifying the connector.
        connector_id: Which connector to patch. Defaults to the configured GHCN
            connector when empty.

    Returns:
        Dict with the patch applied (or planned) and the resulting empty_header value.
        If the connector is already headerless, reports ``already_correct`` rather
        than pretending a fix was made.
    """
    connector_id = connector_id or CONNECTOR_ID
    patch = {"config": {"empty_header": True}}

    # Honesty guard: if the connector is already in headerless mode, applying the
    # patch changes nothing — say so plainly instead of reporting a fix that did
    # not happen. (The mangled data can still persist if no re-sync has run.)
    current = _api("GET", f"/connections/{connector_id}")
    if "error" not in current:
        empty_header = current.get("data", {}).get("config", {}).get("empty_header")
        if empty_header is True or empty_header == "true":
            return {
                "applied": False,
                "already_correct": True,
                "empty_header": True,
                "note": (
                    "Connector is already in headerless mode (empty_header=true); no "
                    "config change is needed. The mangled data persists only because "
                    "no re-sync has re-ingested the files with the corrected parsing."
                ),
            }

    if not confirm:
        return {"applied": False, "planned_patch": patch, "note": "Re-call with confirm=True to apply."}
    resp = _api("PATCH", f"/connections/{connector_id}", patch)
    if "error" in resp:
        return {"applied": False, "error": resp["error"]}
    new_cfg = resp.get("data", {}).get("config", {})
    return {
        "applied": resp.get("code") == "Success",
        "code": resp.get("code"),
        "empty_header": new_cfg.get("empty_header"),
        "message": resp.get("message"),
    }


def _resync_execution_enabled() -> bool:
    """Whether the tool may actually fire a live re-sync.

    OFF by default. A real historical re-sync re-ingests all ~187M GHCN rows with
    the corrected headerless parsing — which UN-MANGLES the data and takes ~1
    hour. That is irreversible and would erase the intentionally-preserved
    misparse. So the tool returns the re-sync as a *proposal* for the operator to
    approve out-of-band, unless ``FIVETRAN_RESYNC_ENABLED`` is explicitly set.
    """
    return os.environ.get("FIVETRAN_RESYNC_ENABLED", "").lower() in ("1", "true", "yes")


def fivetran_resync(confirm: bool = False, connector_id: str = "") -> dict:
    """Propose (or, if enabled, trigger) a full historical re-sync of the connector.

    Use after the CSV header config is correct so the fixed parsing is applied to
    all data. A full re-sync of the GHCN by_year files takes roughly an hour and
    recovers the Q_FLAG / OBS_TIME columns the misparse destroyed.

    Execution is gated behind ``FIVETRAN_RESYNC_ENABLED`` (see
    ``_resync_execution_enabled``). When disabled, this returns the re-sync as a
    proposal — it does NOT run, and the caller must NOT claim it ran.

    Args:
        confirm: Must be True to trigger the re-sync (only honored when execution
            is enabled). If False, returns the plan.
        connector_id: Which connector to re-sync. Defaults to the configured GHCN
            connector when empty.

    Returns:
        Dict describing the proposed / planned / triggered re-sync.
    """
    connector_id = connector_id or CONNECTOR_ID
    # Resync scope is a {schema: [tables]} map; the array must be non-empty. GHCN
    # lands in schema `noaa_ghcn`, table `observations`.
    scope = {"noaa_ghcn": ["observations"]}
    plan = {
        "action": "full_historical_resync",
        "connector_id": connector_id,
        "scope": scope,
        "duration_estimate": "~1 hour",
        "recovers": "All 8 GHCN columns, including the Q_FLAG and OBS_TIME lost in the misparse.",
        "irreversible": True,
    }

    if not _resync_execution_enabled():
        return {
            "triggered": False,
            "status": "proposed",
            "plan": plan,
            "note": (
                "This is a PROPOSED source fix that requires operator approval and is "
                "executed out-of-band — re-sync execution is disabled here. Present the "
                "plan; do NOT claim the re-sync ran and do NOT emit manual UI steps. The "
                "immediate, applied remediation is the in-warehouse observations_clean rebuild."
            ),
        }

    if not confirm:
        return {
            "triggered": False,
            "status": "planned",
            "plan": plan,
            "note": "Re-call with confirm=True to trigger the full historical re-sync (~1 hour).",
        }
    resp = _api("POST", f"/connections/{connector_id}/resync", {"scope": scope})
    if "error" in resp:
        return {"triggered": False, "error": resp["error"]}
    return {
        "triggered": resp.get("code") == "Success",
        "code": resp.get("code"),
        "message": resp.get("message"),
    }
