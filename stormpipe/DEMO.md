# StormPipe — Demo Guide (for reviewers)

**StormPipe** is an agentic data-pipeline health system for NOAA GHCN-Daily
weather data. It ingests NOAA's Global Historical Climatology Network daily
observations from AWS S3 into BigQuery via **Fivetran**, then a multi-agent
system (built on Google's ADK + Gemini 3.5 Flash) monitors the pipeline, diagnoses
schema problems, and **self-heals data quality in the warehouse** — replying with
rich, agent-generated UI (**A2UI**) instead of walls of text.

---

## The hero story: the headerless-CSV misparse

NOAA's `by_year` CSV files are **headerless** — the first line is already data.
The Fivetran connector was configured with `empty_header=false`, so Fivetran
consumed the first *data* row of each yearly file as the column header. The
result is a badly mangled `observations` table:

- No canonical `ID / DATE / ELEMENT / DATA_VALUE` columns.
- Columns named after data values (a station id, one date per year, element
  codes like `tmax`, bare readings like `_278`).
- `Q_FLAG` and `OBS_TIME` were empty in those header rows and **destroyed
  entirely**.

StormPipe detects this, then offers a **two-tier fix**:

1. **In-warehouse (immediate):** rebuild `observations_clean` by COALESCE-ing the
   scattered per-file columns back into the canonical schema (186.9M rows,
   tenths→SI conversion, trace-precip tagging). Unblocks analytics now, but
   cannot recover the destroyed `Q_FLAG`/`OBS_TIME`.
2. **Source fix (complete):** patch the connector (`empty_header=true`) and
   re-sync — the only way to recover the lost columns. Requires operator
   approval; mutates the live connector.

> The bug is **intentionally preserved** in this demo (no re-sync run) so the
> self-healing flow is visible end-to-end.

---

## Try it

The agent backend is live and public (Vertex AI Cloud Run):

```
https://stormpipe-mued7ds4ba-uc.a.run.app
```

### Option A — the visual UI (recommended)

The React + A2UI frontend renders the agent's responses as native cards, tabs,
and status indicators. It runs locally and talks to the live backend.

Prerequisites: Node 18+.

```bash
cd frontend
npm install
ADK_URL=https://stormpipe-mued7ds4ba-uc.a.run.app npm run dev
# open http://localhost:5173
```

Then click a quick-action chip (or type your own question). All three work
against live data:

| Ask | What you'll see | Backed by |
|-----|-----------------|-----------|
| **"Give me a pipeline health overview."** | Status card: Fivetran sync status, last sync time, and the misparse finding | live Fivetran API |
| **"What schema drift or misparse did you detect?"** | Card + **Tabs** (Detected / Recoverable / Lost) | live BigQuery `INFORMATION_SCHEMA` |
| **"Show the data-quality remediation status for observations_clean."** | Card with rows cleaned, element count, flagged count | live BigQuery (~30–60s — scans 186.9M rows) |

### Option B — the API directly (no UI)

The backend speaks ADK's REST API. Create a session, then run a turn:

```bash
URL=https://stormpipe-mued7ds4ba-uc.a.run.app

# 1. create a session
curl -X POST "$URL/apps/app/users/operator/sessions/demo-1" \
  -H 'content-type: application/json' -d '{}'

# 2. ask a question
curl -X POST "$URL/run" -H 'content-type: application/json' -d '{
  "app_name": "app",
  "user_id": "operator",
  "session_id": "demo-1",
  "new_message": {"role": "user", "parts": [{"text": "What schema drift or misparse did you detect?"}]},
  "streaming": false
}'
```

The response is a JSON array of ADK events. The final model turn's text contains
the answer; agent-generated UI arrives as `<a2ui-json>…</a2ui-json>` blocks (A2UI
v0.9 messages) embedded in that text. The frontend parses those blocks and
renders them natively — see `frontend/src/a2ui/`.

---

## What you're looking at (A2UI)

Rather than returning plain text, the agent composes its answer from A2UI
primitives (Card, Column, Row, Text, Icon, Tabs, Divider, …). The client renders
them with its own components, so each intent gets a purpose-built layout — a
status card for health, tabs for a schema drill-down, a metrics card for
remediation — with no per-layout frontend code.

---

## Architecture

```
NOAA GHCN-Daily (S3, headerless CSV)
        │  Fivetran connector  (the misparse happens here)
        ▼
BigQuery  noaa_ghcn.observations  ──▶  observations_clean (remediated)
        ▲
        │  tools (BigQuery, Fivetran REST, schema diff)
        │
  ADK multi-agent  (Gemini 3.5 Flash)
   ├─ orchestrator        — routes, synthesizes, emits A2UI
   ├─ pipeline_controller — Fivetran sync status + source fix
   ├─ schema_detective    — drift + header-as-data misparse detection
   └─ dq_remediator       — rebuilds observations_clean
        │  + Vertex AI Memory Bank (preloaded GHCN domain facts)
        ▼
Cloud Run (fast_api_app)  ──▶  React + A2UI frontend
```

---

## Notes & limits

- The **DQ remediation** query scans 186.9M rows — first response can take
  ~30–60s (plus Cloud Run cold start on the first request).
- The hero misparse bug is **left intact on purpose**; the source re-sync is not
  run so the diagnosis/remediation flow stays demonstrable.
- The backend is a **public** endpoint for review convenience; it may be locked
  down or removed after judging.
- Cloud Run scales to zero, so the very first request after idle is slower.
