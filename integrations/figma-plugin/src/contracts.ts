export interface AdCut {
  section_id: string;
  section_type: string;
  layout_type: string;
  headline: string;
  subcopy: string;
  supporting_text: string | null;
  image_url: string | null;
  background_style: string;
}

export interface VisualSlot {
  kind: 'image' | 'placeholder';
  asset_ref: string | null;
  image_url: string | null;
  fallback_label: string;
}

export interface VisualCommerceCut {
  section_id: string;
  section_type: string;
  layout_type: string;
  headline: string;
  subcopy: string;
  supporting_text: string | null;
  image_role: string | null;
  image_asset_ref: string | null;
  image_url: string | null;
  visual_slot: VisualSlot;
  badges: string[];
  background_tone: string;
  emphasis_level: number;
}

export interface VisualLayout {
  layout_version: 'commerce_visual_v1';
  width: number;
  category: string;
  style_key: string;
  background_key: string;
  cuts: VisualCommerceCut[];
}

export interface BrandInfo {
  name: string;
  primary_color: string;
  font_family: string;
}

export interface ProjectInfo {
  id: string;
  name: string;
  category: string;
}

export interface PageInfo {
  canvas_width: number;
  channel: string;
  style_key: string;
}

export interface FigmaDesignPayload {
  schema_version: string;
  project: ProjectInfo;
  brand: BrandInfo;
  page: PageInfo;
  cuts: AdCut[];
  visual_layout?: VisualLayout;
}

export interface EmbeddedAsset {
  asset_ref: string;
  mime_type: string;
  base64: string;
}

export interface DetailPagePackage {
  schema_version: string;
  payload: FigmaDesignPayload;
  embedded_assets: EmbeddedAsset[];
}
