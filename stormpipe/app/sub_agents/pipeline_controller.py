"""Pipeline Controller sub-agent — manages Fivetran syncs + source self-healing."""

import os

from google.adk.agents import Agent
from google.adk.models import Gemini
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, StdioConnectionParams

from app.tools.fivetran_tool import (
    fivetran_connector_status,
    fivetran_diagnose_csv_parsing,
    fivetran_fix_csv_header_config,
    fivetran_resync,
)

FIVETRAN_API_KEY = os.environ.get("FIVETRAN_API_KEY", "")
FIVETRAN_API_SECRET = os.environ.get("FIVETRAN_API_SECRET", "")

fivetran_mcp = MCPToolset(
    connection_params=StdioConnectionParams(
        server_params={
            "command": "uvx",
            "args": ["fivetran-mcp@latest"],
            "env": {
                "FIVETRAN_API_KEY": FIVETRAN_API_KEY,
                "FIVETRAN_API_SECRET": FIVETRAN_API_SECRET,
            },
        }
    )
)

pipeline_controller_agent = Agent(
    name="pipeline_controller",
    model=Gemini(model="gemini-2.5-flash"),
    description=(
        "Controls the Fivetran S3→BigQuery pipeline and heals it at the source. "
        "Checks sync/setup status, diagnoses the headerless-CSV misparse, and (on "
        "explicit confirmation) fixes the connector's CSV header config and triggers a "
        "re-sync. Connector ID 'personified_hither'."
    ),
    instruction=open("app/prompts/pipeline_controller.md").read(),
    tools=[
        fivetran_connector_status,
        fivetran_diagnose_csv_parsing,
        fivetran_fix_csv_header_config,
        fivetran_resync,
        fivetran_mcp,
    ],
)
