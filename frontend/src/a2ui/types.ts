// Minimal A2UI v0.9 model — only the parts StormPipe's agent emits and the
// renderer supports. The full spec is larger; we intentionally cover the
// BasicCatalog subset declared in app/a2ui_setup.py SUPPORTED_COMPONENTS.

export type DynamicString = string | { path: string };

export type ChildList = string[] | { componentId: string; path: string };

export interface A2uiComponent {
  id: string;
  component: string;
  // Loose bag of props; renderer reads what each component type needs.
  [key: string]: unknown;
}

export interface A2uiMessage {
  version?: string;
  createSurface?: { surfaceId: string; catalogId?: string };
  updateComponents?: { surfaceId: string; components: A2uiComponent[] };
  updateDataModel?: { surfaceId: string; path: string; value: unknown };
}

// A fully-folded surface ready to render: components indexed by id, the root
// (first component in arrival order), and the merged data model.
export interface Surface {
  surfaceId: string;
  rootId: string | null;
  components: Record<string, A2uiComponent>;
  data: Record<string, unknown>;
}
