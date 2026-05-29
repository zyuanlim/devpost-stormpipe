# ruff: noqa
"""A2UI prompt-injection setup for the StormPipe orchestrator.

Enabling A2UI makes the orchestrator emit agent-driven UI as `<a2ui-json>`
blocks (A2UI v0.9 messages) that the React frontend renders natively. It is
gated behind the `A2UI_ENABLED` env var so the eval set and headless runs keep
their plain-text/tool behavior untouched.

The clean A2A toolset path (`SendA2uiToClientToolset`) is unavailable on the
installed a2a-sdk (1.x dropped `a2a.types.DataPart`), so we use the
prompt-injection pattern: the schema manager generates a system prompt that
constrains the model to valid A2UI JSON for the components our renderer
supports.
"""
import functools
import os

# Components the React renderer in frontend/ supports. Restricting the schema
# to this subset both shrinks the prompt and guarantees the model never emits a
# primitive the client cannot draw.
SUPPORTED_COMPONENTS = [
    "Text",
    "Icon",
    "Image",
    "Row",
    "Column",
    "List",
    "Card",
    "Tabs",
    "Divider",
    "Button",
]

_UI_DESCRIPTION = """\
Render the operator response as agent-driven UI on a persistent dashboard
canvas. Each concern is a panel with a STABLE surfaceId so re-emitting it
updates that panel in place instead of stacking duplicates. Use these canonical
surfaceIds:

- `pipeline-health` — health overview: a Card whose child is a Column. Lead
  with a Row holding a status Icon (`check_circle` healthy, `warning` warning,
  `error` error) and a Text title (variant h3). Follow with Text rows for sync
  status, row count, and the headerless-misparse finding.
- `schema-detail` — schema drift / misparse: Tabs with one tab per concern
  (e.g. "Detected", "Recoverable", "Lost"), each tab's child a Column of Text
  rows.
- `dq-status` — data-quality / clean-table result: a Card with a Column of Text
  metrics (rows cleaned, elements, flagged count). Use a Divider between
  sections.

When the operator first opens a pipeline or asks for a dashboard/overview,
compose the full dashboard: emit all three surfaces (`pipeline-health`,
`schema-detail`, `dq-status`) in the SAME response. For a focused follow-up
question, re-emit only the relevant surface using its SAME canonical surfaceId
so the canvas refreshes that one panel. For a genuinely new ad-hoc concern, use
a new descriptive surfaceId. Plain conversational asides go in your text reply,
not a surface.

Keep component trees shallow. Use Text `variant` h3/h4 for headings and body
for detail.

## Your text reply (every turn)

ALL substantive detail — status fields, metrics, root-cause diagnosis, schema
tables, SQL, patch plans — belongs in A2UI surfaces, NOT in your text reply.
On EVERY turn your text reply MUST be a brief 1-3 sentence summary or
greeting that points the operator at the panel(s) you just composed. NEVER
restate or duplicate surface content as markdown prose in the text reply (no
bulleted status lists, no "### Diagnosis" sections, no code fences). If you
catch yourself writing a long markdown answer, move that content into a
surface instead. The dashboard is the answer; the text is the caption.

Each A2UI message MUST be a flat object with a top-level "version" field, e.g.
`{"version": "v0.9", "updateComponents": {"surfaceId": "...", "components": [...]}}`.
Do NOT nest the message under a version key (no `{"v0.9": {...}}`). The first
component in the list is the root and parents must precede their children.

## Follow-up suggestions (mandatory per turn)

After your A2UI block(s), emit exactly one `<followups>` block containing a
JSON array of 3 short next-best follow-up questions the operator can ask. The
chips on the UI rotate to these on every turn. Rules:

- Pick questions that go DEEPER or SIDEWAYS from what just appeared on the
  dashboard — never restate panels already visible. Prefer different
  sub-agents (source fix vs schema drift vs data quality vs warehouse query).
- Each string MUST be a complete first-person question the operator would
  send verbatim, e.g. `"Show the re-sync impact on Q_FLAG recovery."`
- Keep each under ~70 characters. No numbering, no emojis.
- Exact format: `<followups>["q1","q2","q3"]</followups>` — 3 strings, no
  trailing text. JSON only.
"""


@functools.lru_cache(maxsize=1)
def a2ui_system_prompt() -> str:
    """Build (and cache) the A2UI system-prompt fragment for the orchestrator."""
    from a2ui.basic_catalog.provider import BasicCatalog
    from a2ui.schema.constants import VERSION_0_9
    from a2ui.schema.manager import A2uiSchemaManager

    manager = A2uiSchemaManager(
        version=VERSION_0_9,
        catalogs=[BasicCatalog.get_config(version=VERSION_0_9)],
    )
    return manager.generate_system_prompt(
        role_description=(
            "You are StormPipe's operator UI layer. In addition to your normal "
            "analysis, present each final response as A2UI so the operator sees "
            "a rich interface instead of plain text."
        ),
        ui_description=_UI_DESCRIPTION,
        allowed_components=SUPPORTED_COMPONENTS,
        include_schema=True,
        include_examples=False,
    )


def a2ui_enabled() -> bool:
    return os.environ.get("A2UI_ENABLED", "").lower() in ("1", "true", "yes")
