"""Preload GHCN-Daily domain knowledge into the Vertex AI Memory Bank.

Run once, after the Agent Engine is provisioned (Phase B):

    AGENT_ENGINE_ID=<id> GOOGLE_CLOUD_PROJECT=stormpipe-hackathon \
    GOOGLE_CLOUD_LOCATION=us-central1 \
    .venv/bin/python -m scripts.preload_memories

Facts are written under a fixed scope (app_name + user_id). The orchestrator's
`load_memory` tool retrieves memories scoped to the *current* session's app_name and
user_id, so MEMORY_SCOPE_USER_ID here must match the user_id the agent runs under for
the preloaded facts to be visible.
"""

import asyncio
import os

from google.genai import types

from app.tools.schema_comparator import (
    CANONICAL_COLUMNS,
    ELEMENT_UNITS,
    MEASUREMENT_FLAGS,
    MISSING_VALUE_SENTINEL,
    QUALITY_FLAGS,
)

APP_NAME = os.environ.get("MEMORY_SCOPE_APP_NAME", "app")
USER_ID = os.environ.get("MEMORY_SCOPE_USER_ID", "stormpipe")


def _facts() -> list[str]:
    facts = [
        "The canonical NOAA GHCN-Daily observation schema has 8 columns in order: "
        + ", ".join(CANONICAL_COLUMNS)
        + ". ID is the station id, DATE is YYYYMMDD, ELEMENT is the measurement code, "
        "DATA_VALUE is the reading.",
        "NOAA GHCN-Daily by_year CSV files live at "
        "s3://noaa-ghcn-pds/csv.gz/by_year/ and are HEADERLESS — the first line is "
        "already data, not column names.",
        f"In GHCN-Daily a DATA_VALUE of {MISSING_VALUE_SENTINEL} is the missing-value "
        "sentinel and must be treated as NULL, not a real reading.",
        "The StormPipe hero bug: the Fivetran S3 connector was configured with "
        "empty_header=false against the headerless by_year files, so Fivetran consumed "
        "each file's first data row as the header. The result is a mangled observations "
        "table whose columns are named after data values (station ids, dates, element "
        "codes, bare readings). Q_FLAG and OBS_TIME were empty in those header rows and "
        "were destroyed entirely. The source fix is empty_header=true followed by a full "
        "re-sync; the in-warehouse fix reconstructs the canonical columns by COALESCE-ing "
        "the scattered per-file columns.",
        "GHCN measurement flag M_FLAG='T' means a trace of precipitation, snowfall, or "
        "snow depth — a real zero-ish reading, not missing data.",
    ]
    for element, (desc, divisor, unit) in ELEMENT_UNITS.items():
        if divisor != 1.0:
            facts.append(
                f"GHCN element {element} DATA_VALUE is stored in {desc}; "
                f"divide by {divisor:g} to get {unit}."
            )
        else:
            facts.append(f"GHCN element {element} DATA_VALUE is already in {unit}.")
    facts.append(
        "GHCN Q_FLAG quality codes: "
        + "; ".join(f"{k}={v}" for k, v in QUALITY_FLAGS.items())
        + ". A non-empty Q_FLAG means the value failed a quality check."
    )
    facts.append(
        "GHCN M_FLAG measurement codes: "
        + "; ".join(f"{k}={v}" for k, v in MEASUREMENT_FLAGS.items())
        + "."
    )
    return facts


async def main() -> None:
    agent_engine_id = os.environ.get("AGENT_ENGINE_ID")
    if not agent_engine_id:
        raise SystemExit("AGENT_ENGINE_ID is not set — provision the Agent Engine first.")

    from google.adk.memory.memory_entry import MemoryEntry
    from google.adk.memory.vertex_ai_memory_bank_service import (
        VertexAiMemoryBankService,
    )

    service = VertexAiMemoryBankService(
        project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
        location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
        agent_engine_id=agent_engine_id,
    )

    memories = [
        MemoryEntry(
            author="stormpipe_preload",
            content=types.Content(role="user", parts=[types.Part(text=fact)]),
        )
        for fact in _facts()
    ]
    await service.add_memory(app_name=APP_NAME, user_id=USER_ID, memories=memories)
    print(f"Preloaded {len(memories)} GHCN domain memories "
          f"(scope: app_name={APP_NAME!r}, user_id={USER_ID!r}).")


if __name__ == "__main__":
    asyncio.run(main())
