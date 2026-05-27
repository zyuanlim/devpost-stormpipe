import { useEffect, useRef, useState } from "react";
import { A2uiSurface, renderMarkdown } from "./a2ui/Renderer";
import { parseA2ui } from "./a2ui/parse";
import type { Surface } from "./a2ui/types";
import {
  createSession,
  newSessionId,
  resolveAppName,
  runAgent,
} from "./adk";

interface Turn {
  role: "user" | "agent";
  text: string;
  surfaces: Surface[];
  pending?: boolean;
}

const QUICK_ACTIONS = [
  "Give me a pipeline health overview.",
  "What schema drift or misparse did you detect?",
  "Show the data-quality remediation status for observations_clean.",
];

export function App() {
  const [appName, setAppName] = useState<string | null>(null);
  const [sessionId] = useState(newSessionId);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const initStarted = useRef(false);

  useEffect(() => {
    // React StrictMode runs effects twice in dev; guard so we create the
    // session only once (a duplicate create 500s on the unique constraint).
    if (initStarted.current) return;
    initStarted.current = true;
    (async () => {
      const name = await resolveAppName();
      await createSession(name, sessionId);
      setAppName(name);
    })().catch((e) => setError(String(e)));
  }, [sessionId]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [turns]);

  async function send(message: string) {
    if (!appName || busy || !message.trim()) return;
    setError(null);
    setBusy(true);
    setInput("");
    setTurns((t) => [
      ...t,
      { role: "user", text: message, surfaces: [] },
      { role: "agent", text: "", surfaces: [], pending: true },
    ]);
    try {
      const raw = await runAgent(appName, sessionId, message);
      const { text, surfaces } = parseA2ui(raw);
      setTurns((t) => {
        const copy = [...t];
        copy[copy.length - 1] = { role: "agent", text, surfaces };
        return copy;
      });
    } catch (e) {
      setError(String(e));
      setTurns((t) => {
        const copy = [...t];
        copy[copy.length - 1] = {
          role: "agent",
          text: "Request failed.",
          surfaces: [],
        };
        return copy;
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo">⛈</span> StormPipe
          <span className="subtitle">NOAA GHCN-Daily pipeline health</span>
        </div>
        <div className="status">
          {appName ? (
            <span className="ok">connected · {appName}</span>
          ) : (
            <span className="warn">connecting…</span>
          )}
        </div>
      </header>

      {error && <div className="error-banner">{error}</div>}

      <main className="chat" ref={scrollRef}>
        {turns.length === 0 && (
          <div className="empty">
            <p>Ask StormPipe about the pipeline. Try:</p>
            <div className="quick">
              {QUICK_ACTIONS.map((q) => (
                <button key={q} className="chip" onClick={() => send(q)}>
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {turns.map((turn, i) => (
          <div key={i} className={`turn ${turn.role}`}>
            <div className="bubble">
              {turn.pending && <div className="spinner">thinking…</div>}
              {turn.text && (
                <div className="msg-text">
                  {turn.role === "agent" ? renderMarkdown(turn.text) : turn.text}
                </div>
              )}
              {turn.surfaces.map((s) => (
                <div key={s.surfaceId} className="surface">
                  <A2uiSurface surface={s} onAction={(name) => send(name)} />
                </div>
              ))}
            </div>
          </div>
        ))}
      </main>

      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
      >
        <input
          value={input}
          placeholder="Ask about sync status, schema drift, data quality…"
          onChange={(e) => setInput(e.target.value)}
          disabled={busy || !appName}
        />
        <button type="submit" disabled={busy || !appName || !input.trim()}>
          Send
        </button>
      </form>
    </div>
  );
}
