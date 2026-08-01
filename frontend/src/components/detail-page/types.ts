export type VisualKind = "image" | "html_graphic" | "composed_product";

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
    | "hero_product_right"
    | "hero_product_center"
    | "image_text"
    | "comparison_cards"
    | "benefit_cards"
    | "spec_table";
  eyebrow?: string;
  badges?: string[];
  cards?: VisualCard[];
  table_rows?: VisualTableRow[];
  palette?: { surface?: string; accent?: string; text?: string };
  product_fit?: "contain";
  text_safe_area?: "left" | "bottom";
  background_token?: "surface_mint" | "surface_ink" | "surface_sand";
  decoration_tokens?: string[];
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
    "composed_product",
    null,
    undefined,
  ];
  const validLayouts = new Set([
    "hero_overlay",
    "hero_product_right",
    "hero_product_center",
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
  if (kind === "composed_product") {
    if (!section.image_asset_id) issues.push("image_asset_required");
    if (!new Set(["hero_product_right", "hero_product_center"]).has(payload.layout_variant as string)) {
      issues.push("invalid_composed_product_layout");
    }
    if (payload.product_fit !== "contain") issues.push("invalid_product_fit");
    if (!new Set(["left", "bottom"]).has(payload.text_safe_area as string)) {
      issues.push("invalid_text_safe_area");
    }
    if (!new Set(["surface_mint", "surface_ink", "surface_sand"]).has(payload.background_token as string)) {
      issues.push("invalid_background_token");
    }
    if (!Array.isArray(payload.decoration_tokens)) {
      issues.push("decoration_tokens_required");
    }
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
