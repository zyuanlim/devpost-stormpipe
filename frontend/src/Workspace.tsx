import { useEffect, useRef, useState } from "react";
import { A2uiSurface, renderMarkdown } from "./a2ui/Renderer";
import { liveChatText, parseA2ui } from "./a2ui/parse";
import type { Surface } from "./a2ui/types";
import {
  createSession,
  newSessionId,
  resolveAppName,
  runAgentStream,
  type Pipeline,
} from "./adk";
import { cacheAgeLabel, clearCached, getCached, setCached } from "./cache";

interface Turn {
  role: "user" | "agent";
  text: string;
  // Live chain-of-thought summary, shown while the turn streams (if the model
  // emits any). Cleared/ignored once the final answer text lands.
  thought?: string;
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

// Deterministic fix / reparse action wired to a fixed canvas button so it is
// ALWAYS present on first load — not dependent on the model emitting a fix
// button inside the composed dashboard. Phrasing matches the orchestrator's
// "proceed/fix" routing: execute the in-warehouse rebuild now, then surface the
// source re-sync proposal for the fields only a re-sync can recover.
const FIX_PROMPT =
  "Fix it now: reparse the misparsed GHCN data — rebuild " +
  "noaa_ghcn.observations_clean in BigQuery and apply it, then show the source " +
  "re-sync proposal for the Q_FLAG / OBS_TIME fields only a re-sync can recover.";

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
  // surfaceIds the latest turn created/updated — highlighted + scrolled into
  // view so the operator can pinpoint what their query just changed.
  const [recentIds, setRecentIds] = useState<Set<string>>(new Set());
  const [followups, setFollowups] = useState<string[]>(DEFAULT_FOLLOWUPS);
  const [cachedTs, setCachedTs] = useState<number | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const chatRef = useRef<HTMLDivElement>(null);
  const gridRef = useRef<HTMLDivElement>(null);
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
      // Stream the conversational text into the chat as tokens arrive. Canvas
      // surfaces stay non-streamed — A2UI JSON can't render until a block is
      // complete — so they commit once below, after the turn finishes.
      const raw = await runAgentStream(name, sessionId, message, (u) => {
        const preview = liveChatText(u.text);
        setTurns((t) => {
          const copy = [...t];
          copy[copy.length - 1] = {
            role: "agent",
            text: preview,
            thought: u.thought || undefined,
            pending: true,
          };
          return copy;
        });
      });
      const { text, surfaces: parsed, followups: nextFollowups } = parseA2ui(raw);
      const greeting = text || (parsed.length ? "Updated the dashboard." : "Done.");
      setTurns((t) => {
        const copy = [...t];
        // Keep the streamed thought summary on the finished turn so it can be
        // re-read from the collapsed toggle.
        const prev = copy[copy.length - 1];
        copy[copy.length - 1] = {
          role: "agent",
          text: greeting,
          thought: prev?.thought,
        };
        return copy;
      });
      if (parsed.length) {
        setSurfaces((prev) => mergeSurfaces(prev, parsed));
        setRecentIds(new Set(parsed.map((s) => s.surfaceId)));
      }
      // First load (kickoff) shows a DETERMINISTIC set of suggested questions —
      // the model's per-turn <followups> only take over once the operator has
      // driven a follow-up turn. Keeps the opening experience reproducible.
      if (opts.kickoff) setFollowups(DEFAULT_FOLLOWUPS);
      else if (nextFollowups.length) setFollowups(nextFollowups);
      // Only the kickoff response is cacheable as the dashboard baseline —
      // follow-up turns are operator-driven and would poison the cache.
      if (opts.kickoff && parsed.length) {
        setCached(pipeline.connector_id, {
          text: greeting,
          surfaces: parsed,
          followups: DEFAULT_FOLLOWUPS,
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
    setRecentIds(new Set());
    setTurns([]);
    setFollowups(DEFAULT_FOLLOWUPS);
    execute(appName, KICKOFF, false, { kickoff: true });
  }

  useEffect(() => {
    chatRef.current?.scrollTo({ top: chatRef.current.scrollHeight });
  }, [turns]);

  // Bring the just-updated panel into view so the operator's eye lands on what
  // their query changed. Runs after surfaces commit (recentIds change).
  useEffect(() => {
    if (!recentIds.size) return;
    const el = gridRef.current?.querySelector(".canvas-panel--recent");
    el?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [recentIds, surfaces]);

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
              className="canvas-fix"
              onClick={() => send(FIX_PROMPT)}
              disabled={busy || !appName}
              title="Reparse the misparsed data and rebuild observations_clean now"
            >
              Fix &amp; reparse
            </button>
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
          <div className="canvas-grid" ref={gridRef}>
            {surfaces.map((s) => (
              <div
                key={s.surfaceId}
                className={`canvas-panel${
                  recentIds.has(s.surfaceId) ? " canvas-panel--recent" : ""
                }`}
              >
                {recentIds.has(s.surfaceId) && (
                  <span className="canvas-panel-badge">updated</span>
                )}
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
                {turn.pending && turn.thought && (
                  <div className="msg-thought">{turn.thought}</div>
                )}
                {!turn.pending && turn.thought && (
                  <details className="msg-thought-toggle">
                    <summary>Thinking</summary>
                    <div className="msg-thought">{turn.thought}</div>
                  </details>
                )}
                {turn.pending && !turn.text && !turn.thought && (
                  <div className="spinner">thinking…</div>
                )}
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
