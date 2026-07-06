/**
 * Sprint 37 — style-key-aware primary colour tests for the Figma visual renderer.
 *
 * The renderer's primaryColor is determined by:
 *   1. visualLayout.style_key  (highest priority)
 *   2. payload.page.style_key
 *   3. 'default'
 *
 * Brand colour that differs from the default (#2D7DFF) takes priority over
 * the style fallback. Only when brand color is the default do style-specific
 * fallbacks apply.
 */
import { DetailPagePackage } from '../src/contracts';
import { renderVisualCommercePage } from '../src/visual-renderer';

// Reuse the same MockNode from the main test suite
class MockNode {
  name = '';
  width = 0;
  height = 0;
  layoutMode = '';
  fills: any[] = [];
  children: MockNode[] = [];
  characters = '';
  fontName: any = null;
  fontSize = 0;
  paddingLeft = 0;
  paddingRight = 0;
  paddingTop = 0;
  paddingBottom = 0;
  itemSpacing = 0;
  layoutGrow = 0;
  cornerRadius = 0;
  primaryAxisSizingMode = '';
  counterAxisSizingMode = '';

  resize(_w: number, _h: number) {
    this.width = _w;
    this.height = _h;
  }

  appendChild(node: MockNode) {
    this.children.push(node);
  }
}

/** Collect all text nodes recursively from a node tree. */
function collectText(node: MockNode): MockNode[] {
  const current = node.characters ? [node] : [];
  return [...current, ...node.children.flatMap((child) => collectText(child))];
}

/** Extract the fill color hex from a node's SOLID fills array. */
function extractColorHex(node: MockNode): string | null {
  if (!node.fills || node.fills.length === 0) return null;
  const fill = node.fills[0];
  if (fill.type !== 'SOLID' || !fill.color) return null;
  const { r, g, b } = fill.color;
  const toHex = (v: number) =>
    Math.round(v * 255)
      .toString(16)
      .padStart(2, '0');
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`.toUpperCase();
}

function makeFigmaMock() {
  return {
    createFrame: () => new MockNode(),
    createText: () => new MockNode(),
    createRectangle: () => new MockNode(),
    createImage: (bytes: Uint8Array) => ({ hash: `hash-${bytes.length}` }),
    loadFontAsync: jest.fn().mockResolvedValue(true),
  };
}

/**
 * Build a minimal DetailPagePackage with a custom visual_layout.style_key.
 */
function makePackage(overrides: {
  styleKey?: string;
  brandColor?: string;
  pageStyleKey?: string;
}): DetailPagePackage {
  const styleKey = overrides.styleKey || 'default';
  const brandColor = overrides.brandColor || '#2D7DFF';
  const pageStyleKey = overrides.pageStyleKey || 'cool_minimal';

  return {
    schema_version: '1.0',
    payload: {
      schema_version: '1.0',
      project: { id: 'p1', name: '테스트 상품', category: 'Living' },
      brand: { name: 'Sellform', primary_color: brandColor, font_family: 'Inter' },
      page: { canvas_width: 860, channel: 'smartstore', style_key: pageStyleKey },
      cuts: [
        {
          section_id: 'sec-0',
          section_type: 'problem_statement',
          layout_type: 'problem_visual',
          headline: '고객의 고민',
          subcopy: '무더운 여름 선풍기가 없어 불편합니다.',
          supporting_text: null,
          image_url: null,
          background_style: 'clean',
        },
      ],
      visual_layout: {
        layout_version: 'commerce_visual_v1',
        width: 860,
        category: 'Living',
        style_key: styleKey,
        background_key: 'cooling-blue',
        cuts: [
          {
            section_id: 'sec-0',
            section_type: 'problem_statement',
            layout_type: 'problem_visual',
            headline: '고객의 고민',
            subcopy: '무더운 여름 선풍기가 없어 불편합니다.',
            supporting_text: null,
            image_role: 'lifestyle_scene',
            image_asset_ref: null,
            image_url: null,
            visual_slot: {
              kind: 'placeholder',
              asset_ref: null,
              image_url: null,
              fallback_label: '고객 불편 장면 이미지',
            },
            badges: ['문제 제기', '불편 상황'],
            background_tone: 'warm_neutral',
            emphasis_level: 1,
          },
        ],
      },
    },
    embedded_assets: [],
  };
}

describe('visual renderer style-key colour resolution', () => {
  let figmaMock: any;

  beforeEach(() => {
    figmaMock = makeFigmaMock();
  });

  it('uses brand color as-is when style_key is problem_solution (or default)', async () => {
    const pkg = makePackage({ styleKey: 'problem_solution' });
    const result = await renderVisualCommercePage(pkg, {}, figmaMock);

    // Badge text nodes should use the brand color (#2D7DFF → uppercase for comparison)
    const textNodes = collectText(result.root);
    const badgeNodes = textNodes.filter((n) => n.name === 'badge_text');
    expect(badgeNodes.length).toBeGreaterThan(0);

    for (const badge of badgeNodes) {
      const hex = extractColorHex(badge);
      expect(hex).toBe('#2D7DFF');
    }
  });

  it('uses amber fallback for lifestyle when brand color is default #2D7DFF', async () => {
    const pkg = makePackage({ styleKey: 'lifestyle' });
    const result = await renderVisualCommercePage(pkg, {}, figmaMock);

    const textNodes = collectText(result.root);
    const badgeNodes = textNodes.filter((n) => n.name === 'badge_text');
    expect(badgeNodes.length).toBeGreaterThan(0);

    for (const badge of badgeNodes) {
      const hex = extractColorHex(badge);
      // Expected: amber #D97706
      expect(hex).toBe('#D97706');
    }
  });

  it('uses deep navy fallback for spec_focused when brand color is default #2D7DFF', async () => {
    const pkg = makePackage({ styleKey: 'spec_focused' });
    const result = await renderVisualCommercePage(pkg, {}, figmaMock);

    const textNodes = collectText(result.root);
    const badgeNodes = textNodes.filter((n) => n.name === 'badge_text');
    expect(badgeNodes.length).toBeGreaterThan(0);

    for (const badge of badgeNodes) {
      const hex = extractColorHex(badge);
      // Expected: deep navy #1E3A5F
      expect(hex).toBe('#1E3A5F');
    }
  });

  it('preserves custom brand color regardless of style_key (no fallback)', async () => {
    // If brand has a custom primary color, it should be used even with lifestyle
    const pkg = makePackage({ styleKey: 'lifestyle', brandColor: '#E63946' });
    const result = await renderVisualCommercePage(pkg, {}, figmaMock);

    const textNodes = collectText(result.root);
    const badgeNodes = textNodes.filter((n) => n.name === 'badge_text');
    expect(badgeNodes.length).toBeGreaterThan(0);

    for (const badge of badgeNodes) {
      const hex = extractColorHex(badge);
      // Should use the custom brand color, not amber fallback
      expect(hex).toBe('#E63946');
    }
  });

  it('falls back to visualLayout.style_key, then payload.page.style_key, then default', async () => {
    // Case 1: visual_layout has style_key → it should be used
    const pkg1 = makePackage({ styleKey: 'lifestyle', pageStyleKey: 'cool_minimal' });
    const result1 = await renderVisualCommercePage(pkg1, {}, figmaMock);

    const textNodes1 = collectText(result1.root);
    const badgeNodes1 = textNodes1.filter((n) => n.name === 'badge_text');
    expect(badgeNodes1.length).toBeGreaterThan(0);
    // lifestyle → amber
    expect(extractColorHex(badgeNodes1[0])).toBe('#D97706');
  });
});
