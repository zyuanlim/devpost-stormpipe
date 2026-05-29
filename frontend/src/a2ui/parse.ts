import type { A2uiComponent, A2uiMessage, Surface } from "./types";

const BLOCK_RE = /<a2ui-json>([\s\S]*?)<\/a2ui-json>/g;
const FOLLOWUPS_RE = /<followups>([\s\S]*?)<\/followups>/g;

export interface ParsedResponse {
  // Conversational text outside the A2UI / followups blocks.
  text: string;
  surfaces: Surface[];
  // Next-best follow-up questions the agent suggests for the operator. Empty
  // when the model didn't emit a followups block.
  followups: string[];
}

function extractFollowups(raw: string): { followups: string[]; stripped: string } {
  const followups: string[] = [];
  let stripped = raw;
  FOLLOWUPS_RE.lastIndex = 0;
  stripped = stripped.replace(FOLLOWUPS_RE, (_full, body: string) => {
    try {
      const arr = JSON.parse(body.trim());
      if (Array.isArray(arr)) {
        for (const q of arr) if (typeof q === "string" && q.trim()) followups.push(q.trim());
      }
    } catch {
      /* malformed → ignore, defaults stay */
    }
    return "";
  });
  return { followups, stripped };
}

// A single <a2ui-json> block may contain one JSON object, several concatenated
// objects (not comma-separated), or a JSON array of messages. Pull out every
// top-level {...} object and parse each.
function extractJsonObjects(raw: string): A2uiMessage[] {
  const trimmed = raw.trim();
  const msgs: A2uiMessage[] = [];

  // Try the whole block as JSON first (object or array).
  try {
    const parsed = JSON.parse(trimmed);
    return Array.isArray(parsed) ? parsed : [parsed];
  } catch {
    /* fall through to brace-scanning */
  }

  let depth = 0;
  let start = -1;
  let inStr = false;
  let esc = false;
  for (let i = 0; i < trimmed.length; i++) {
    const ch = trimmed[i];
    if (inStr) {
      if (esc) esc = false;
      else if (ch === "\\") esc = true;
      else if (ch === '"') inStr = false;
      continue;
    }
    if (ch === '"') inStr = true;
    else if (ch === "{") {
      if (depth === 0) start = i;
      depth++;
    } else if (ch === "}") {
      depth--;
      if (depth === 0 && start >= 0) {
        try {
          msgs.push(JSON.parse(trimmed.slice(start, i + 1)));
        } catch {
          /* skip malformed object */
        }
        start = -1;
      }
    }
  }
  return msgs;
}

// The model is inconsistent about the message envelope: sometimes flat
// (`{version:"v0.9", updateComponents:{...}}`), sometimes wrapped with the
// version as the only key (`{"v0.9": {updateComponents:{...}}}`). Unwrap the
// latter so folding only deals with the flat form.
function normalize(raw: unknown): A2uiMessage {
  if (!raw || typeof raw !== "object") return {} as A2uiMessage;
  const obj = raw as Record<string, unknown>;
  if ("updateComponents" in obj || "createSurface" in obj || "updateDataModel" in obj) {
    return obj as A2uiMessage;
  }
  // Flat envelopes the model sometimes emits without the update* wrapper, e.g.
  // `{surfaceId, components:[...]}` or `{surfaceId, path, value}`. Re-wrap so
  // folding (and untagged recovery) treat them as A2UI instead of leaking.
  if ("surfaceId" in obj && Array.isArray(obj.components)) {
    return {
      updateComponents: {
        surfaceId: obj.surfaceId as string,
        components: obj.components as A2uiComponent[],
      },
    } as A2uiMessage;
  }
  if ("surfaceId" in obj && "path" in obj && "value" in obj) {
    return {
      updateDataModel: {
        surfaceId: obj.surfaceId as string,
        path: obj.path as string,
        value: obj.value,
      },
    } as A2uiMessage;
  }
  const keys = Object.keys(obj);
  if (keys.length === 1 && obj[keys[0]] && typeof obj[keys[0]] === "object") {
    return normalize(obj[keys[0]]);
  }
  return obj as A2uiMessage;
}

// An A2UI message carries at least one of these top-level keys (after
// unwrapping a `{"v0.9": {...}}` envelope). Used to recognize A2UI JSON that
// the model emitted WITHOUT the <a2ui-json> tags — e.g. in a ```json fence or
// bare — so it still renders on the canvas instead of leaking into the chat.
const A2UI_KEYS = ["updateComponents", "createSurface", "updateDataModel"];

function looksLikeA2ui(obj: unknown): boolean {
  const n = normalize(obj) as Record<string, unknown>;
  return !!n && typeof n === "object" && A2UI_KEYS.some((k) => k in n);
}

// Brace-scan a string for every top-level {...} object, returning each parsed
// object with its [start, end) span so callers can excise it from the text.
function scanJsonObjects(s: string): { obj: unknown; start: number; end: number }[] {
  const out: { obj: unknown; start: number; end: number }[] = [];
  let depth = 0;
  let start = -1;
  let inStr = false;
  let esc = false;
  for (let i = 0; i < s.length; i++) {
    const ch = s[i];
    if (inStr) {
      if (esc) esc = false;
      else if (ch === "\\") esc = true;
      else if (ch === '"') inStr = false;
      continue;
    }
    if (ch === '"') inStr = true;
    else if (ch === "{") {
      if (depth === 0) start = i;
      depth++;
    } else if (ch === "}") {
      if (depth > 0) {
        depth--;
        if (depth === 0 && start >= 0) {
          try {
            out.push({ obj: JSON.parse(s.slice(start, i + 1)), start, end: i + 1 });
          } catch {
            /* not valid JSON — skip */
          }
          start = -1;
        }
      }
    }
  }
  return out;
}

// Recover A2UI messages the model emitted without <a2ui-json> tags. Any
// top-level JSON object that looks like an A2UI message is pulled out of the
// chat text and routed to the canvas; non-A2UI JSON (e.g. a Fivetran config
// patch the operator should see) is left in the text untouched.
function recoverUntaggedA2ui(text: string): { messages: A2uiMessage[]; text: string } {
  const messages: A2uiMessage[] = [];
  const spans = scanJsonObjects(text).filter((o) => looksLikeA2ui(o.obj));
  if (!spans.length) return { messages, text };
  for (const { obj } of spans) messages.push(obj as A2uiMessage);
  // Excise spans right-to-left so earlier indices stay valid.
  let out = text;
  for (let i = spans.length - 1; i >= 0; i--) {
    out = out.slice(0, spans[i].start) + out.slice(spans[i].end);
  }
  // Clean up now-empty code fences and the leftover blank lines they leave.
  out = out
    .replace(/```[a-zA-Z]*\s*```/g, "")
    .replace(/```[a-zA-Z]*\s*$/gm, "")
    .replace(/\n{3,}/g, "\n\n");
  return { messages, text: out };
}

function foldSurfaces(rawMessages: A2uiMessage[]): Surface[] {
  const messages = rawMessages.map(normalize);
  const order: string[] = [];
  const byId: Record<string, Surface> = {};

  const ensure = (id: string): Surface => {
    if (!byId[id]) {
      byId[id] = { surfaceId: id, rootId: null, components: {}, data: {} };
      order.push(id);
    }
    return byId[id];
  };

  for (const msg of messages) {
    if (msg.createSurface) ensure(msg.createSurface.surfaceId);

    if (msg.updateComponents) {
      const s = ensure(msg.updateComponents.surfaceId);
      for (const c of msg.updateComponents.components ?? []) {
        if (!c?.id) continue;
        if (s.rootId === null) s.rootId = c.id;
        s.components[c.id] = c;
      }
    }

    if (msg.updateDataModel) {
      const s = ensure(msg.updateDataModel.surfaceId);
      // Store by absolute path; the renderer resolves DynamicString {path}.
      s.data[msg.updateDataModel.path] = msg.updateDataModel.value;
    }
  }

  return order.map((id) => byId[id]).filter((s) => s.rootId !== null);
}

// Cheap, allocation-light strip for the LIVE streaming preview: show only the
// conversational text that precedes any A2UI / followups payload. The model is
// prompted to lead with its one-line reply and put the dashboard JSON after, so
// cutting at the first block boundary keeps half-streamed JSON out of the chat
// without trying to parse incomplete objects. parseA2ui does the real cleanup
// once the full turn has arrived.
export function liveChatText(raw: string): string {
  let end = raw.length;
  for (const marker of ["<a2ui-json>", "<followups>", "```json", "```"]) {
    const i = raw.indexOf(marker);
    if (i !== -1 && i < end) end = i;
  }
  return raw.slice(0, end).trimStart();
}

export function parseA2ui(responseText: string): ParsedResponse {
  // Pull followups first so they never leak into the chat text.
  const { followups, stripped } = extractFollowups(responseText);

  const messages: A2uiMessage[] = [];
  let text = "";
  let lastEnd = 0;

  BLOCK_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = BLOCK_RE.exec(stripped)) !== null) {
    text += stripped.slice(lastEnd, m.index);
    messages.push(...extractJsonObjects(m[1]));
    lastEnd = BLOCK_RE.lastIndex;
  }
  let tail = stripped.slice(lastEnd);
  // A truncated turn can leave an unterminated `<a2ui-json>` with no closing
  // tag — drop from there to the end so half-streamed JSON never leaks into the
  // chat. Also recover any A2UI objects from that dangling block first.
  const openIdx = tail.indexOf("<a2ui-json>");
  if (openIdx !== -1) {
    messages.push(...extractJsonObjects(tail.slice(openIdx + "<a2ui-json>".length)));
    tail = tail.slice(0, openIdx);
  }
  text += tail;

  // Belt-and-suspenders: if the model emitted A2UI JSON without the
  // <a2ui-json> tags (fenced or bare), recover it from the chat text so it
  // renders on the canvas instead of leaking into the conversation.
  const recovered = recoverUntaggedA2ui(text);
  messages.push(...recovered.messages);

  return { text: recovered.text.trim(), surfaces: foldSurfaces(messages), followups };
}
