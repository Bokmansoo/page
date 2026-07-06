import { DetailPagePackage, VisualCommerceCut } from './contracts';

export interface VisualRenderWarning {
  code: string;
  section_type: string;
  message: string;
}

function hexToRgb(hex: string): { r: number; g: number; b: number } {
  const clean = (hex || '#2D7DFF').replace('#', '');
  const num = parseInt(clean.length === 3
    ? clean.split('').map((part) => `${part}${part}`).join('')
    : clean, 16) || 0x2d7dff;

  return {
    r: ((num >> 16) & 0xff) / 255,
    g: ((num >> 8) & 0xff) / 255,
    b: (num & 0xff) / 255,
  };
}

function solid(hex: string) {
  return [{ type: 'SOLID', color: hexToRgb(hex) }];
}

function sectionHeight(cut: VisualCommerceCut): number {
  if (cut.layout_type.includes('hero')) return 560;
  if (cut.layout_type.includes('problem')) return 520;
  if (cut.layout_type.includes('solution')) return 560;
  if (cut.layout_type.includes('benefit')) return 520;
  if (cut.layout_type.includes('feature')) return 500;
  if (cut.layout_type.includes('purchase')) return 560;
  return cut.emphasis_level >= 2 ? 560 : 500;
}

function backgroundFill(tone: string) {
  if (tone === 'warm_neutral') return solid('#F7F1E8');
  if (tone === 'dark_contrast') return solid('#13213A');
  if (tone === 'clean_white') return solid('#FFFFFF');
  return solid('#EFF6FF');
}

async function loadFonts(figmaObj: any, fontFamily: string): Promise<string> {
  if (!figmaObj.loadFontAsync) return fontFamily;

  try {
    await figmaObj.loadFontAsync({ family: fontFamily, style: 'Regular' });
    await figmaObj.loadFontAsync({ family: fontFamily, style: 'Bold' });
    return fontFamily;
  } catch (err) {
    await figmaObj.loadFontAsync({ family: 'Inter', style: 'Regular' });
    await figmaObj.loadFontAsync({ family: 'Inter', style: 'Bold' });
    return 'Inter';
  }
}

function createText(figmaObj: any, options: {
  name: string;
  characters: string;
  family: string;
  bold?: boolean;
  size: number;
  color: string;
}) {
  const node = figmaObj.createText();
  node.name = options.name;
  try {
    node.fontName = { family: options.family, style: options.bold ? 'Bold' : 'Regular' };
  } catch (err) {
    // Font assignment can fail in tests or in Figma if the selected font has no style.
  }
  node.fontSize = options.size;
  node.characters = options.characters;
  node.fills = solid(options.color);
  return node;
}

function resolveImageBytes(
  cut: VisualCommerceCut,
  imageBytes: Record<string, Uint8Array>
): Uint8Array | undefined {
  const candidates = [
    cut.visual_slot?.image_url,
    cut.visual_slot?.asset_ref,
    cut.image_url,
    cut.image_asset_ref,
  ].filter(Boolean) as string[];

  for (const key of candidates) {
    if (imageBytes[key] && imageBytes[key].length > 0) return imageBytes[key];
  }
  return undefined;
}

function appendVisualBlock(
  figmaObj: any,
  section: any,
  cut: VisualCommerceCut,
  imageBytes: Record<string, Uint8Array>,
  warnings: VisualRenderWarning[]
) {
  const bytes = resolveImageBytes(cut, imageBytes);

  if (cut.visual_slot?.kind === 'image' && bytes) {
    const image = figmaObj.createImage(bytes);
    const imageNode = figmaObj.createRectangle();
    imageNode.name = 'visual_image';
    imageNode.resize(748, cut.emphasis_level >= 2 ? 300 : 240);
    imageNode.cornerRadius = 28;
    imageNode.fills = [{
      type: 'IMAGE',
      imageHash: image.hash,
      scaleMode: 'FILL',
    }];
    section.appendChild(imageNode);
    return;
  }

  const placeholder = figmaObj.createRectangle();
  placeholder.name = 'visual_placeholder';
  placeholder.resize(748, cut.emphasis_level >= 2 ? 300 : 220);
  placeholder.cornerRadius = 28;
  placeholder.fills = solid('#DCEBFF');
  section.appendChild(placeholder);

  warnings.push({
    code: 'VISUAL_PLACEHOLDER_USED',
    section_type: cut.section_type,
    message: `${cut.section_type} 섹션에 사용할 이미지가 없어 비주얼 플레이스홀더를 렌더링했습니다.`,
  });
}

export async function renderVisualCommercePage(
  pkg: DetailPagePackage,
  imageBytes: Record<string, Uint8Array>,
  figmaObj: any
) {
  const { payload } = pkg;
  const visualLayout = payload.visual_layout;
  if (!visualLayout) {
    throw new Error('MISSING_VISUAL_LAYOUT');
  }

  const warnings: VisualRenderWarning[] = [];
  const sections: any[] = [];
  const fontFamily = await loadFonts(figmaObj, payload.brand.font_family || 'Inter');

  // Style-key-aware primary colour: the brand color acts as baseline but the
  // selected sales strategy can shift the visual direction.
  const styleKey = visualLayout.style_key || payload.page?.style_key || 'default';
  const brandColor = payload.brand.primary_color || '#2D7DFF';
  let primaryColor: string;
  if (styleKey === 'lifestyle') {
    // Warm, soft direction — prefer brand color if it's warm, otherwise use amber
    primaryColor = brandColor !== '#2D7DFF' ? brandColor : '#D97706';
  } else if (styleKey === 'spec_focused') {
    // Strong info hierarchy — deep navy/indigo for readability
    primaryColor = brandColor !== '#2D7DFF' ? brandColor : '#1E3A5F';
  } else {
    // problem_solution and default — original cool blue
    primaryColor = brandColor;
  }

  const root = figmaObj.createFrame();
  root.name = `Sellform / ${payload.project.name} 상세페이지`;
  root.resize(visualLayout.width || 860, 100);
  root.layoutMode = 'VERTICAL';
  root.fills = solid('#F5F8FF');
  root.itemSpacing = 0;
  if ('primaryAxisSizingMode' in root) root.primaryAxisSizingMode = 'AUTO';
  if ('counterAxisSizingMode' in root) root.counterAxisSizingMode = 'FIXED';

  visualLayout.cuts.forEach((cut, index) => {
    const section = figmaObj.createFrame();
    section.name = `${String(index + 1).padStart(2, '0')}_${cut.section_type}`;
    section.resize(visualLayout.width || 860, sectionHeight(cut));
    section.layoutMode = 'VERTICAL';
    section.paddingLeft = 56;
    section.paddingRight = 56;
    section.paddingTop = index === 0 ? 64 : 48;
    section.paddingBottom = 48;
    section.itemSpacing = 20;
    section.fills = backgroundFill(cut.background_tone);
    if ('primaryAxisSizingMode' in section) section.primaryAxisSizingMode = 'AUTO';
    if ('counterAxisSizingMode' in section) section.counterAxisSizingMode = 'FIXED';

    const badgeWrap = figmaObj.createFrame();
    badgeWrap.name = 'badges';
    badgeWrap.layoutMode = 'HORIZONTAL';
    badgeWrap.itemSpacing = 8;
    badgeWrap.fills = [];
    badgeWrap.resize(748, 28);
    for (const badge of cut.badges || []) {
      const badgeText = createText(figmaObj, {
        name: 'badge_text',
        characters: badge,
        family: fontFamily,
        bold: true,
        size: 13,
        color: primaryColor,
      });
      badgeWrap.appendChild(badgeText);
    }
    section.appendChild(badgeWrap);

    if (index === 0 || cut.emphasis_level >= 2 || cut.visual_slot?.kind === 'image') {
      appendVisualBlock(figmaObj, section, cut, imageBytes, warnings);
    }

    section.appendChild(createText(figmaObj, {
      name: 'headline',
      characters: cut.headline,
      family: fontFamily,
      bold: true,
      size: index === 0 ? 36 : 28,
      color: cut.background_tone === 'dark_contrast' ? '#FFFFFF' : primaryColor,
    }));

    section.appendChild(createText(figmaObj, {
      name: 'body',
      characters: cut.subcopy,
      family: fontFamily,
      size: 17,
      color: cut.background_tone === 'dark_contrast' ? '#E8F0FF' : '#25324B',
    }));

    if (cut.supporting_text) {
      section.appendChild(createText(figmaObj, {
        name: 'supporting_text',
        characters: cut.supporting_text,
        family: fontFamily,
        size: 13,
        color: cut.background_tone === 'dark_contrast' ? '#B7C4D8' : '#667085',
      }));
    }

    if (index !== 0 && cut.visual_slot?.kind !== 'image') {
      appendVisualBlock(figmaObj, section, cut, imageBytes, warnings);
    }

    root.appendChild(section);
    sections.push(section);
  });

  return { root, sections, warnings };
}
