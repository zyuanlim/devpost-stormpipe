import { useState } from "react";
import { PipelineList } from "./PipelineList";
import { Workspace } from "./Workspace";
import type { Pipeline } from "./adk";

export function App() {
  const [pipeline, setPipeline] = useState<Pipeline | null>(null);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo">⛈</span> StormPipe
          <span className="subtitle">Fivetran pipeline health</span>
        </div>
        {pipeline ? (
          <div className="topbar-pipeline">
            <button className="back" onClick={() => setPipeline(null)}>
              ← pipelines
            </button>
            <span className="pipeline-chip">{pipeline.connector_id}</span>
          </div>
        ) : null}
      </header>

      {pipeline ? (
        <Workspace key={pipeline.connector_id} pipeline={pipeline} />
      ) : (
        <PipelineList onSelect={setPipeline} />
      )}
    </div>
  );
}
