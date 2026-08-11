export type VisualKind = "image" | "html_graphic" | "composed_product";

export interface VisualCard {
  icon_key?: string;
  title: string;
  body: string;
  tone?: "positive" | "muted" | "warning";
  verification_status: "confirmed";
  provenance_label?: string;
  source_fact_ids: string[];
}

export interface VisualTableRow {
  label: string;
  value: string;
  verification_status: "confirmed";
  provenance_label?: string;
  source_fact_ids: string[];
}

export interface VisualNumericHighlight {
  label: string;
  value: string;
  body?: string;
  verification_status: "confirmed";
  provenance_label?: string;
  source_fact_ids: string[];
}

export interface VisualStep {
  step: number;
  title: string;
  body: string;
  verification_status: "confirmed";
  provenance_label?: string;
  source_fact_ids: string[];
}

export interface VisualChecklistItem {
  text: string;
  kind?: "seller_action";
  verification_status: "confirmed" | "action_required";
  provenance_label?: string;
  source_fact_ids: string[];
}

export interface VisualPayload {
  layout_variant:
    | "hero_overlay"
    | "hero_product_right"
    | "hero_product_center"
    | "image_text"
    | "comparison_cards"
    | "benefit_cards"
    | "numeric_highlights"
    | "spec_table"
    | "steps"
    | "checklist";
  eyebrow?: string;
  badges?: string[];
  image_fit?: "contain" | "cover";
  cards?: VisualCard[];
  highlights?: VisualNumericHighlight[];
  table_rows?: VisualTableRow[];
  steps?: VisualStep[];
  items?: VisualChecklistItem[];
  palette?: { surface?: string; accent?: string; text?: string };
  product_fit?: "contain";
  text_safe_area?: "left" | "bottom";
  background_token?: "surface_mint" | "surface_ink" | "surface_sand";
  decoration_tokens?: string[];
  missing_state?: "product_photo_required" | "quality_review_required" | "source_approval_required" | "ai_redesign_required";
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
    "numeric_highlights",
    "spec_table",
    "steps",
    "checklist",
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
    const isText = (value: unknown): value is string => typeof value === "string" && value.trim().length > 0;
    const isGrounded = (item: unknown, fields: string[]) => {
      if (!item || typeof item !== "object") return false;
      const record = item as Record<string, unknown>;
      return (
        record.verification_status === "confirmed" &&
        Array.isArray(record.source_fact_ids) &&
        record.source_fact_ids.length > 0 &&
        record.source_fact_ids.every(isText) &&
        fields.every((field) => isText(record[field]))
      );
    };
    if (layout === "comparison_cards" || layout === "benefit_cards") {
      const cards = payload.cards;
      if (!Array.isArray(cards) || cards.length === 0) issues.push("html_cards_required");
      else if (!cards.every((card) => isGrounded(card, ["title", "body"]))) issues.push("html_card_grounding_required");
    }
    if (layout === "numeric_highlights") {
      const highlights = payload.highlights;
      if (!Array.isArray(highlights) || highlights.length === 0) issues.push("numeric_highlights_required");
      else if (!highlights.every((item) => isGrounded(item, ["label", "value"]))) issues.push("numeric_highlight_grounding_required");
    }
    if (layout === "spec_table") {
      const rows = payload.table_rows;
      if (!Array.isArray(rows) || rows.length === 0) issues.push("spec_rows_required");
      else if (!rows.every((row) => isGrounded(row, ["label", "value"]))) issues.push("spec_row_grounding_required");
    }
    if (layout === "steps") {
      const steps = payload.steps;
      if (!Array.isArray(steps) || steps.length === 0) issues.push("html_steps_required");
      else if (!steps.every((step) => {
        const record = step as Record<string, unknown>;
        return typeof record.step === "number" && record.step > 0 && isGrounded(step, ["title", "body"]);
      })) issues.push("html_step_grounding_required");
    }
    if (layout === "checklist") {
      const items = payload.items;
      if (!Array.isArray(items) || items.length === 0) issues.push("html_checklist_required");
      else if (!items.every((item) => {
        if (isGrounded(item, ["text"])) return true;
        const record = item as Record<string, unknown>;
        return record.kind === "seller_action" && record.verification_status === "action_required" && Array.isArray(record.source_fact_ids) && record.source_fact_ids.length === 0 && isText(record.text);
      })) issues.push("html_checklist_grounding_required");
    }
  }
  return issues;
}
