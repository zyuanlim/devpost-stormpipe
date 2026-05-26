import type { A2uiMessage, Surface } from "./types";

const BLOCK_RE = /<a2ui-json>([\s\S]*?)<\/a2ui-json>/g;

export interface ParsedResponse {
  // Conversational text outside the A2UI blocks.
  text: string;
  surfaces: Surface[];
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
  const keys = Object.keys(obj);
  if (keys.length === 1 && obj[keys[0]] && typeof obj[keys[0]] === "object") {
    return normalize(obj[keys[0]]);
  }
  return obj as A2uiMessage;
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

export function parseA2ui(responseText: string): ParsedResponse {
  const messages: A2uiMessage[] = [];
  let text = "";
  let lastEnd = 0;

  BLOCK_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = BLOCK_RE.exec(responseText)) !== null) {
    text += responseText.slice(lastEnd, m.index);
    messages.push(...extractJsonObjects(m[1]));
    lastEnd = BLOCK_RE.lastIndex;
  }
  text += responseText.slice(lastEnd);

  return { text: text.trim(), surfaces: foldSurfaces(messages) };
}
