import { useEffect, useState } from "react";
import { listPipelines, type Pipeline } from "./adk";

function syncClass(state?: string): string {
  if (!state) return "neutral";
  const s = state.toLowerCase();
  if (s.includes("sync") || s === "connected") return "ok";
  if (s.includes("fail") || s.includes("error") || s.includes("broken"))
    return "bad";
  return "warn";
}

export function PipelineList({
  onSelect,
}: {
  onSelect: (p: Pipeline) => void;
}) {
  const [pipelines, setPipelines] = useState<Pipeline[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listPipelines()
      .then(setPipelines)
      .catch((e) => setError(String(e)));
  }, []);

  return (
    <main className="picker">
      <div className="picker-head">
        <h1>Select a pipeline</h1>
        <p>Choose a Fivetran connector to dive into its health, schema, and data quality.</p>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {pipelines === null && !error && (
        <div className="picker-loading">Loading pipelines…</div>
      )}

      <div className="pipeline-grid">
        {pipelines?.map((p) => (
          <button
            key={p.connector_id}
            className="pipeline-card"
            onClick={() => onSelect(p)}
          >
            <div className="pipeline-card-top">
              <span className="pipeline-service">{p.service ?? "source"}</span>
              <span className={`badge ${syncClass(p.sync_state)}`}>
                {p.sync_state ?? "unknown"}
              </span>
            </div>
            <div className="pipeline-id">{p.connector_id}</div>
            {p.schema && <div className="pipeline-schema">{p.schema}</div>}
            <div className="pipeline-go">Open →</div>
          </button>
        ))}
      </div>

      {pipelines?.length === 0 && (
        <div className="picker-loading">No connectors found in this group.</div>
      )}
    </main>
  );
}
