import { useEffect, useRef, useState } from "react";
import { A2uiSurface, renderMarkdown } from "./a2ui/Renderer";
import { parseA2ui } from "./a2ui/parse";
import type { Surface } from "./a2ui/types";
import {
  createSession,
  newSessionId,
  resolveAppName,
  runAgent,
  type Pipeline,
} from "./adk";
import { cacheAgeLabel, clearCached, getCached, setCached } from "./cache";

interface Turn {
  role: "user" | "agent";
  text: string;
  pending?: boolean;
}

// Initial follow-up suggestions shown before the agent has replied. The
// dashboard already answers status / schema / DQ overview, so these chips push
// into next-step territory: source fix, deeper data quality, and re-sync
// recovery. The agent replaces these per turn via the <followups> block.
const DEFAULT_FOLLOWUPS = [
  "Walk me through the source-fix plan.",
  "Which elements have the most quality flags?",
  "What's only recoverable by a re-sync?",
];

// Compose the full dashboard when the operator first opens the pipeline.
const KICKOFF =
  "Open this pipeline. Compose the full health dashboard: pipeline health, " +
  "schema drift / misparse, and data-quality status. Keep your text reply to a " +
  "one-line greeting — put the detail in the dashboard surfaces.";

function mergeSurfaces(prev: Surface[], incoming: Surface[]): Surface[] {
  const map = new Map(prev.map((s) => [s.surfaceId, s]));
  const order = prev.map((s) => s.surfaceId);
  for (const s of incoming) {
    if (!map.has(s.surfaceId)) order.push(s.surfaceId);
    map.set(s.surfaceId, s);
  }
  return order.map((id) => map.get(id)!);
}

export function Workspace({ pipeline }: { pipeline: Pipeline }) {
  const [appName, setAppName] = useState<string | null>(null);
  const [sessionId] = useState(newSessionId);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [surfaces, setSurfaces] = useState<Surface[]>([]);
  const [followups, setFollowups] = useState<string[]>(DEFAULT_FOLLOWUPS);
  const [cachedTs, setCachedTs] = useState<number | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const chatRef = useRef<HTMLDivElement>(null);
  const initStarted = useRef(false);

  async function execute(
    name: string,
    message: string,
    showUser: boolean,
    opts: { kickoff?: boolean } = {}
  ) {
    setError(null);
    setBusy(true);
    setInput("");
    setTurns((t) => [
      ...t,
      ...(showUser ? [{ role: "user" as const, text: message }] : []),
      { role: "agent" as const, text: "", pending: true },
    ]);
    try {
      const raw = await runAgent(name, sessionId, message);
      const { text, surfaces: parsed, followups: nextFollowups } = parseA2ui(raw);
      const greeting = text || (parsed.length ? "Updated the dashboard." : "Done.");
      setTurns((t) => {
        const copy = [...t];
        copy[copy.length - 1] = { role: "agent", text: greeting };
        return copy;
      });
      if (parsed.length) setSurfaces((prev) => mergeSurfaces(prev, parsed));
      if (nextFollowups.length) setFollowups(nextFollowups);
      // Only the kickoff response is cacheable as the dashboard baseline —
      // follow-up turns are operator-driven and would poison the cache.
      if (opts.kickoff && parsed.length) {
        setCached(pipeline.connector_id, {
          text: greeting,
          surfaces: parsed,
          followups: nextFollowups.length ? nextFollowups : DEFAULT_FOLLOWUPS,
        });
        setCachedTs(Date.now());
      }
    } catch (e) {
      setError(String(e));
      setTurns((t) => {
        const copy = [...t];
        copy[copy.length - 1] = { role: "agent", text: "Request failed." };
        return copy;
      });
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    // StrictMode runs effects twice in dev; guard so the session is created once.
    if (initStarted.current) return;
    initStarted.current = true;
    (async () => {
      const name = await resolveAppName();
      await createSession(name, sessionId, {
        selected_connector_id: pipeline.connector_id,
        // Don't pass the BQ schema/table path here — the model treats it as a
        // table reference and improvises SQL against it with hallucinated cols.
        // The orchestrator knows the GHCN dataset structure from its prompt.
        selected_connector_name: pipeline.connector_id,
      });
      setAppName(name);

      // Hydrate from cache if fresh — the kickoff turn is the slow path (~90s),
      // and Fivetran sync state moves slowly enough that a 10 min TTL is fine.
      const cached = getCached(pipeline.connector_id);
      if (cached) {
        setSurfaces(cached.surfaces);
        setFollowups(cached.followups.length ? cached.followups : DEFAULT_FOLLOWUPS);
        setTurns([{ role: "agent", text: cached.text }]);
        setCachedTs(cached.ts);
        return;
      }
      await execute(name, KICKOFF, false, { kickoff: true });
    })().catch((e) => setError(String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function refresh() {
    if (!appName || busy) return;
    clearCached(pipeline.connector_id);
    setCachedTs(null);
    setSurfaces([]);
    setTurns([]);
    setFollowups(DEFAULT_FOLLOWUPS);
    execute(appName, KICKOFF, false, { kickoff: true });
  }

  useEffect(() => {
    chatRef.current?.scrollTo({ top: chatRef.current.scrollHeight });
  }, [turns]);

  function send(message: string) {
    if (!appName || busy || !message.trim()) return;
    execute(appName, message, true);
  }

  const composing = busy && surfaces.length === 0;

  return (
    <div className="workspace">
      {error && <div className="error-banner">{error}</div>}

      <section className="canvas">
        <div className="canvas-head">
          <h2>{pipeline.schema ?? pipeline.connector_id} · dashboard</h2>
          <div className="canvas-meta">
            {cachedTs && !busy && (
              <span className="canvas-cached">
                cached {cacheAgeLabel(cachedTs)}
              </span>
            )}
            {busy && <span className="canvas-busy">updating…</span>}
            <button
              className="canvas-refresh"
              onClick={refresh}
              disabled={busy || !appName}
              title="Re-compose the dashboard from the live agent"
            >
              Refresh
            </button>
          </div>
        </div>
        {surfaces.length === 0 ? (
          <div className="canvas-empty">
            {composing ? "Composing dashboard…" : "No panels yet."}
          </div>
        ) : (
          <div className="canvas-grid">
            {surfaces.map((s) => (
              <div key={s.surfaceId} className="canvas-panel">
                <A2uiSurface surface={s} onAction={(name) => send(name)} />
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="chat-panel">
        <div className="chat-log" ref={chatRef}>
          {turns.length === 0 && (
            <div className="empty">
              <p>Connecting to {pipeline.connector_id}…</p>
            </div>
          )}
          {turns.map((turn, i) => (
            <div key={i} className={`turn ${turn.role}`}>
              <div className="bubble">
                {turn.pending && <div className="spinner">thinking…</div>}
                {turn.text && (
                  <div className="msg-text">
                    {turn.role === "agent"
                      ? renderMarkdown(turn.text)
                      : turn.text}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>

        <div className="quick-row">
          {followups.map((q) => (
            <button
              key={q}
              className="chip"
              disabled={busy || !appName}
              onClick={() => send(q)}
            >
              {q}
            </button>
          ))}
        </div>

        <form
          className="composer"
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
        >
          <input
            value={input}
            placeholder="Ask about sync, schema drift, data quality…"
            onChange={(e) => setInput(e.target.value)}
            disabled={busy || !appName}
          />
          <button type="submit" disabled={busy || !appName || !input.trim()}>
            Send
          </button>
        </form>
      </section>
    </div>
  );
}
