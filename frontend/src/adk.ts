// Thin client for the ADK api_server REST surface (proxied via vite).

interface Part {
  text?: string;
  // Gemini marks chain-of-thought summaries with thought:true. We stream these
  // separately from the answer text so they never leak into the A2UI parse.
  thought?: boolean;
}
interface Content {
  role?: string;
  parts?: Part[];
}
interface Event {
  author?: string;
  content?: Content;
  // ADK sets partial:true on incremental token deltas during SSE streaming and
  // omits it (or sets false) on the final aggregated event for a segment.
  partial?: boolean;
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

// Split a turn's parts into answer text (the A2UI-bearing reply) and thought
// summaries (Gemini chain-of-thought). The answer text is what parseA2ui later
// folds into chat text + canvas surfaces, so thoughts must stay out of it.
function splitParts(parts: Part[]): { text: string; thought: string } {
  let text = "";
  let thought = "";
  for (const p of parts) {
    if (!p.text) continue;
    if (p.thought) thought += p.text;
    else text += p.text;
  }
  return { text, thought };
}

export interface StreamUpdate {
  // Full answer text accumulated so far (raw — still contains <a2ui-json> and
  // <followups> blocks; the caller strips those for the live chat preview).
  text: string;
  // Full thought-summary text accumulated so far, if the model emits any.
  thought: string;
}

// Run the agent with server-sent-event streaming. onUpdate fires on every token
// delta so the chat can render text as it arrives; the resolved value is the
// final raw answer text for parseA2ui (surfaces + followups commit at the end).
export async function runAgentStream(
  appName: string,
  sessionId: string,
  message: string,
  onUpdate: (u: StreamUpdate) => void
): Promise<string> {
  const r = await fetch("/run_sse", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      app_name: appName,
      user_id: USER_ID,
      session_id: sessionId,
      new_message: { role: "user", parts: [{ text: message }] },
      streaming: true,
    }),
  });
  if (!r.ok || !r.body) {
    const body = r.body ? await r.text() : "";
    throw new Error(`/run_sse ${r.status}: ${body.slice(0, 300)}`);
  }

  // Text from completed (non-partial) events; partial deltas accumulate on top
  // and are folded into committed when the segment's final event lands. This is
  // correct whether deltas arrive as separate partials or one final blob.
  let committedText = "";
  let committedThought = "";
  let pendingText = "";
  let pendingThought = "";

  const emit = () =>
    onUpdate({
      text: committedText + pendingText,
      thought: committedThought + pendingThought,
    });

  const handleEvent = (ev: Event) => {
    const { text, thought } = splitParts(ev.content?.parts ?? []);
    if (!text && !thought) return;
    if (ev.partial) {
      pendingText += text;
      pendingThought += thought;
    } else {
      committedText += text;
      committedThought += thought;
      pendingText = "";
      pendingThought = "";
    }
    emit();
  };

  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const drain = () => {
    // SSE frames are separated by a blank line. Parse each complete frame.
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      for (const line of frame.split("\n")) {
        if (!line.startsWith("data:")) continue;
        const payload = line.slice(5).trim();
        if (!payload || payload === "[DONE]") continue;
        try {
          handleEvent(JSON.parse(payload) as Event);
        } catch {
          /* keep-alive comment or partial frame split mid-flight — skip */
        }
      }
    }
  };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    drain();
  }
  buffer += decoder.decode();
  drain();

  return committedText + pendingText;
}

export function newSessionId(): string {
  return `s-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}
