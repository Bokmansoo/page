import {
  CanonicalFigmaPayload,
  CompiledFigmaLayout
} from './types';

export type FigmaRenderPayload = CanonicalFigmaPayload;

export interface FigmaExecutionResult {
  rootNodeId: string;
  imageSlots: Record<string, string>;
}

function collectResultCandidates(value: any): any[] {
  if (value === null || value === undefined) return [];
  if (Array.isArray(value)) return value.flatMap(collectResultCandidates);
  if (typeof value === 'object') {
    return [value, ...Object.values(value).flatMap(collectResultCandidates)];
  }
  if (typeof value === 'string') {
    try {
      return collectResultCandidates(JSON.parse(value));
    } catch {
      const match = value.match(/rootNodeId["'\s:=]+([0-9]+[:\-][0-9]+)/i);
      return match ? [{ rootNodeId: match[1] }] : [];
    }
  }
  return [];
}

export function parseFigmaExecutionResult(response: any): FigmaExecutionResult {
  for (const candidate of collectResultCandidates(response)) {
    const rootNodeId = candidate.rootNodeId || candidate.root_node_id || candidate.nodeId;
    if (typeof rootNodeId === 'string' && /^[0-9]+[:\-][0-9]+$/.test(rootNodeId)) {
      return {
        rootNodeId: rootNodeId.replace('-', ':'),
        imageSlots: candidate.imageSlots || candidate.image_slots || {}
      };
    }
  }
  const error = new Error('INVALID_MCP_RESPONSE: Figma did not return a created node id.');
  (error as any).error_code = 'INVALID_MCP_RESPONSE';
  throw error;
}

export class FigmaRenderer {
  public validateImageUrls(payload: FigmaRenderPayload): void {
    const invalidProtocols = ['localhost', '127.0.0.1', 'file:'];
    for (const cut of payload.cuts) {
      if (cut.image_url) {
        const urlLower = cut.image_url.toLowerCase();
        if (invalidProtocols.some(p => urlLower.includes(p))) {
          const err = new Error(`Asset image URL is not public: ${cut.image_url}`);
          (err as any).error_code = 'ASSET_URL_NOT_PUBLIC';
          throw err;
        }
        if (!urlLower.startsWith('https://') && !urlLower.startsWith('http://')) {
          const err = new Error(`Invalid image protocol: ${cut.image_url}`);
          (err as any).error_code = 'ASSET_URL_NOT_PUBLIC';
          throw err;
        }
      }
    }
  }

  public parseFileKey(fileUrl: string): string {
    // Figma URL format: https://www.figma.com/design/FILE_KEY/FILE_NAME?...
    try {
      const url = new URL(fileUrl);
      const paths = url.pathname.split('/');
      // design 또는 file 뒤에 나오는 첫 경로가 FILE_KEY입니다.
      const designIdx = paths.findIndex(p => p === 'design' || p === 'file');
      if (designIdx !== -1 && paths[designIdx + 1]) {
        return paths[designIdx + 1];
      }
      throw new Error('Could not find design file key in URL path.');
    } catch (err) {
      const error = new Error('Invalid Figma design file URL format.');
      (error as any).error_code = 'INVALID_FIGMA_URL';
      throw error;
    }
  }

  public compilePayloadToFigmaNodes(payload: FigmaRenderPayload): CompiledFigmaLayout {
    this.validateImageUrls(payload);

    if (payload.schema_version !== '1.0') {
      const error = new Error(`Unsupported Figma payload schema: ${payload.schema_version}`);
      (error as any).error_code = 'INVALID_REQUEST';
      throw error;
    }

    const canvasWidth = payload.page.canvas_width || 860;
    const themeColor = payload.brand.primary_color || '#3B82F6';
    const fontFamily = payload.brand.font_family || 'Inter';
    const primaryColorRgb = this.hexToRgb(themeColor);

    // Build children nodes from cuts
    const childrenNodes = payload.cuts.map((cut, index) => {
      const cutChildren: any[] = [];

      // Headline / Title text node
      if (cut.headline) {
        cutChildren.push({
          type: 'TEXT',
          name: 'Headline',
          characters: cut.headline,
          fontSize: 28,
          fills: [{ type: 'SOLID', color: primaryColorRgb }],
          fontName: { family: fontFamily, style: 'Bold' }
        });
      }

      // Subcopy text node
      if (cut.subcopy) {
        cutChildren.push({
          type: 'TEXT',
          name: 'Subcopy',
          characters: cut.subcopy,
          fontSize: 16,
          fills: [{ type: 'SOLID', color: { r: 0.2, g: 0.2, b: 0.2 } }],
          fontName: { family: fontFamily, style: 'Regular' }
        });
      }

      // Supporting copy text node (e.g. Badge / Small disclaimer)
      if (cut.supporting_text) {
        cutChildren.push({
          type: 'TEXT',
          name: 'Supporting Copy',
          characters: cut.supporting_text,
          fontSize: 12,
          fills: [{ type: 'SOLID', color: { r: 0.5, g: 0.5, b: 0.5 } }],
          fontName: { family: fontFamily, style: 'Italic' }
        });
      }

      // Image node represented as a placeholder rectangle node with image fills
      if (cut.image_url) {
        cutChildren.push({
          type: 'RECTANGLE',
          name: `Image Slot (${cut.section_type})`,
          width: canvasWidth - 48,
          height: 480,
          fills: [{ type: 'SOLID', color: { r: 0.92, g: 0.94, b: 0.98 } }]
        });
      }

      // Single Cut Frame container (Auto Layout)
      return {
        type: 'FRAME',
        name: `Cut ${index + 1}: ${cut.section_type}`,
        width: canvasWidth,
        layoutMode: 'VERTICAL',
        primaryAxisSizingMode: 'AUTO',
        counterAxisSizingMode: 'FIXED',
        itemSpacing: 12,
        paddingLeft: 24,
        paddingRight: 24,
        paddingTop: 32,
        paddingBottom: 32,
        fills: [{ type: 'SOLID', color: { r: 0.98, g: 0.98, b: 0.98 } }],
        children: cutChildren
      };
    });

    // Parent Frame containing all cuts (Auto Layout)
    return {
      type: 'FRAME',
      name: `Sellform / ${payload.project.name}`,
      width: canvasWidth,
      layoutMode: 'VERTICAL',
      primaryAxisSizingMode: 'AUTO',
      counterAxisSizingMode: 'FIXED',
      itemSpacing: 24,
      fills: [{ type: 'SOLID', color: { r: 1, g: 1, b: 1 } }],
      children: childrenNodes
    };
  }

  public buildUseFigmaCode(payload: FigmaRenderPayload): string {
    this.compilePayloadToFigmaNodes(payload);
    const serialized = JSON.stringify(payload);
    return `
const payload = ${serialized};
const requestedFamily = payload.brand.font_family || "Inter";
let regularFont = { family: requestedFamily, style: "Regular" };
try {
  await figma.loadFontAsync(regularFont);
} catch (_) {
  regularFont = { family: "Inter", style: "Regular" };
  await figma.loadFontAsync(regularFont);
}
const hexToRgb = (hex) => {
  const clean = String(hex || "#5B7CFA").replace("#", "");
  const value = parseInt(clean, 16);
  return {
    r: ((value >> 16) & 255) / 255,
    g: ((value >> 8) & 255) / 255,
    b: (value & 255) / 255
  };
};
const createText = (name, characters, size, color) => {
  const node = figma.createText();
  node.name = name;
  node.fontName = regularFont;
  node.fontSize = size;
  node.characters = characters || "";
  node.fills = [{ type: "SOLID", color }];
  node.textAutoResize = "HEIGHT";
  node.layoutAlign = "STRETCH";
  return node;
};
const root = figma.createFrame();
root.name = "Sellform / " + payload.project.name;
root.resize(payload.page.canvas_width || 860, 100);
root.layoutMode = "VERTICAL";
root.primaryAxisSizingMode = "AUTO";
root.counterAxisSizingMode = "FIXED";
root.itemSpacing = 24;
root.fills = [{ type: "SOLID", color: { r: 1, g: 1, b: 1 } }];
const imageSlots = {};
for (let index = 0; index < payload.cuts.length; index += 1) {
  const cut = payload.cuts[index];
  const frame = figma.createFrame();
  frame.name = "Cut " + (index + 1) + ": " + cut.section_type;
  frame.resize(payload.page.canvas_width || 860, 100);
  frame.layoutMode = "VERTICAL";
  frame.primaryAxisSizingMode = "AUTO";
  frame.counterAxisSizingMode = "FIXED";
  frame.itemSpacing = 12;
  frame.paddingLeft = 24;
  frame.paddingRight = 24;
  frame.paddingTop = 32;
  frame.paddingBottom = 32;
  frame.fills = [{ type: "SOLID", color: { r: 0.98, g: 0.98, b: 0.98 } }];
  if (cut.headline) frame.appendChild(createText("Headline", cut.headline, 28, hexToRgb(payload.brand.primary_color)));
  if (cut.subcopy) frame.appendChild(createText("Subcopy", cut.subcopy, 16, { r: 0.2, g: 0.2, b: 0.2 }));
  if (cut.supporting_text) frame.appendChild(createText("Supporting Text", cut.supporting_text, 12, { r: 0.5, g: 0.5, b: 0.5 }));
  if (cut.image_url) {
    const slot = figma.createRectangle();
    slot.name = "SellformImageSlot:" + cut.section_id;
    slot.resize((payload.page.canvas_width || 860) - 48, 480);
    slot.fills = [{ type: "SOLID", color: { r: 0.92, g: 0.94, b: 0.98 } }];
    frame.appendChild(slot);
    imageSlots[cut.section_id] = slot.id;
  }
  root.appendChild(frame);
}
figma.currentPage.appendChild(root);
figma.currentPage.selection = [root];
figma.viewport.scrollAndZoomIntoView([root]);
return JSON.stringify({ rootNodeId: root.id, imageSlots });
`.trim();
  }

  private hexToRgb(hex: string): { r: number; g: number; b: number } {
    const cleanHex = hex.replace('#', '');
    const num = parseInt(cleanHex, 16);
    return {
      r: ((num >> 16) & 255) / 255,
      g: ((num >> 8) & 255) / 255,
      b: (num & 255) / 255
    };
  }
}
