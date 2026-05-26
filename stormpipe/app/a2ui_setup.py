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
Render the operator response as agent-driven UI. Choose layout by intent:

- Pipeline health overview: a Card whose child is a Column. Lead with a Row
  holding a status Icon (`check_circle` healthy, `warning` warning, `error`
  error) and a Text title (variant h3). Follow with Text rows for sync status,
  row count, and the headerless-misparse finding.
- Schema drift / misparse detail: Tabs with one tab per concern (e.g.
  "Detected", "Recoverable", "Lost"), each tab's child a Column of Text rows.
- Data-quality / clean-table result: a Card with a Column of Text metrics
  (rows cleaned, elements, flagged count). Use a Divider between sections.
- Plain conversational answers: a single Text component (variant body).

Keep component trees shallow. Use Text `variant` h3/h4 for headings and body
for detail. Prefer one surface per response.

Each A2UI message MUST be a flat object with a top-level "version" field, e.g.
`{"version": "v0.9", "updateComponents": {"surfaceId": "...", "components": [...]}}`.
Do NOT nest the message under a version key (no `{"v0.9": {...}}`). The first
component in the list is the root and parents must precede their children.
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
