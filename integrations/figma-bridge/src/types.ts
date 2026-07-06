export interface CanonicalFigmaCut {
  section_id: string;
  section_type: string;
  layout_type: string;
  headline?: string | null;
  subcopy?: string | null;
  supporting_text?: string | null;
  image_url?: string | null;
  background_style?: string | null;
}

export interface CanonicalFigmaPayload {
  schema_version: '1.0';
  project: {
    id: string;
    name: string;
    category: string;
  };
  brand: {
    name: string;
    primary_color: string;
    font_family: string;
  };
  page: {
    canvas_width: number;
    channel: string;
    style_key: string;
  };
  cuts: CanonicalFigmaCut[];
}

export interface CompiledFigmaLayout {
  type: 'FRAME';
  name: string;
  width: number;
  layoutMode: 'VERTICAL';
  primaryAxisSizingMode: 'AUTO';
  counterAxisSizingMode: 'FIXED';
  itemSpacing: number;
  fills: Array<Record<string, unknown>>;
  children: Array<Record<string, any>>;
}
