export type VisualKind = "image" | "html_graphic";

export interface VisualCard {
  icon_key?: string;
  title: string;
  body: string;
  tone?: "positive" | "muted" | "warning";
}

export interface VisualTableRow {
  label: string;
  value: string;
  verification_status?: string;
}

export interface VisualPayload {
  layout_variant:
    | "hero_overlay"
    | "image_text"
    | "comparison_cards"
    | "benefit_cards"
    | "spec_table";
  eyebrow?: string;
  badges?: string[];
  cards?: VisualCard[];
  table_rows?: VisualTableRow[];
  palette?: { surface?: string; accent?: string; text?: string };
}

export interface DetailPageSectionVisual {
  id?: string;
  section_type: string;
  title?: string | null;
  body_copy?: string | null;
  body?: string | null;
  image_asset_id?: string | null;
  visual_kind?: VisualKind | null;
  visual_payload?: VisualPayload | null;
  sort_order: number;
  is_visible?: boolean;
}

export function validateSectionVisual(
  section: DetailPageSectionVisual
): string[] {
  const issues: string[] = [];
  const kind = section.visual_kind;
  const payload = (section.visual_payload || {}) as Record<string, unknown>;
  const validKinds: Array<VisualKind | null | undefined> = [
    "image",
    "html_graphic",
    null,
    undefined,
  ];
  const validLayouts = new Set([
    "hero_overlay",
    "image_text",
    "comparison_cards",
    "benefit_cards",
    "spec_table",
  ]);

  if (!validKinds.includes(kind)) {
    issues.push("invalid_visual_kind");
    return issues;
  }
  if (kind === "image" && !section.image_asset_id) {
    issues.push("image_asset_required");
  }
  if (kind === "html_graphic") {
    const layout = payload.layout_variant as string | undefined;
    if (!layout || !validLayouts.has(layout)) {
      issues.push("invalid_html_layout");
    }
    if (
      (layout === "comparison_cards" || layout === "benefit_cards") &&
      (!payload.cards || (payload.cards as unknown[]).length === 0)
    ) {
      issues.push("html_cards_required");
    }
    if (layout === "spec_table" && (!payload.table_rows || (payload.table_rows as unknown[]).length === 0)) {
      issues.push("spec_rows_required");
    }
  }
  return issues;
}
