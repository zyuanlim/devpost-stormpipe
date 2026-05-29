// Thin client for the ADK api_server REST surface (proxied via vite).

interface Part {
  text?: string;
}
interface Content {
  role?: string;
  parts?: Part[];
}
interface Event {
  author?: string;
  content?: Content;
}

const USER_ID = "operator";

export interface Pipeline {
  connector_id: string;
  service?: string;
  schema?: string;
  sync_state?: string;
  setup_state?: string;
  succeeded_at?: string | null;
  failed_at?: string | null;
}

export async function listApps(): Promise<string[]> {
  const r = await fetch("/list-apps");
  if (!r.ok) throw new Error(`/list-apps ${r.status}`);
  return r.json();
}

// List selectable Fivetran pipelines from the agent server's /pipelines route.
export async function listPipelines(): Promise<Pipeline[]> {
  const r = await fetch("/pipelines");
  if (!r.ok) throw new Error(`/pipelines ${r.status}`);
  const body = await r.json();
  return (body.connectors ?? []) as Pipeline[];
}

// Resolve which app name the api_server is serving. Falls back to "app".
export async function resolveAppName(): Promise<string> {
  try {
    const apps = await listApps();
    if (apps.length) return apps[0];
  } catch {
    /* ignore, use fallback */
  }
  return "app";
}

export async function createSession(
  appName: string,
  sessionId: string,
  state: Record<string, unknown> = {}
): Promise<void> {
  const r = await fetch(
    `/apps/${appName}/users/${USER_ID}/sessions/${sessionId}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ state }),
    }
  );
  // 200 created, or already-exists style errors are tolerable for the demo.
  if (!r.ok && r.status !== 409) {
    // Some builds return 400 if the session exists; don't hard-fail.
    console.warn(`createSession ${r.status}`);
  }
}

// Run the agent once and return the concatenated text of the final model turn.
export async function runAgent(
  appName: string,
  sessionId: string,
  message: string
): Promise<string> {
  const r = await fetch("/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      app_name: appName,
      user_id: USER_ID,
      session_id: sessionId,
      new_message: { role: "user", parts: [{ text: message }] },
      streaming: false,
    }),
  });
  if (!r.ok) {
    const body = await r.text();
    throw new Error(`/run ${r.status}: ${body.slice(0, 300)}`);
  }
  const events: Event[] = await r.json();

  // The final answer is the last event carrying model text. Concatenate text
  // parts of the last text-bearing event from the orchestrator.
  let lastText = "";
  for (const ev of events) {
    const parts = ev.content?.parts ?? [];
    const text = parts
      .map((p) => p.text ?? "")
      .join("")
      .trim();
    if (text) lastText = text;
  }
  return lastText;
}

export function newSessionId(): string {
  return `s-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}
