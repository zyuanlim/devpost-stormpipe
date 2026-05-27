# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os

import google.auth
from fastapi import FastAPI
from google.adk.cli.fast_api import get_fast_api_app
from google.cloud import logging as google_cloud_logging

from app.app_utils.telemetry import setup_telemetry
from app.app_utils.typing import Feedback

setup_telemetry()
_, project_id = google.auth.default()
logging_client = google_cloud_logging.Client()
logger = logging_client.logger(__name__)
allow_origins = (
    os.getenv("ALLOW_ORIGINS", "").split(",") if os.getenv("ALLOW_ORIGINS") else None
)

# Artifact bucket for ADK (created by Terraform, passed via env var)
logs_bucket_name = os.environ.get("LOGS_BUCKET_NAME")

AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# In-memory session configuration - no persistent storage
session_service_uri = None

artifact_service_uri = f"gs://{logs_bucket_name}" if logs_bucket_name else None

# Vertex AI Memory Bank, keyed off the Agent Engine id. Unset until the engine is
# provisioned; falls back to ADK's in-memory memory service. The URI is built in
# full-resource form so the memory region is pinned independently of
# GOOGLE_CLOUD_LOCATION — the agent's Gemini model runs against the `global`
# endpoint (where gemini-3.5-flash is served) while the Memory Bank stays in its
# own region (us-central1, where the engine was created).
agent_engine_id = os.environ.get("AGENT_ENGINE_ID")
memory_location = os.environ.get("MEMORY_LOCATION", "us-central1")
memory_project = os.environ.get("MEMORY_PROJECT", project_id)
memory_service_uri = (
    f"agentengine://projects/{memory_project}/locations/{memory_location}"
    f"/reasoningEngines/{agent_engine_id}"
    if agent_engine_id
    else None
)

# Cloud Trace/Logging export. Off by default — enabling it requires the otel
# OTLP + GCP exporter packages (opentelemetry-exporter-otlp-proto-http,
# -gcp-monitoring, -gcp-logging, resourcedetector-gcp); without them the app
# crashes at import. Gated so the deploy doesn't depend on that chain.
otel_to_cloud = os.environ.get("OTEL_TO_CLOUD", "").lower() in ("1", "true", "yes")

app: FastAPI = get_fast_api_app(
    agents_dir=AGENT_DIR,
    web=True,
    artifact_service_uri=artifact_service_uri,
    allow_origins=allow_origins,
    session_service_uri=session_service_uri,
    memory_service_uri=memory_service_uri,
    otel_to_cloud=otel_to_cloud,
)
app.title = "stormpipe"
app.description = "API for interacting with the Agent stormpipe"


@app.post("/feedback")
def collect_feedback(feedback: Feedback) -> dict[str, str]:
    """Collect and log feedback.

    Args:
        feedback: The feedback data to log

    Returns:
        Success message
    """
    logger.log_struct(feedback.model_dump(), severity="INFO")
    return {"status": "success"}


# Main execution
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
