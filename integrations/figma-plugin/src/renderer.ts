import { DetailPagePackage } from './contracts';
import { renderVisualCommercePage } from './visual-renderer';

interface RenderWarning {
  code: string;
  section_type: string;
  message: string;
}

function hexToRgb(hex: string): { r: number; g: number; b: number } {
  const clean = hex.replace('#', '');
  if (clean.length === 3) {
    const num = parseInt(clean, 16);
    return {
      r: ((num >> 8) & 0xf) / 15,
      g: ((num >> 4) & 0xf) / 15,
      b: (num & 0xf) / 15
    };
  }
  const num = parseInt(clean, 16) || 0;
  return {
    r: ((num >> 16) & 0xff) / 255,
    g: ((num >> 8) & 0xff) / 255,
    b: (num & 0xff) / 255
  };
}

export async function renderDetailPage(
  pkg: DetailPagePackage,
  imageBytes: Record<string, Uint8Array>,
  figmaObj: any
) {
  const { payload } = pkg;
  if (payload.visual_layout?.layout_version === 'commerce_visual_v1') {
    return renderVisualCommercePage(pkg, imageBytes, figmaObj);
  }

  const warnings: RenderWarning[] = [];
  const sections: any[] = [];

  const root = figmaObj.createFrame();
  root.name = `Sellform / ${payload.project.name}`;
  root.resize(860, 100);
  root.layoutMode = 'VERTICAL';
  if ('primaryAxisSizingMode' in root) {
    root.primaryAxisSizingMode = 'AUTO';
  }
  if ('counterAxisSizingMode' in root) {
    root.counterAxisSizingMode = 'FIXED';
  }

  const requestedFontFamily = payload.brand.font_family || 'Inter';
  let fontFamily = requestedFontFamily;

  // Attempt to load fonts
  if (figmaObj.loadFontAsync) {
    try {
      await figmaObj.loadFontAsync({ family: requestedFontFamily, style: 'Regular' });
      await figmaObj.loadFontAsync({ family: requestedFontFamily, style: 'Bold' });
    } catch (err) {
      fontFamily = 'Inter';
      await figmaObj.loadFontAsync({ family: fontFamily, style: 'Regular' });
      await figmaObj.loadFontAsync({ family: fontFamily, style: 'Bold' });
    }
  }

  for (const cut of payload.cuts) {
    const sectionFrame = figmaObj.createFrame();
    sectionFrame.name = cut.section_type;
    sectionFrame.resize(860, 100);
    sectionFrame.layoutMode = 'VERTICAL';
    if ('primaryAxisSizingMode' in sectionFrame) {
      sectionFrame.primaryAxisSizingMode = 'AUTO';
    }
    if ('counterAxisSizingMode' in sectionFrame) {
      sectionFrame.counterAxisSizingMode = 'FIXED';
    }

    sectionFrame.paddingLeft = 56;
    sectionFrame.paddingRight = 56;
    sectionFrame.paddingTop = 64;
    sectionFrame.paddingBottom = 64;
    sectionFrame.itemSpacing = 16;

    // Background style / color
    sectionFrame.fills = [{ type: 'SOLID', color: { r: 0.98, g: 0.98, b: 0.98 } }];

    // Render image slot if required
    if (cut.section_type !== 'product_information' && cut.image_url) {
      const bytes = imageBytes[cut.image_url];
      if (bytes && bytes.length > 0) {
        try {
          const image = figmaObj.createImage(bytes);
          const rect = figmaObj.createRectangle();
          rect.name = 'image_slot';
          rect.resize(748, 400);
          rect.fills = [{
            type: 'IMAGE',
            imageHash: image.hash,
            scaleMode: 'FILL'
          }];
          sectionFrame.appendChild(rect);
        } catch (err) {
          warnings.push({
            code: 'IMAGE_RENDER_FAILED',
            section_type: cut.section_type,
            message: `Failed to paint image for section ${cut.section_type}`
          });
        }
      } else {
        // Create placeholder
        const placeholder = figmaObj.createRectangle();
        placeholder.name = 'image_placeholder';
        placeholder.resize(748, 200);
        placeholder.fills = [{ type: 'SOLID', color: { r: 0.9, g: 0.9, b: 0.9 } }];
        sectionFrame.appendChild(placeholder);

        warnings.push({
          code: 'IMAGE_PLACEHOLDER_USED',
          section_type: cut.section_type,
          message: `Asset not available. Image placeholder used in section ${cut.section_type}`
        });
      }
    }

    // Render Text fields
    const texts = [
      { key: 'headline', value: cut.headline, isBold: true, size: 24 },
      { key: 'subcopy', value: cut.subcopy, isBold: false, size: 14 },
      { key: 'supporting_text', value: cut.supporting_text, isBold: false, size: 11 }
    ];

    for (const txt of texts) {
      if (txt.value && txt.value.trim() !== '') {
        const textNode = figmaObj.createText();
        
        // Font name assignment
        try {
          textNode.fontName = { family: fontFamily, style: txt.isBold ? 'Bold' : 'Regular' };
        } catch (e) {
          // Fallback font style
        }

        textNode.fontSize = txt.size;
        textNode.characters = txt.value;
        textNode.layoutGrow = 1;

        if (txt.key === 'headline') {
          const hex = payload.brand.primary_color || '#5B7CFA';
          textNode.fills = [{ type: 'SOLID', color: hexToRgb(hex) }];
        } else if (txt.key === 'subcopy') {
          textNode.fills = [{ type: 'SOLID', color: { r: 0.2, g: 0.2, b: 0.2 } }];
        } else {
          textNode.fills = [{ type: 'SOLID', color: { r: 0.5, g: 0.5, b: 0.5 } }];
        }

        sectionFrame.appendChild(textNode);
      }
    }

    root.appendChild(sectionFrame);
    sections.push(sectionFrame);
  }

  return {
    root,
    sections,
    warnings
  };
}
