"""Schema Drift Detective sub-agent — detects GHCN-Daily schema changes."""

from google.adk.agents import Agent
from google.adk.models import Gemini

from app.tools.bigquery_tool import (
    bigquery_get_schema,
    bigquery_list_tables,
    bigquery_run_query,
)
from app.tools.schema_comparator import (
    build_reconstruction_mapping,
    compare_schemas,
    detect_header_as_data_misparse,
    schema_fingerprint,
)

schema_detective_agent = Agent(
    name="schema_detective",
    model=Gemini(model="gemini-2.5-pro"),
    description=(
        "Detects schema drift in GHCN-Daily BigQuery tables. "
        "Compares current BQ schema against known 8-column GHCN-Daily spec, and "
        "detects the 'header-as-data' misparse where a headerless CSV's first row "
        "was consumed as column names. Classifies changes and proposes a "
        "reconstruction mapping."
    ),
    instruction=open("app/prompts/schema_detective.md").read(),
    tools=[
        bigquery_get_schema,
        bigquery_list_tables,
        bigquery_run_query,
        compare_schemas,
        detect_header_as_data_misparse,
        build_reconstruction_mapping,
        schema_fingerprint,
    ],
)
