# Hackathon Winning Plan: NOAA Storm Events Pipeline Intelligence Agent
### Google Cloud Rapid Agent Hackathon — Fivetran Track ($5,000 First Prize)

***

## Executive Summary

This plan targets **1st place in the Fivetran track** of the [Google Cloud Rapid Agent Hackathon](https://rapid-agent.devpost.com/) by building **StormPipe** — an agentic data engineering system that ingests the notoriously messy NOAA Storm Events Database from AWS S3 into BigQuery, using an AI agent to autonomously detect, diagnose, and resolve pipeline ambiguities, schema drift, and data quality issues in real time.[^1][^2]

The NOAA Storm Events Database is a perfect "finicky dataset" for this use case: it spans 1950–present, has undergone multiple major schema restructurings, contains inconsistent property damage formats (e.g., `"1.5K"` vs `1500` vs `""` vs `"1.5M"`), non-standard free-text event type names that changed across decades, timezone inconsistencies (CST-forced records pre-1993 mixed with local-time records post-1993), and missing fields across roughly half of all records. Academic research explicitly documents the database as suffering from "incompleteness and inconsistencies" and warns it "should not be used without taking reservations and appropriate precautions."[^2][^3][^1]

The judging criteria — technological implementation, design, potential impact, and quality of the idea — are all strongly served by this approach.

***

## 0. Implementation Status (updated 2026-05-25)

> This section reflects the **actual build**. It supersedes the original plan where they diverge. The rest of this document is retained as the original design reference.

### 0.1 Dataset pivot: Storm Events → GHCN-Daily

The implementation uses **NOAA GHCN-Daily** (`s3://noaa-ghcn-pds`, `csv.gz/by_year/` 2020–2024), **not** NOAA Storm Events (`noaa-swdi-pds`). Consequences:
- Single table `noaa_ghcn.observations` (8 logical columns), not details/locations/fatalities.
- The "finicky" challenge is **not** K/M property-damage parsing or 489→48 event-taxonomy normalization. Those FRs (FR-03 original, FR-04) are **dropped** — GHCN ELEMENT codes are already standardized.
- New hero challenge below.

### 0.2 The hero bug: headerless-CSV misparse

GHCN `by_year` CSVs are **headerless**, but the Fivetran S3 connector `personified_hither` was created with `empty_header=false`, so Fivetran consumed each yearly file's first data row as the header. Result: `observations` (186,963,714 rows) has columns named after data values (`ae_000041196`, `_20210101`…`_20240101`, `tmax/tmin/tavg`, `_278/_168/_204/_252`, flags `s`/`h`), each logical field scattered across per-file columns, and **`Q_FLAG` + `OBS_TIME` destroyed** (empty in row 1 → no column). This is the agent's reason to exist and the demo centerpiece. Snapshot `noaa_ghcn._observations_misparsed_snapshot` preserves the broken state.

### 0.3 FR status

| FR | Status | Notes |
|----|--------|-------|
| FR-01 Fivetran S3→BQ ingest | ✅ Done | Connector live; 186.9M rows synced (misparsed). |
| FR-02 Schema drift detection | ✅ Done | `detect_header_as_data_misparse` + `compare_schemas` + `build_reconstruction_mapping`; verified live (conf 0.99). |
| FR-03 Value parsing ambiguity | ✅ Adapted | Not K/M — instead tenths→SI conversion, `-9999`→NULL, **headerless-misparse reconstruction** via COALESCE. `observations_clean` built (186.9M rows, 76 elements). |
| FR-04 Event taxonomy 489→48 | ❌ Dropped | Storm-Events-specific; N/A for GHCN. |
| FR-05 Quarantine table | ⚠️ Partial | `_quarantine` + `_audit_log` DDL created, not yet populated. Q_FLAG-based quarantine **blocked by misparse** (Q_FLAG lost) → needs source re-sync. |
| FR-06 NL operator summary | ✅ Done | `format_pipeline_summary` + orchestrator prose; verified live. |
| FR-07 Memory Bank persistence | ❌ Not started | |
| FR-08 Operator chat interface | ✅ Done (local) | React+A2UI SPA in `frontend/` against local `adk api_server`; emits/renders A2UI v0.9. Hosted (Firebase) deploy deferred to Phase B. |
| FR-09 Observability (Trace/Logging) | ❌ Not started | No infra provisioned. |

**Bonus built (not in original plan):** Fivetran source-self-heal capability — `app/tools/fivetran_tool.py` (`fivetran_connector_status`, `fivetran_diagnose_csv_parsing`, `fivetran_fix_csv_header_config(confirm)`, `fivetran_resync(confirm)`), wired into `pipeline_controller`. Diagnoses `empty_header=false` root cause and can patch+resync to recover lost columns. Mutations gated behind `confirm=True`.

### 0.4 Verified working (runtime evidence)

- Agent runs end-to-end on Vertex (gemini-2.5-pro): orchestrator → sub-agent transfer → tools → live BQ/Fivetran → correct reasoning. Confirmed on two separate flows (schema-misparse diagnosis; pipeline-health check).
- `observations_clean`: 186,963,714 rows, 76 elements, 638K flagged (trace precip). Tenths conversions spot-checked (PRCP 25654→2565.4mm; SNOW whole-mm).
- 13 unit tests pass (`tests/unit/test_schema_comparator.py`, `test_notifier.py`); `ruff check` clean.

### 0.5 Next tasks — decided sequence (updated 2026-05-25)

Strategy: front-load free, reversible, high-value local work; batch all billable cloud
provisioning into one short window right before recording; **do not** re-sync (keep the
hero-bug demo intact). Eval (T11) is ✅ 6/6, observability code (T3b) is ✅ wired in
`fast_api_app.py` — only provisioning remains.

**Phase A — free local work (no cloud spend):**
1. **T9 code wiring** — wire `memory_service_uri` from an `AGENT_ENGINE_ID` env var into
   `get_fast_api_app`, add `load_memory` tool to the orchestrator, and write the GHCN
   domain-knowledge preload script (runs later once the engine exists). No provisioning yet.
2. **T10/T12 frontend** — ✅ DONE (local, against `adk api_server`). React (Vite) SPA in
   `stormpipe/frontend/` with a custom A2UI v0.9 renderer; agent emits `<a2ui-json>` via
   prompt-injection (`app/a2ui_setup.py`, gated by `A2UI_ENABLED`). Verified end-to-end:
   schema-drift query → live BigQuery → rendered Card+Tabs with working tab switching.
   **Deviation from original plan:** the official `@a2ui/react`/CopilotKit renderer path and
   the `SendA2uiToClientToolset` A2A path are both broken/coupled on the installed versions
   (a2a-sdk 1.x dropped `DataPart`; CopilotKit needs its own runtime endpoint), so we use
   prompt-injection + a focused custom renderer over the BasicCatalog subset. Firebase Hosting
   deploy of the static bundle is deferred to Phase B (needs `firebase` CLI, not installed).
   Run locally: `A2UI_ENABLED=1 … adk api_server --port 8042 --allow_origins http://localhost:5173`
   + `ADK_URL=http://127.0.0.1:8042 npm run dev` in `frontend/`.

**Phase B — ✅ DONE 2026-05-27 (billable provisioning):**
3. **T9 provision** — ✅ Agent Engine created via `vertexai.agent_engines.create()` (the
   `gcloud ai agent-engines` command does NOT exist in SDK 565). `AGENT_ENGINE_ID=4516136808706211840`.
   18 GHCN facts preloaded (scope user_id=`operator` to match the frontend). Required IAM:
   RE service agent → `roles/aiplatform.user` (Memory Bank embedding calls).
4. **T13 deploy** — ✅ deployed to **Cloud Run** (NOT Agent Runtime): the frontend uses
   ADK's `/run` REST API which only `fast_api_app` serves, and Cloud Run scales to zero.
   `https://stormpipe-mued7ds4ba-uc.a.run.app` (public via `allUsers` run.invoker, user-approved).
   Env: `A2UI_ENABLED=1`, `AGENT_ENGINE_ID`, `ALLOW_ORIGINS`. `otel_to_cloud` gated OFF
   (`OTEL_TO_CLOUD` env) — observability backend NOT provisioned (needs otel exporter pkgs).
5. ✅ Frontend pointed at Cloud Run via vite proxy (`ADK_URL=<cloud-url>`); smoke-tested
   end-to-end — schema-drift + DQ A2UI cards render from live BigQuery.

**Phase C — submit:**
6. **T14 demo video** (3 min) recorded with the hero bug **intact**, then Devpost submission.

**Deferred / do-not-run:** source re-sync (T1) + `_quarantine` populate (FR-05) — would
destroy the hero-bug demo. Only consider *after* the video is recorded, if at all; the
`_observations_misparsed_snapshot` already preserves the broken state regardless.

***

## 1. Product Requirements Document (PRD)

### 1.1 Problem Statement

Raw public datasets, especially multi-decade government archives like NOAA Storm Events, are notoriously difficult to operationalize. Teams waste days debugging Fivetran pipelines broken by upstream schema changes, undocumented column renames, mixed data types, and encoding anomalies. There is no intelligent agent today that can sit between a Fivetran pipeline and BigQuery, autonomously identify ambiguity at the source, reason about the correct remediation strategy, and execute it — all without human intervention.

### 1.2 Product Vision

**StormPipe** is a production-grade, multi-agent data engineering assistant that:
- Automatically connects NOAA Storm Events data (AWS S3 `noaa-swdi-pds` / `noaa-ghcn-pds`) to BigQuery via Fivetran
- Detects schema drift, type ambiguity, missing data patterns, and encoding inconsistencies autonomously
- Reasons about remediation and executes fixes through Fivetran MCP and BigQuery SQL tools
- Surfaces a natural-language pipeline health dashboard to operators
- Persists decisions and remediation history in Agent Memory Bank for continuous learning

### 1.3 Target User

**Data Engineering Teams** at insurance companies, climate risk analysts, catastrophe modelers, and municipal emergency management offices who need clean, reliable NOAA severe weather data in BigQuery for downstream ML and analytics.[^4]

### 1.4 Functional Requirements

| # | Requirement | Priority |
|---|-------------|----------|
| FR-01 | Fivetran S3 connector ingests NOAA Storm Events CSV files from `s3://noaa-swdi-pds` into BigQuery | Must |
| FR-02 | Agent detects schema drift between annual CSV files (column renames, additions, type changes) | Must |
| FR-03 | Agent resolves property damage value parsing ambiguity (`1.5K`, `1.5M`, `""`, nulls) | Must |
| FR-04 | Agent normalizes event type taxonomy (489 raw types → 48 official NOAA types) | Must |
| FR-05 | Agent flags and quarantines rows that fail validation into a `_quarantine` table in BigQuery | Must |
| FR-06 | Agent sends remediation decision + rationale to operator via a natural-language summary | Must |
| FR-07 | Pipeline decisions persisted to Agent Memory Bank for future drift prediction | Should |
| FR-08 | Agent exposes a chat interface for operators to query pipeline health in natural language | Should |
| FR-09 | Full observability via Cloud Trace, Cloud Logging integrated into Agent Runtime | Should |

### 1.5 Non-Functional Requirements

- **Availability:** Agent Runtime on Gemini Enterprise Agent Platform provides serverless, auto-scaling execution
- **Latency:** Pipeline health assessment returned within 30 seconds of sync completion trigger
- **Auditability:** Every agent decision logged with structured rationale in BigQuery audit table
- **Security:** IAM-controlled access via Google Cloud service accounts; Fivetran API credentials stored in Secret Manager

### 1.6 Judging Criteria Alignment

| Criterion | How StormPipe Wins |
|-----------|-------------------|
| **Technological Implementation** | Full-stack ADK 2.0 + Fivetran MCP + BigQuery + Agent Runtime — every technology used meaningfully, not decoratively |
| **Design** | Clean operator UX: one chat interface to understand entire pipeline health |
| **Potential Impact** | NOAA Storm Events powers $25K–$50K/yr catastrophe modeling subscriptions — this democratizes it[^4] |
| **Quality of Idea** | Novel: an agent that makes Fivetran pipelines self-healing on genuinely difficult public data |

***

## 2. Architecture

### 2.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        GEMINI ENTERPRISE AGENT PLATFORM                      │
│                                                                               │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │                    AGENT RUNTIME (Managed Serverless)                 │    │
│  │                                                                        │    │
│  │   ┌──────────────────────────────────────────────────────────────┐   │    │
│  │   │                  ROOT ORCHESTRATOR AGENT                      │   │    │
│  │   │              (ADK 2.0 LlmAgent + gemini-2.5-pro)             │   │    │
│  │   └────────┬───────────────────┬──────────────┬──────────────────┘   │    │
│  │            │                   │              │                        │    │
│  │   ┌────────▼──────┐  ┌─────────▼──────┐ ┌────▼───────────────┐      │    │
│  │   │  PIPELINE     │  │  SCHEMA DRIFT   │ │  DATA QUALITY      │      │    │
│  │   │  CONTROLLER   │  │  DETECTIVE      │ │  REMEDIATION       │      │    │
│  │   │  SUB-AGENT    │  │  SUB-AGENT      │ │  SUB-AGENT         │      │    │
│  │   └────────┬──────┘  └─────────┬──────┘ └────┬───────────────┘      │    │
│  │            │                   │              │                        │    │
│  │   ┌────────▼───────────────────▼──────────────▼───────────────────┐  │    │
│  │   │                         TOOL LAYER                             │  │    │
│  │   │  [Fivetran MCP]  [BigQuery Tool]  [Memory Bank]  [Notifier]   │  │    │
│  │   └────────────────────────────────────────────────────────────────┘  │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
│                                                                               │
│  ┌─────────────────────┐   ┌──────────────────┐   ┌───────────────────────┐  │
│  │  Agent Memory Bank  │   │  Sessions API     │   │  Agent Gateway        │  │
│  │  (Persistent state  │   │  (Multi-turn UI)  │   │  (Routing + Security) │  │
│  │   + drift history)  │   │                   │   │                        │  │
│  └─────────────────────┘   └──────────────────┘   └───────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
           │                           │
           ▼                           ▼
┌──────────────────┐        ┌──────────────────────────────────────┐
│  FIVETRAN         │        │  GOOGLE CLOUD BIGQUERY               │
│  (14-day trial)  │        │                                       │
│                  │        │  noaa_storm_events.details            │
│  S3 Connector    │◄──────►│  noaa_storm_events.locations          │
│  → BigQuery Dest │        │  noaa_storm_events.fatalities         │
│  Schema mgmt     │        │  noaa_storm_events._quarantine        │
│  Drift detection │        │  noaa_storm_events._audit_log         │
└──────────────────┘        └──────────────────────────────────────┘
           ▲
           │
┌──────────────────────────────────────────┐
│  AWS S3 Open Data (Public, no-auth read) │
│  s3://noaa-swdi-pds/                     │
│  ├── StormEvents_details-ftp_v1.0_YYYY   │
│  ├── StormEvents_locations-ftp_v1.0_YYYY │
│  └── StormEvents_fatalities-ftp_v1.0_YYYY│
└──────────────────────────────────────────┘
```

### 2.2 Agent Topology (Multi-Agent System)

**Root Orchestrator Agent** (`root_agent`)
- Model: `gemini-2.5-pro` via ADK 2.0
- Responsible for: receiving trigger events, routing to sub-agents, synthesizing final operator report
- Has access to: all sub-agents as tools, Memory Bank, Sessions

**Pipeline Controller Sub-Agent** (`pipeline_controller`)
- Model: `gemini-2.5-flash` (lower latency, cheaper)
- Responsible for: Fivetran connection management via MCP (list, trigger, pause, resume, status check)
- Tools: Fivetran MCP server tools — `list_connections`, `trigger_sync`, `check_sync_status`, `pause_connection`, `resume_connection`, `reload_schema`

**Schema Drift Detective Sub-Agent** (`schema_detective`)
- Model: `gemini-2.5-pro` (reasoning-intensive)
- Responsible for: comparing current BigQuery schema against expected schema, detecting new/removed/renamed columns, inferring if NOAA has changed file format across years
- Tools: BigQuery tool (schema introspection queries), Fivetran MCP `get_schema`, custom `compare_schema` tool

**Data Quality Remediation Sub-Agent** (`dq_remediator`)
- Model: `gemini-2.5-pro`
- Responsible for: parsing property damage values (`1.5K`, `1.5M`, `""`, nulls), normalizing event type names, identifying timezone issues, quarantining bad rows
- Tools: BigQuery tool (DML execution), custom transformation tools

### 2.3 Data Flow

```
1. Cloud Scheduler triggers → Root Agent via Agent Runtime REST endpoint
2. Root Agent → Pipeline Controller: "Check Fivetran status, trigger sync if needed"
3. Pipeline Controller calls Fivetran MCP: trigger_sync() → polls until complete
4. Root Agent → Schema Drift Detective: "Inspect schema changes since last run"
5. Schema Detective queries BigQuery INFORMATION_SCHEMA, calls Fivetran get_schema()
6. If drift detected → Root Agent reasons over findings → routes to DQ Remediator
7. DQ Remediator executes BigQuery SQL to fix/quarantine → writes to _audit_log
8. Root Agent stores decision in Memory Bank (what drift was detected + fix applied)
9. Root Agent generates natural-language health summary → returned via Sessions API
10. Operator queries agent via chat interface for pipeline status
```

***

## 3. Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Agent Framework** | ADK 2.0 (`google-adk>=2.0`) | Multi-agent orchestration, tool integration, session management |
| **Agentic Coding** | `google-agents-cli` + Claude Code | Scaffold, build, eval, and deploy via `uvx google-agents-cli setup` |
| **Agent Runtime** | Gemini Enterprise Agent Platform — Agent Runtime | Serverless, managed production deployment[^5] |
| **Memory** | Agent Platform Memory Bank | Persistent cross-session memory for drift history and decisions[^6] |
| **Sessions** | Agent Platform Sessions API | Multi-turn operator chat interface state management |
| **Observability** | Cloud Trace + Cloud Logging (via Agents CLI `infra`) | Traces per LLM call, tool execution spans[^7] |
| **Gateway** | Agent Gateway | Traffic routing, auth, rate limiting for the agent endpoint[^5] |
| **Pipeline Tool** | Fivetran MCP Server (`fivetran/fivetran-mcp`) | Agent-controlled Fivetran pipeline management[^8] |
| **Source** | AWS S3 Open Data — NOAA SWDI (`s3://noaa-swdi-pds`) | Public, no-auth, annual CSV files since 1950[^9] |
| **Pipeline** | Fivetran S3 Connector → BigQuery Destination | Automated ELT; schema drift detection built-in[^10][^11] |
| **Destination** | Google BigQuery | Analytics warehouse, DML execution for remediation |
| **Models** | Gemini 2.5 Pro (orchestrator/DQ) + Gemini 2.5 Flash (pipeline) | Via Vertex AI Model Garden |
| **Secrets** | Google Cloud Secret Manager | Fivetran API key/secret, GCP service account |
| **Scheduling** | Cloud Scheduler | Daily pipeline trigger |
| **IaC** | Terraform (via Agents CLI `infra` command) | Agent Runtime infra provisioning[^7] |

### Fivetran MCP Integration

The official Fivetran MCP server from `github.com/fivetran/fivetran-mcp` is integrated into Claude Code via `~/.claude.json`:[^8]

```json
{
  "mcpServers": {
    "fivetran": {
      "type": "stdio",
      "command": "uvx",
      "args": ["fivetran-mcp@latest"],
      "env": {
        "FIVETRAN_API_KEY": "${FIVETRAN_API_KEY}",
        "FIVETRAN_API_SECRET": "${FIVETRAN_API_SECRET}"
      }
    }
  }
}
```

The MCP server exposes tools for: listing connections, checking sync status, triggering syncs, historical resyncs, pause/resume, schema visibility, and reloading schemas. The Pipeline Controller sub-agent uses these tools directly via ADK's `MCPToolset`.[^8]

***

## 4. Dataset: NOAA Storm Events (Why It's Perfectly "Finicky")

### 4.1 Source Details

- **AWS S3 ARN:** `arn:aws:s3:::noaa-swdi-pds` (also cross-referenced with `noaa-ghcn-pds`)[^9]
- **Coverage:** January 1950 — present (February 2026 as of this writing)[^12]
- **License:** CC0-1.0 Public Domain — zero restrictions[^13]
- **File structure:** Three CSV files per year:
  - `StormEvents_details-ftp_v1.0_dYYYY*.csv.gz` — main event records
  - `StormEvents_locations-ftp_v1.0_dYYYY*.csv.gz` — geolocation data
  - `StormEvents_fatalities-ftp_v1.0_dYYYY*.csv.gz` — fatality records

### 4.2 Why This Dataset Requires an Agent

This dataset is the canonical example of real-world data engineering pain:

1. **Schema evolution across decades:** Major restructuring in 1993, 1996/97, 2000, and 2012. Records prior to 1993 were keyed from manually typed PDFs; 1993–1995 data came from WordPerfect 5.0 floppy diskettes. Column names, types, and presence vary by year.[^3]

2. **Property damage encoding chaos:** Values appear as `"1.5K"`, `"1.5M"`, `"1500"`, `""`, and `null` — sometimes all in the same file. There is no single canonical format. The agent must infer the intended numeric value and convert to a consistent representation.[^1]

3. **Event type taxonomy drift:** 489+ raw event type strings in the database that should map to 48 official NOAA event types. Non-standard types (e.g., `"TORNADO F0"` vs `"Tornado"`) still appear despite standardization efforts.[^1]

4. **Timezone inconsistency:** Pre-1993 SPC records were force-converted to CST; post-1993 records use local time zones. This creates silent cross-year join errors.[^3]

5. **Missing data at scale:** Damage reports are missing in more than half of all records. The agent must distinguish between "no damage occurred" (legitimately zero) and "damage was not recorded" (null/unknown).[^1]

6. **File prefix changes:** NOAA's NODD team is actively restructuring S3 prefixes (noted in the dataset README), meaning Fivetran S3 connector configurations can break on upstream changes.[^14]

### 4.3 Agent Remediation Strategies

| Anomaly | Agent Strategy |
|---------|---------------|
| Property damage `"1.5K"` | Parse suffix multiplier; write `1500.0` to `PROP_DAMAGE_CLEAN` column; flag source format in `PROP_DAMAGE_FORMAT` |
| Event type `"TORNADO F0"` | Fuzzy match against official 48-type taxonomy; if confidence > 0.85 remap; else quarantine with reasoning |
| Missing timezone indicator | Apply CST if year < 1993 and state = SPC-source; else keep as-is with flag |
| Schema column rename (e.g., `WFO` → `NWS_OFFICE`) | Detect via Fivetran `get_schema` + BigQuery `INFORMATION_SCHEMA`; add mapping alias; preserve old column |
| Null damage in high-magnitude event | Flag as `DATA_QUALITY = 'LIKELY_MISSING'` vs `'CONFIRMED_ZERO'` based on event type and magnitude |
| New year's CSV with new columns | Reload Fivetran schema; notify operator; apply net-additive integration strategy[^15] |

***

## 5. Detailed Specs

### 5.1 Project Structure (scaffolded by `google-agents-cli`)

```
stormpipe/
├── .agents-cli-spec.md           # Auto-generated by agents-cli
├── app/
│   ├── agent.py                  # Root orchestrator agent definition
│   ├── sub_agents/
│   │   ├── pipeline_controller.py
│   │   ├── schema_detective.py
│   │   └── dq_remediator.py
│   ├── tools/
│   │   ├── bigquery_tool.py      # Custom BigQuery DML + schema tools
│   │   ├── fivetran_mcp.py       # MCPToolset wrapper for Fivetran MCP
│   │   ├── notifier.py           # Operator summary generation
│   │   └── schema_comparator.py  # Schema diff logic
│   └── prompts/
│       ├── orchestrator.md
│       ├── schema_detective.md
│       └── dq_remediator.md
├── tests/
│   └── eval/
│       ├── evalsets/
│       │   ├── schema_drift.evalset.json
│       │   ├── damage_parsing.evalset.json
│       │   └── event_taxonomy.evalset.json
│       └── eval_config.json
├── infra/
│   └── main.tf                   # Agent Runtime infra via agents-cli infra
├── pyproject.toml
└── README.md
```

### 5.2 Core Agent Code (ADK 2.0)

```python
# app/agent.py
from google.adk.agents import LlmAgent
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, StdioServerParameters
from app.sub_agents.pipeline_controller import pipeline_controller_agent
from app.sub_agents.schema_detective import schema_detective_agent
from app.sub_agents.dq_remediator import dq_remediator_agent
from app.tools.bigquery_tool import bigquery_tool
from google.adk.memory import VertexAiMemoryBankService

# Fivetran MCP Toolset
fivetran_mcp = MCPToolset(
    connection_params=StdioServerParameters(
        command="uvx",
        args=["fivetran-mcp@latest"],
        env={
            "FIVETRAN_API_KEY": os.environ["FIVETRAN_API_KEY"],
            "FIVETRAN_API_SECRET": os.environ["FIVETRAN_API_SECRET"],
        }
    )
)

root_agent = LlmAgent(
    name="stormpipe_orchestrator",
    model="gemini-2.5-pro",
    description="""
        StormPipe Orchestrator: Manages end-to-end NOAA Storm Events
        pipeline health. Coordinates Fivetran ingestion, schema drift
        detection, and data quality remediation into BigQuery.
    """,
    instruction=open("app/prompts/orchestrator.md").read(),
    sub_agents=[
        pipeline_controller_agent,
        schema_detective_agent,
        dq_remediator_agent,
    ],
    tools=[bigquery_tool],
    memory_service=VertexAiMemoryBankService(
        project=PROJECT_ID,
        location=LOCATION,
        agent_engine_id=AGENT_ENGINE_ID,
    ),
)
```

### 5.3 Schema Drift Detective Prompt (Key Intelligence)

```markdown
# Schema Drift Detective

You are an expert data engineer specializing in NOAA Storm Events data quality.

Given:
- Current BigQuery schema (from INFORMATION_SCHEMA query)
- Expected Fivetran connector schema (from fivetran get_schema tool)
- Historical schema fingerprint from Memory Bank

Your job:
1. Identify any NEW columns in the source not yet in BigQuery
2. Identify any MISSING columns that existed in BigQuery but not source
3. Identify any TYPE CHANGES (e.g., VARCHAR → INTEGER)
4. Cross-reference against known NOAA schema change history:
   - Pre-1993: SPC format (limited columns, CST forced)
   - 1993-1995: WordPerfect-derived (inconsistent field widths)
   - 1996-2012: FoxPro-imported (event type free text, damage in K/M)
   - 2012-present: Structured (standardized types, but still K/M damage)

For each detected drift:
- Classify as: ADDITIVE | DESTRUCTIVE | TYPE_CHANGE | RENAME | ENCODING
- Recommend: ACCEPT | QUARANTINE | REMAP | ALERT_OPERATOR
- Confidence score: 0.0 - 1.0

Output structured JSON with your findings and call dq_remediator if confidence > 0.7.
```

### 5.4 Fivetran → BigQuery Pipeline Configuration

**Fivetran S3 Connector Config** (via MCP `create_connection` or REST API):[^16]

```json
{
  "service": "s3",
  "group_id": "<FIVETRAN_GROUP_ID>",
  "sync_frequency": 1440,
  "config": {
    "bucket": "noaa-swdi-pds",
    "access_approach": "PUBLIC_BUCKET",
    "prefix": "csv/",
    "file_type": "csv",
    "compression": "gzip",
    "pattern": "StormEvents_details-ftp_v1\\.0_d\\d{4}.*\\.csv\\.gz",
    "on_error": "skip",
    "destination_schema_names": "FIVETRAN_NAMING",
    "file_mapping_method": "EXTRACT_TABLES"
  }
}
```

**BigQuery Destination Tables:**

| Table | Description |
|-------|-------------|
| `noaa_storm_events.details` | Main ingested event records (raw from Fivetran) |
| `noaa_storm_events.details_clean` | Agent-remediated clean records |
| `noaa_storm_events.locations` | Geolocation data |
| `noaa_storm_events.fatalities` | Fatality records |
| `noaa_storm_events._quarantine` | Rows failing quality checks + agent rationale |
| `noaa_storm_events._audit_log` | Agent decisions, timestamps, confidence scores |
| `noaa_storm_events._schema_history` | Historical schema fingerprints per sync run |

### 5.5 Deployment via Agents CLI + Agent Runtime

The full deployment flow uses `google-agents-cli` with Claude Code as the agentic coder:[^7][^17][^18]

```bash
# Step 1: Install Agents CLI
uvx google-agents-cli setup

# Step 2: Open Claude Code (with Agents CLI skills installed)
claude

# Step 3: Ask Claude Code to scaffold
# "Use agents-cli to build a multi-agent data pipeline health agent
#  called stormpipe that uses Fivetran MCP to manage NOAA S3→BigQuery
#  pipelines with schema drift detection, deploy to agent_runtime"

# agents-cli scaffolds:
agents-cli create stormpipe --deployment-target agent_runtime --yes
cd stormpipe && agents-cli install

# Step 4: Development loop (Claude Code drives this)
agents-cli playground  # local dev at localhost:8080

# Step 5: Run evaluations
agents-cli eval run  # runs schema_drift, damage_parsing, event_taxonomy evals

# Step 6: Deploy to Agent Runtime
agents-cli scaffold enhance --deployment-target agent_runtime
agents-cli deploy

# Step 7: Set up observability infra (BigQuery + GCS for traces)
# Claude Code runs:
agents-cli infra single-project

# Step 8: Register with Gemini Enterprise (via google-agents-cli-publish skill)
# agents-cli publish  (makes agent discoverable in Gemini Enterprise)
```

**Agent Runtime deployment** provides serverless scaling, built-in Cloud Trace integration, managed sessions, and IAM-controlled API endpoint. No Docker or Kubernetes configuration needed.[^5]

### 5.6 Memory Bank Integration

The Memory Bank enables the agent to learn from past pipeline runs:[^6][^19]

```python
# After each remediation cycle, store findings
memory_client.generate_memories(
    agent_engine_id=AGENT_ENGINE_ID,
    session_id=current_session_id,
    # Memories auto-extracted from conversation:
    # "StormEvents 2024 CSV added column FLOOD_CAUSE with mixed null rate 67%"
    # "Property damage in K/M format detected in years 1993-2011, normalized"
    # "Event type 'MARINE THUNDERSTORM WIND' maps to official type 'Marine Thunderstorm Wind'"
)

# At start of next run, retrieve relevant memories
memories = memory_client.fetch_memories(
    agent_engine_id=AGENT_ENGINE_ID,
    query="NOAA Storm Events schema changes property damage encoding"
)
# Agent uses these to predict issues BEFORE they cause failures
```

This creates a **self-improving pipeline agent** — the more it runs, the fewer issues it hits blind.

### 5.7 Evaluation Test Cases (for `agents-cli eval run`)

**Schema Drift Eval Set** (`schema_drift.evalset.json`):
```json
[
  {
    "query": "New column 'FLOOD_CAUSE' appeared in 2024 CSV but not in BigQuery schema. What do you do?",
    "expected_tool_calls": ["get_schema", "bigquery_introspect_schema"],
    "criteria": "Agent recommends ADDITIVE integration and reloads schema via Fivetran MCP"
  },
  {
    "query": "Column 'DAMAGE_PROPERTY' changed from VARCHAR to NULL across 47% of rows in 1993 data",
    "criteria": "Agent classifies as ENCODING anomaly, applies K/M parser, quarantines remainder"
  }
]
```

**Damage Parsing Eval Set** (`damage_parsing.evalset.json`):
```json
[
  {
    "query": "Parse these property damage values: ['1.5K', '1.5M', '', '0', NULL, '500', '2.5B']",
    "criteria": "Agent returns [1500, 1500000, null, 0, null, 500, 2500000000] with format annotations"
  }
]
```

***

## 6. Development Timeline (Hackathon Sprint)

| Day | Focus | Deliverable |
|-----|-------|-------------|
| **Day 1 AM** | Environment setup | Fivetran 14-day trial, GCP project, Agents CLI installed, BigQuery dataset created |
| **Day 1 PM** | Fivetran pipeline | S3 connector to `noaa-swdi-pds` → BigQuery working; first sync of 2020-2024 data |
| **Day 2 AM** | ADK scaffolding | `agents-cli create stormpipe` + Fivetran MCP wired into Pipeline Controller |
| **Day 2 PM** | Schema Detective | Sub-agent detecting column renames and type changes between 1990s and 2020s files |
| **Day 3 AM** | DQ Remediator | Damage value parser + event type taxonomy normalizer working in BigQuery |
| **Day 3 PM** | Memory Bank | Persistent drift history; agent predicts known issues on second run |
| **Day 4 AM** | Evals + polish | `agents-cli eval run` passes; observability infra provisioned |
| **Day 4 PM** | Deployment + demo | `agents-cli deploy` to Agent Runtime; 3-minute demo video recorded |

### Demo Video Script (3 minutes)

1. **(0:00–0:30)** Problem: Show raw NOAA Storm Events CSV with mixed `"1.5K"/"1.5M"/""` damage values and inconsistent event types. "This is what real public data looks like."
2. **(0:30–1:00)** Pipeline: Show Fivetran S3 connector syncing to BigQuery. Deliberately introduce a schema change (new column in latest year's CSV). Fivetran sync completes.
3. **(1:00–1:45)** Agent in action: StormPipe agent triggered. Show Agent trace in Cloud Console: Schema Detective detects drift → DQ Remediator normalizes damage values → quarantine table populated with rationale → audit log written.
4. **(1:45–2:30)** Operator chat: Ask agent "What happened in last night's sync?" — receives natural-language summary. Ask "How many events were quarantined and why?" — agent queries BigQuery and explains.
5. **(2:30–3:00)** Close with BigQuery showing clean `details_clean` table vs messy `details` table. Memory Bank showing accumulated drift knowledge. Agent Runtime dashboard showing zero infrastructure management needed.

***

## 7. Why This Wins

**Technological Implementation:** The stack uses every judging-relevant technology genuinely and correctly — ADK 2.0 multi-agent orchestration, Fivetran MCP for agent-controlled pipeline management, BigQuery as destination with DML-executing tools, Agent Runtime for production deployment, Memory Bank for persistent state, and `google-agents-cli` with Claude Code for the full agentic coding workflow.[^20][^17][^5][^6]

**Design:** The UX is deliberately simple — one natural language chat interface hides the complexity of multi-agent orchestration. Operators don't need to know how the agent works; they just ask "is my pipeline healthy?"

**Potential Impact:** NOAA Storm Events data underpins catastrophe modeling products that cost $25,000–$50,000/year. A self-healing, agentic pipeline for this data is genuinely valuable to the insurance, municipal government, and climate finance sectors that currently struggle with it. Academic research confirms the dataset "should not be used without appropriate precautions" — StormPipe automates exactly those precautions.[^21][^4][^1]

**Quality of Idea:** No existing Fivetran agent demo uses a genuinely difficult public dataset with documented multi-decade schema evolution and requires the agent to reason under real ambiguity. This is not a toy use case — it's the kind of data engineering problem that delays production deployments by weeks at real companies.

***

## 9. UI/UX Design with ADK A2UI

### 9.1 What is A2UI and Why It's Perfect Here

A2UI is Google's open protocol (v0.9, Apache 2.0) that lets ADK agents generate rich, declarative user interfaces — cards, tables, charts, status indicators, forms — directly from the agent's response, without any per-layout frontend code changes. Instead of returning walls of text, the agent composes layouts from **18 UI primitives** (Card, Column, Row, List, Tabs, Text, Icon, Button, TextField, etc.) and the client renders them natively using its own components. This is architecturally ideal for StormPipe: the operator gets a different UI for every intent (pipeline health overview vs. a quarantine drill-down vs. a schema diff) driven by the agent, not hardcoded templates.[^22][^23][^24]

A2UI separates structure (`surfaceUpdate`) from data (`dataModelUpdate`), enabling incremental streaming updates — the pipeline status card can refresh in real time as the Fivetran sync progresses without re-rendering the entire page.[^23][^22]

### 9.2 StormPipe UI/UX Design System

#### Core Screens

| Screen | A2UI Layout | Key Components |
|--------|------------|----------------|
| **Pipeline Health Overview** | Column → Row of status Cards | Icon (🟢🟡🔴) + Text (event count, sync time) + Button ("Inspect") |
| **Schema Drift Alert** | Tabs (Current / Expected / Diff) | Row per column: Icon + Text (old name → new name) + MultipleChoice (ACCEPT / QUARANTINE / REMAP) |
| **Damage Value Audit** | List of Card rows | Text (raw value) + Icon (format tag) + Text (parsed value) + confidence Slider indicator |
| **Quarantine Explorer** | Tabs (By Rule / By Year / By Event Type) | List + Card + Button ("Release" / "Delete") |
| **Memory Bank History** | Column timeline | Card per past run: Icon (calendar) + Text (drift summary) + Button ("Re-apply fix") |
| **Natural Language Chat** | Column (sticky bottom TextField) | TextField (ask anything) + streaming Text responses with A2UI inline cards |

#### Visualization Best Practices

**Status at a glance:** Every pipeline and table health state uses a consistent traffic-light icon system (`Icon` primitive with `color` binding from data model). Operators parse pipeline health in under 2 seconds without reading text.[^23]

**Progressive disclosure:** The overview shows one Card per BigQuery table. Clicking "Inspect" (Button → agent action) triggers a sub-agent query that re-renders the surface with a detailed `Tabs` breakdown — users only see depth when they need it.

**Data-to-ink ratio:** Schema diff views use a `Row` with three columns (column name, old type, new type) and inline `Icon` (✅ compatible / ⚠️ breaking). No decorative elements — every pixel carries signal.

**Streaming updates:** Because A2UI separates structure from data, the agent can push `dataModelUpdate` messages mid-sync to update row counts and percentages in real time without re-sending the full component tree — creating a live dashboard feel at minimal cost.[^22]

**Error + empty states:** Quarantine table zero-state renders a `Card` with `Icon` (checkmark) + `Text` ("No rows quarantined — pipeline is clean"). Users are never left staring at a blank panel.

### 9.3 A2UI Integration with ADK Agent

Following the official A2UI + ADK codelab pattern:[^23]

```python
# app/agent.py — add A2UI to root orchestrator
from a2ui.schema.manager import A2uiSchemaManager
from a2ui.basic_catalog.provider import BasicCatalog
from app.a2ui_utils import a2ui_callback  # streaming wrapper

schema_manager = A2uiSchemaManager(
    version="0.9",
    catalogs=[BasicCatalog.get_config("0.9")],
)

ui_instruction = schema_manager.generate_system_prompt(
    role_description="You are StormPipe, an agentic data pipeline health assistant.",
    workflow_description=(
        "When asked about pipeline health, schema drift, data quality, or "
        "quarantine status, retrieve data via tools and render structured UI."
    ),
    ui_description=(
        "Pipeline health: use Cards with traffic-light Icons (status binding). "
        "Schema diffs: use Tabs with Rows showing old→new column mappings. "
        "Quarantine rows: use List of Cards with confidence score and MultipleChoice remediation. "
        "Damage value parsing: use Cards with raw/parsed/format Text trio. "
        "Use Button components for all drill-down and action triggers. "
        "Stream dataModelUpdate for live sync progress. "
        "Never use markdown in Text values — use usageHint for h1/h2/h3. "
        "Respond ONLY with A2UI JSON array."
    ),
    include_schema=True,
    include_examples=True,
)

root_agent = LlmAgent(
    name="stormpipe_orchestrator",
    model="gemini-2.5-pro",
    instruction=ui_instruction,
    after_model_callback=a2ui_callback,  # converts JSON → rendered components
    sub_agents=[pipeline_controller_agent, schema_detective_agent, dq_remediator_agent],
    tools=[bigquery_tool],
    memory_service=memory_bank,
)
```

The `a2ui_callback` (from the official codelab) intercepts the agent's JSON response and wraps each A2UI message into the `application/json+a2ui` blob format that the ADK web renderer expects.[^23]

### 9.4 Production Frontend: React + Cloud Run (Firebase Hosting)

For the hackathon demo, `adk web` renders A2UI natively in development. For the production frontend (the hosted demo URL submitted to Devpost), the optimal GCP deployment is:

#### Option A — Firebase Hosting (Most Cost-Effective for Frontend)

The React frontend (`@a2ui/react` renderer) is built to a static bundle and deployed to **Firebase Hosting** — Google's global CDN with a generous free tier (10 GB/month transfer, 1 GB storage). Firebase Hosting handles HTTPS automatically, serves globally from CDN edge nodes, and costs **$0** for hackathon-scale traffic.[^25]

```bash
# Build React frontend with A2UI renderer
npm install @a2ui/react
npm run build

# Deploy to Firebase Hosting (free tier)
firebase init hosting
firebase deploy --only hosting
```

The frontend connects to the Agent Runtime REST endpoint (on Gemini Enterprise Agent Platform) via the Sessions API for multi-turn state.[^5]

#### Option B — Cloud Run (min-instances=0, Fullstack)

If the demo needs server-side rendering or an API proxy layer (to avoid CORS and hide credentials), deploy the ADK `api_server` + static frontend together on a single **Cloud Run** service with `min-instances=0`:[^26][^27]

```bash
# Cloud Run with scale-to-zero (only billed when requests hit)
gcloud run deploy stormpipe-ui \
  --source . \
  --region asia-southeast1 \
  --min-instances 0 \
  --max-instances 3 \
  --memory 512Mi \
  --cpu 1 \
  --allow-unauthenticated
```

With `min-instances=0`, Cloud Run scales to zero between requests — the service costs **$0 when idle**, billing only per 100ms of actual request processing. For a hackathon demo with intermittent traffic, the entire frontend hosting cost is well under $1.[^28][^29]

#### Recommended: Firebase Hosting (frontend) + Agent Runtime (backend)

| Component | Service | Cost |
|-----------|---------|------|
| React A2UI frontend | Firebase Hosting | $0 (free tier) |
| Agent Runtime endpoint | Gemini Enterprise Agent Platform | Pay-per-call |
| BigQuery queries | BigQuery | $0 (< 1 TB/mo free) |
| Cloud Run (API proxy, optional) | Cloud Run min=0 | ~$0 at hackathon scale |

### 9.5 Full Frontend Architecture

```
Firebase Hosting (CDN, global edge)
├── React SPA
│   ├── @a2ui/react renderer (18 primitives, native styling)
│   ├── Pipeline Health Dashboard (A2UI Cards + Icons)
│   ├── Schema Drift Explorer (A2UI Tabs + Rows)
│   ├── Quarantine Manager (A2UI List + MultipleChoice)
│   ├── Memory Bank Timeline (A2UI Column + Cards)
│   └── Chat Interface (A2UI TextField + streaming Text)
│
└── AG-UI transport layer
    └── SSE stream to → Agent Runtime REST endpoint
                              (Gemini Enterprise Agent Platform)
                                        │
                          ADK 2.0 Root Orchestrator
                          (with A2UI after_model_callback)
```

The React frontend uses **AG-UI** (CopilotKit's transport layer, day-0 A2UI compatible) to handle SSE streaming from the Agent Runtime endpoint, feed A2UI JSON to the `@a2ui/react` renderer, and manage multi-turn session state. This eliminates the need for a custom WebSocket server — AG-UI handles streaming protocol bridging out of the box.[^22]

***

## 8. Setup Checklist

- [x] Create Fivetran 14-day free trial at `fivetran.com/signup`
- [x] Generate Fivetran API Key + Secret from Fivetran Dashboard
- [x] Create GCP project (`stormpipe-hackathon`), enable BigQuery API, Agent Platform API, Secret Manager API
- [x] Store Fivetran credentials in Secret Manager: `FIVETRAN_API_KEY`, `FIVETRAN_API_SECRET`
- [x] Run `uvx google-agents-cli setup` to install Agents CLI + skills
- [x] Configure Fivetran MCP in `~/.claude.json` for Claude Code
- [x] Create Fivetran BigQuery destination (`unconcerned_sweat`, connected)
- [x] Create Fivetran S3 connector (`personified_hither`) — points to `noaa-ghcn-pds` (NOT `noaa-swdi-pds`; see §0.1)
- [x] Run first sync to validate data landing in BigQuery (186.9M rows; misparsed — see §0.2)
- [x] Open Claude Code and scaffold the `stormpipe` ADK project
- [ ] Provision observability infra (`agents-cli infra single-project`) — FR-09
- [ ] Deploy to Agent Runtime (`agents-cli deploy`) — needs human approval
- [ ] Submit to Devpost with public GitHub repo (Apache 2.0 license), hosted agent URL, and 3-minute demo video

---

## References

1. [Some Comments on the Reliability of NOAA's Storm Events Database](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2799273) - Storms and other severe weather events can result in fatalities, injuries, and property damage. Ther...

2. [Storm Events Database](https://www.ncei.noaa.gov/stormevents/versions.jsp) - The Storm Events Database contains records on various types of severe weather, as collected by NOAA'...

3. [Storm Events Database | National Centers for Environmental ...](https://www.ncei.noaa.gov/stormevents/details.jsp?type=collection) - The Storm Events Database contains records on various types of severe weather, as collected by NOAA'...

4. [NOAA Storm Events Diff API — Damage Revisions for Cat Modeling](https://apify.com/changewire/noaa-storm-events-diff/api/openapi) - Per-event diff of the NOAA NCEI Storm Events Database. Detects damage / fatality / F-scale / narrati...

5. [Scale your agents | Gemini Enterprise Agent Platform](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale) - Serverless efficiency: Utilizing a fully managed Agent Runtime to deploy and scale agents efficientl...

6. [How to build AI agents with long-term memory using Vertex AI ...](https://discuss.google.dev/t/how-to-build-ai-agents-with-long-term-memory-using-vertex-ai-memory-bank-adk/193013) - Getting started with Vertex AI Memory Bank with ADK · Step 1: Create the Agent Engine Instance · Ste...

7. [Tutorial: Build Your First Agent - agents-cli - Google](https://google.github.io/agents-cli/guide/quickstart-tutorial/) - This tutorial shows the full Agents CLI in Agent Platform experience — you talk to your coding agent...

8. [fivetran-mcp 0.2.0 on PyPI - Libraries.io](https://libraries.io/pypi/fivetran-mcp) - MCP server for Fivetran API - manage syncs, check status, and control connections

9. [NOAA Severe Weather Data Inventory (SWDI)](https://registry.opendata.aws/noaa-swdi/) - The Storm Events Database is an integrated database of severe weather events across the United State...

10. [Amazon S3 bucket to warehouse | Fivetran setup guide](https://fivetran.com/docs/connectors/files/amazon-s3/setup-guide) - Set up Fivetran for Amazon S3 buckets.

11. [Amazon S3 Data ETL to your warehouse - Fivetran](https://www.fivetran.com/connectors/amazon-s3) - Amazon S3 offers industry-leading scalability, data availability, and performance for your storage n...

12. [Storm Events Database](https://www.ncei.noaa.gov/stormevents/) - The Storm Events Database contains records on various types of severe weather, as collected by NOAA'...

13. [NOAA Global Historical Climatology Network Daily (GHCN-D)](https://registry.opendata.aws/noaa-ghcn/) - A dataset from NOAA that contains daily observations over global land areas. It contains station-bas...

14. [open-data-registry/datasets/noaa-ghcn.yaml at main - GitHub](https://github.com/awslabs/open-data-registry/blob/main/datasets/noaa-ghcn.yaml) - A dataset from NOAA that contains daily observations over global land areas. It contains station-bas...

15. [Reliable Data Replication in the Face of Schema Drift | Blog | Fivetran](https://www.fivetran.com/blog/reliable-data-replication-in-the-face-of-schema-drift) - Learn methods for ensuring that data replication remains robust even as schemas change.

16. [API Configuration for Amazon S3 - Fivetran](https://fivetran.com/docs/connectors/files/amazon-s3/api-configuration) - Read step-by-step instructions on how to connect Amazon S3 with your destination using Fivetran conn...

17. [Getting Started - agents-cli - Google](https://google.github.io/agents-cli/guide/getting-started/) - Agents CLI in Agent Platform is a CLI and skills package for building, evaluating, and deploying AI ...

18. [Build an agent with ADK and Agents CLI in Agent Platform](https://docs.cloud.google.com/gemini-enterprise-agent-platform/agents/quickstart-adk) - This document demonstrates how to build, evaluate, and deploy a prototype AI agent using the Agent D...

19. [Remember this: Agent state and memory with ADK](https://cloud.google.com/blog/topics/developers-practitioners/remember-this-agent-state-and-memory-with-adk) - Explore ADK's session and memory storage options, including SQL databases and Vertex AI Agent Engine...

20. [Agents CLI in Agent Platform: create to production in one CLI](https://developers.googleblog.com/agents-cli-in-agent-platform-create-to-production-in-one-cli/) - Agents CLI is a specialized tool designed specifically for AI coding agents (like Gemini CLI, Claude...

21. [AWS hosts new open dataset to help businesses identify ...](https://aws.amazon.com/blogs/publicsector/aws-hosts-new-open-dataset-help-businesses-identify-climate-finance-risks-investments/) - Amazon is announcing today that the Legal Entity Identifier (LEI) dataset is now available at no cos...

22. [Introducing A2UI: An open project for agent-driven interfaces](https://developers.googleblog.com/introducing-a2ui-an-open-project-for-agent-driven-interfaces/) - A2UI allows agents to generate the interface which best suits the current conversation with the agen...

23. [Frontend Experiences with ADK and A2UI | Google Codelabs](https://codelabs.developers.google.com/next26/adk-a2ui) - No new frontend code needed per layout. This codelab uses the Agent Development Kit (ADK) to build t...

24. [A2UI v0.9: The New Standard for Portable, Framework ...](https://developers.googleblog.com/a2ui-v0-9-generative-ui/) - This release focuses on making it easier than ever to build agents and integrate with your existing ...

25. [Pros and Cons of hosting a static website on GCS](https://discuss.google.dev/t/pros-and-cons-of-hosting-a-static-website-on-gcs/163431) - You could utilize Cloud Run for that and pay only for traffic ( Cloud Run will scale down to zero if...

26. [Build and deploy an AI agent to Cloud Run using the Agent ...](https://docs.cloud.google.com/run/docs/ai/build-and-deploy-ai-agents/deploy-adk-agent) - Build and deploy an AI agent to Cloud Run using the Agent Development Kit (ADK)

27. [Single-agent AI system using ADK and Cloud Run](https://docs.cloud.google.com/architecture/single-agent-ai-system-adk-cloud-run) - This document provides a reference architecture to help you design a single-agent AI system on Googl...

28. [Google Cloud Run Cost : r/googlecloud - Reddit](https://www.reddit.com/r/googlecloud/comments/1brhv5h/google_cloud_run_cost/) - If you keep 1 instance minimum, you will not make it using the free tier . You will probably cover 5...

29. [Cloud Run pricing | Google Cloud](https://cloud.google.com/run/pricing) - Cloud Run charges you only for the resources you use, rounded up to the nearest 100 millisecond. You...

