import { useState } from "react";
import type { A2uiComponent, ChildList, DynamicString, Surface } from "./types";

// Material-symbol-ish names the agent tends to emit → glyphs, so we avoid an
// icon-font dependency.
const ICONS: Record<string, string> = {
  check_circle: "✓",
  check: "✓",
  warning: "⚠",
  error: "✕",
  info: "ℹ",
  database: "🗄",
  sync: "⟳",
  schema: "▤",
  bug_report: "🐞",
  cleaning_services: "🧹",
  storage: "🗄",
};

function jsonPointerGet(root: unknown, pointer: string): unknown {
  if (!pointer.startsWith("/")) return undefined;
  let cur: unknown = root;
  for (const rawSeg of pointer.split("/").slice(1)) {
    const seg = rawSeg.replace(/~1/g, "/").replace(/~0/g, "~");
    if (cur == null || typeof cur !== "object") return undefined;
    cur = (cur as Record<string, unknown>)[seg];
  }
  return cur;
}

// Build a nested object from the flat path→value writes so {path} bindings
// resolve through it.
function buildDataRoot(data: Record<string, unknown>): unknown {
  const root: Record<string, unknown> = {};
  for (const [path, value] of Object.entries(data)) {
    if (path === "/" || path === "") {
      if (value && typeof value === "object") Object.assign(root, value);
      continue;
    }
    const segs = path.split("/").slice(1);
    let cur: Record<string, unknown> = root;
    for (let i = 0; i < segs.length - 1; i++) {
      const s = segs[i];
      if (typeof cur[s] !== "object" || cur[s] == null) cur[s] = {};
      cur = cur[s] as Record<string, unknown>;
    }
    cur[segs[segs.length - 1]] = value;
  }
  return root;
}

interface Ctx {
  surface: Surface;
  dataRoot: unknown;
  scope: unknown; // local item scope for templated children
  onAction?: (eventName: string, context?: unknown) => void;
}

function resolveString(ds: DynamicString | undefined, ctx: Ctx): string {
  if (ds == null) return "";
  if (typeof ds === "string") return ds;
  if (typeof ds === "object" && "path" in ds) {
    const v =
      jsonPointerGet(ctx.scope, ds.path) ?? jsonPointerGet(ctx.dataRoot, ds.path);
    return v == null ? "" : String(v);
  }
  return "";
}

function resolveChildIds(children: ChildList | undefined, ctx: Ctx): {
  ids: string[];
  scopes: unknown[];
} {
  if (!children) return { ids: [], scopes: [] };
  if (Array.isArray(children)) {
    return { ids: children, scopes: children.map(() => ctx.scope) };
  }
  // Template: repeat componentId for each item at `path`.
  const list = jsonPointerGet(ctx.dataRoot, children.path);
  if (Array.isArray(list)) {
    return {
      ids: list.map(() => children.componentId),
      scopes: list,
    };
  }
  return { ids: [], scopes: [] };
}

// A2UI Text allows simple Markdown. Render the common cases the agent emits
// (**bold**, `code`, and - / * bullet lists) without pulling in a markdown dep.
function renderInline(text: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  const re = /(\*\*([^*]+)\*\*|`([^`]+)`)/g;
  let last = 0;
  let key = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) nodes.push(text.slice(last, m.index));
    if (m[2] !== undefined) nodes.push(<strong key={key++}>{m[2]}</strong>);
    else if (m[3] !== undefined) nodes.push(<code key={key++}>{m[3]}</code>);
    last = m.index + m[0].length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

export function renderMarkdown(text: string): React.ReactNode {
  const blocks: React.ReactNode[] = [];
  let list: string[] = [];
  let code: string[] | null = null;
  let key = 0;
  const flushList = () => {
    if (list.length) {
      const items = list;
      blocks.push(
        <ul key={`ul${key++}`} className="a2-md-list">
          {items.map((li, j) => (
            <li key={j}>{renderInline(li)}</li>
          ))}
        </ul>
      );
      list = [];
    }
  };
  const flushCode = () => {
    if (code !== null) {
      const body = code.join("\n");
      blocks.push(
        <pre key={`pre${key++}`} className="a2-md-code">
          <code>{body}</code>
        </pre>
      );
      code = null;
    }
  };

  for (const line of text.split("\n")) {
    const t = line.trim();

    // Fenced code block (```), toggled on the fence lines.
    if (t.startsWith("```")) {
      if (code === null) {
        flushList();
        code = [];
      } else {
        flushCode();
      }
      continue;
    }
    if (code !== null) {
      code.push(line);
      continue;
    }

    // Horizontal rule: --- / *** / ___
    if (/^([-*_])\1{2,}$/.test(t)) {
      flushList();
      blocks.push(<hr key={`hr${key++}`} className="a2-divider" />);
      continue;
    }

    // ATX heading: #..###### → h2..h5
    const heading = t.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      flushList();
      const lvl = Math.min(heading[1].length + 1, 5);
      blocks.push(
        <div key={`h${key++}`} className={`a2-text a2-h${lvl}`}>
          {renderInline(heading[2])}
        </div>
      );
      continue;
    }

    // Bullet list item
    const bullet = t.match(/^[-*]\s+(.*)/);
    if (bullet) {
      list.push(bullet[1]);
      continue;
    }

    flushList();
    if (t) blocks.push(<div key={`p${key++}`}>{renderInline(t)}</div>);
  }
  flushList();
  flushCode();
  return <>{blocks}</>;
}

function Node({ id, ctx }: { id: string; ctx: Ctx }) {
  const c: A2uiComponent | undefined = ctx.surface.components[id];
  if (!c) return null;

  switch (c.component) {
    case "Text": {
      const variant = (c.variant as string) ?? "body";
      const text = resolveString(c.text as DynamicString, ctx);
      return <div className={`a2-text a2-${variant}`}>{renderMarkdown(text)}</div>;
    }

    case "Icon": {
      const name = (c.name as string) ?? "";
      // Semantic color per status glyph (check/warning/error) via a name class.
      return (
        <span className={`a2-icon a2-icon-${name}`} title={name}>
          {ICONS[name] ?? "•"}
        </span>
      );
    }

    case "Image": {
      const url = c.url as string;
      const fit = (c.fit as string) ?? "contain";
      return (
        <img
          className="a2-image"
          src={url}
          alt={(c.description as string) ?? ""}
          style={{ objectFit: fit as React.CSSProperties["objectFit"] }}
        />
      );
    }

    case "Divider": {
      const axis = (c.axis as string) ?? "horizontal";
      return axis === "vertical" ? (
        <div className="a2-divider-v" />
      ) : (
        <hr className="a2-divider" />
      );
    }

    case "Row":
    case "Column":
    case "List": {
      const isRow = c.component === "Row";
      const { ids, scopes } = resolveChildIds(c.children as ChildList, ctx);
      const justify = c.justify as string | undefined;
      const align = c.align as string | undefined;
      const dir =
        c.component === "List" && c.direction === "horizontal" ? true : isRow;
      return (
        <div
          className={`a2-${c.component.toLowerCase()}`}
          style={{
            display: "flex",
            flexDirection: dir ? "row" : "column",
            // Rows wrap so action-button groups never overflow a narrow panel.
            flexWrap: dir ? "wrap" : undefined,
            justifyContent: mapJustify(justify),
            alignItems: mapAlign(align),
            gap: 10,
          }}
        >
          {ids.map((cid, i) => (
            <Node key={`${cid}-${i}`} id={cid} ctx={{ ...ctx, scope: scopes[i] }} />
          ))}
        </div>
      );
    }

    case "Card": {
      const child = c.child as string;
      return (
        <div className="a2-card">
          <Node id={child} ctx={ctx} />
        </div>
      );
    }

    case "Tabs": {
      const tabs = (c.tabs as { title: DynamicString; child: string }[]) ?? [];
      return <TabsView tabs={tabs} ctx={ctx} />;
    }

    case "Button": {
      const child = c.child as string;
      const variant = (c.variant as string) ?? "default";
      const action = c.action as { event?: { name: string; context?: unknown } };
      return (
        <button
          className={`a2-button a2-button-${variant}`}
          onClick={() =>
            action?.event && ctx.onAction?.(action.event.name, action.event.context)
          }
        >
          <Node id={child} ctx={ctx} />
        </button>
      );
    }

    default:
      return (
        <div className="a2-unknown">[unsupported: {c.component}]</div>
      );
  }
}

function TabsView({
  tabs,
  ctx,
}: {
  tabs: { title: DynamicString; child: string }[];
  ctx: Ctx;
}) {
  const [active, setActive] = useState(0);
  return (
    <div className="a2-tabs">
      <div className="a2-tablist" role="tablist">
        {tabs.map((t, i) => (
          <button
            key={i}
            role="tab"
            aria-selected={i === active}
            className={`a2-tab ${i === active ? "active" : ""}`}
            onClick={() => setActive(i)}
          >
            {resolveString(t.title, ctx)}
          </button>
        ))}
      </div>
      <div className="a2-tabpanel" role="tabpanel">
        {tabs[active] && <Node id={tabs[active].child} ctx={ctx} />}
      </div>
    </div>
  );
}

function mapJustify(j?: string): React.CSSProperties["justifyContent"] {
  switch (j) {
    case "spaceBetween":
      return "space-between";
    case "start":
      return "flex-start";
    case "end":
      return "flex-end";
    case "center":
      return "center";
    default:
      return undefined;
  }
}

function mapAlign(a?: string): React.CSSProperties["alignItems"] {
  switch (a) {
    case "start":
      return "flex-start";
    case "end":
      return "flex-end";
    case "center":
      return "center";
    case "stretch":
      return "stretch";
    default:
      return undefined;
  }
}

export function A2uiSurface({
  surface,
  onAction,
}: {
  surface: Surface;
  onAction?: (eventName: string, context?: unknown) => void;
}) {
  if (!surface.rootId) return null;
  const ctx: Ctx = {
    surface,
    dataRoot: buildDataRoot(surface.data),
    scope: buildDataRoot(surface.data),
    onAction,
  };
  return <Node id={surface.rootId} ctx={ctx} />;
}
