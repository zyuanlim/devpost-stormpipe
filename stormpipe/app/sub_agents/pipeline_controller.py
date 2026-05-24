"""Pipeline Controller sub-agent — manages Fivetran syncs via MCP."""

import os
from google.adk.agents import Agent
from google.adk.models import Gemini
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, StdioConnectionParams

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
        "Controls Fivetran pipeline syncs. Use to check sync status, "
        "trigger syncs, pause/resume connectors, and inspect connector config. "
        "The Fivetran connector ID is 'personified_hither'."
    ),
    instruction=(
        "You manage the Fivetran S3→BigQuery pipeline for NOAA GHCN-Daily data. "
        "Connector ID: personified_hither. Group ID: unconcerned_sweat. "
        "Use available Fivetran MCP tools to check status, trigger syncs, and report results. "
        "Always return structured status: connector_id, sync_state, succeeded_at, failed_at, any errors."
    ),
    tools=[fivetran_mcp],
)
