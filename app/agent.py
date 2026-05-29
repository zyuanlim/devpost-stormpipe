# ruff: noqa
import os

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.tools import load_memory
from google.genai import types

from app.sub_agents.pipeline_controller import pipeline_controller_agent
from app.sub_agents.schema_detective import schema_detective_agent
from app.sub_agents.dq_remediator import dq_remediator_agent
from app.tools.bigquery_tool import (
    bigquery_run_query,
    bigquery_list_tables,
    bigquery_get_schema,
)
from app.tools.notifier import format_pipeline_summary
from app.a2ui_setup import a2ui_enabled, a2ui_system_prompt

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "stormpipe-hackathon")
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

os.environ["GOOGLE_CLOUD_PROJECT"] = PROJECT
os.environ["GOOGLE_CLOUD_LOCATION"] = LOCATION
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"

# ADK eval (`adk eval`) imports this module twice: once under a synthetic
# package name and again as the real `app` package via the absolute imports
# above. The sub_agent objects are module-level singletons shared across both,
# so the second build hits "already has a parent agent". Detach before
# building to keep the import idempotent.
for _sub_agent in (
    pipeline_controller_agent,
    schema_detective_agent,
    dq_remediator_agent,
):
    _sub_agent.parent_agent = None

# The A2UI schema prompt is full of literal `{}` (JSON schema), which ADK's
# `instruction` templating would try to resolve as session-state variables.
# `static_instruction` is not templated (and is cache-friendly), so the schema
# goes there while orchestrator.md stays as the templated instruction.
#
# Because the orchestrator auto-transfers to a sub-agent and that sub-agent then
# produces the user-facing turn, every agent that can answer the operator needs
# the A2UI instruction — otherwise a delegated answer comes back as plain text.
_static_instruction = a2ui_system_prompt() if a2ui_enabled() else None
if _static_instruction is not None:
    for _sub_agent in (
        pipeline_controller_agent,
        schema_detective_agent,
        dq_remediator_agent,
    ):
        _sub_agent.static_instruction = _static_instruction

root_agent = Agent(
    name="stormpipe_orchestrator",
    model=Gemini(
        model="gemini-3.5-flash",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    description=(
        "StormPipe: Agentic data pipeline health assistant for NOAA GHCN-Daily "
        "weather data. Manages Fivetran S3→BigQuery pipeline, detects schema drift, "
        "remediates data quality issues, and answers operator questions."
    ),
    instruction=open("app/prompts/orchestrator.md").read(),
    static_instruction=_static_instruction,
    sub_agents=[
        pipeline_controller_agent,
        schema_detective_agent,
        dq_remediator_agent,
    ],
    tools=[
        bigquery_run_query,
        bigquery_list_tables,
        bigquery_get_schema,
        format_pipeline_summary,
        load_memory,
    ],
)

# Name must match the agent package directory ("app") so the api_server runner
# and session storage agree; the deploy resource name lives in
# agents-cli-manifest.yaml.
app = App(
    root_agent=root_agent,
    name="app",
)
