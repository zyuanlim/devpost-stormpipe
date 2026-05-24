# ruff: noqa
import os

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
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

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "stormpipe-hackathon")
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

os.environ["GOOGLE_CLOUD_PROJECT"] = PROJECT
os.environ["GOOGLE_CLOUD_LOCATION"] = LOCATION
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"

root_agent = Agent(
    name="stormpipe_orchestrator",
    model=Gemini(
        model="gemini-2.5-pro",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    description=(
        "StormPipe: Agentic data pipeline health assistant for NOAA GHCN-Daily "
        "weather data. Manages Fivetran S3→BigQuery pipeline, detects schema drift, "
        "remediates data quality issues, and answers operator questions."
    ),
    instruction=open("app/prompts/orchestrator.md").read(),
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
    ],
)

app = App(
    root_agent=root_agent,
    name="stormpipe",
)
