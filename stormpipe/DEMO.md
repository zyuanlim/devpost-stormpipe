# StormPipe — Demo Guide (for reviewers)

**StormPipe** is an agentic data-pipeline health system for NOAA GHCN-Daily
weather data. It ingests NOAA's daily observations from AWS S3 into BigQuery via
**Fivetran**, then a multi-agent system (Google ADK + **Gemini 3.5 Flash**)
monitors the pipeline, diagnoses schema problems, and **self-heals data quality
in the warehouse** — replying with rich, agent-generated UI (**A2UI**) instead of
walls of text.

## The hero bug: headerless-CSV misparse

NOAA's `by_year` CSVs are **headerless** (the first line is already data), but the
Fivetran connector ran with `empty_header=false` — so Fivetran ate each file's
first data row as the column header. The `observations` table came out mangled:
columns named after data values (station ids, dates, element codes), and
`Q_FLAG` / `OBS_TIME` destroyed entirely.

StormPipe diagnoses it and offers a **two-tier fix**:
1. **In-warehouse (now):** rebuild `observations_clean` — COALESCE the scattered
   per-file columns back to the canonical schema (186.9M rows, tenths→SI, trace
   tagging). Unblocks analytics immediately; can't recover `Q_FLAG`/`OBS_TIME`.
2. **Source fix (complete):** set `empty_header=true` + re-sync to recover the
   lost columns. Mutates the live connector; requires operator approval.

> The bug is **left intact on purpose** (no re-sync) so the self-healing flow is
> demonstrable end-to-end.

## Try it

Live, public backend (Vertex AI Cloud Run):
`https://stormpipe-mued7ds4ba-uc.a.run.app`

### Option A — visual UI (recommended)

React + A2UI frontend, runs locally against the live backend. Needs Node 18+.

```bash
cd frontend
npm install
ADK_URL=https://stormpipe-mued7ds4ba-uc.a.run.app npm run dev
# open http://localhost:5173
```

Click a quick-action chip (or type your own). All three run against live data:

| Ask | You'll see | Backed by |
|-----|------------|-----------|
| *"Give me a pipeline health overview."* | Status card: sync status, last sync, misparse finding | live Fivetran API |
| *"What schema drift or misparse did you detect?"* | Card + **Tabs** (Detected / Recoverable / Lost) | live BigQuery `INFORMATION_SCHEMA` |
| *"Show the data-quality remediation status for observations_clean."* | Metrics card: rows cleaned, elements, flagged | live BigQuery (~30–60s, scans 186.9M rows) |

### Option B — API directly

```bash
URL=https://stormpipe-mued7ds4ba-uc.a.run.app
curl -X POST "$URL/apps/app/users/operator/sessions/demo-1" \
  -H 'content-type: application/json' -d '{}'
curl -X POST "$URL/run" -H 'content-type: application/json' -d '{
  "app_name": "app", "user_id": "operator", "session_id": "demo-1",
  "new_message": {"role":"user","parts":[{"text":"What schema drift or misparse did you detect?"}]},
  "streaming": false
}'
```

Returns a JSON array of ADK events. Agent-generated UI arrives as
`<a2ui-json>…</a2ui-json>` blocks (A2UI v0.9) inside the final turn's text; the
frontend parses and renders them natively (`frontend/src/a2ui/`).

## Architecture

```
NOAA GHCN-Daily (S3, headerless CSV)
        │  Fivetran connector  (misparse happens here)
        ▼
BigQuery  noaa_ghcn.observations  ──▶  observations_clean (remediated)
        ▲   tools: BigQuery, Fivetran REST, schema diff
        │
  ADK multi-agent  (Gemini 3.5 Flash)
   ├─ orchestrator        — routes, synthesizes, emits A2UI
   ├─ pipeline_controller — Fivetran status + source fix
   ├─ schema_detective    — drift + header-as-data misparse detection
   └─ dq_remediator       — rebuilds observations_clean
        │  + Vertex AI Memory Bank (preloaded GHCN domain facts)
        ▼
Cloud Run (fast_api_app)  ──▶  React + A2UI frontend
```

The agent composes each reply from A2UI primitives (Card, Column, Row, Text,
Icon, Tabs, Divider), so every intent gets a purpose-built layout with no
per-layout frontend code. The client also renders Markdown (headings, bold,
lists, code) in conversational text.

## Notes & limits

- First DQ query is slow (~30–60s): scans 186.9M rows + Cloud Run cold start.
- Hero bug intentionally preserved (no re-sync).
- Backend is **public** for review convenience; may be locked down after judging.
- Cloud Run scales to zero — first request after idle is slower.
