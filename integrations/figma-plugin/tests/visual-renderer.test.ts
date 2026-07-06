import { DetailPagePackage } from '../src/contracts';
import { renderVisualCommercePage } from '../src/visual-renderer';

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

  resize(w: number, h: number) {
    this.width = w;
    this.height = h;
  }

  appendChild(node: MockNode) {
    this.children.push(node);
  }
}

function makePackage(): DetailPagePackage {
  const sectionTypes = [
    'problem_statement',
    'main_claim',
    'secondary_benefit',
    'main_claim_support',
    'benefit_list',
    'summary_claim',
    'product_information',
  ];

  return {
    schema_version: '1.0',
    payload: {
      schema_version: '1.0',
      project: { id: 'p1', name: '루메나 휴대용 무선 냉각선풍기', category: 'Living' },
      brand: { name: 'Sellform', primary_color: '#2D7DFF', font_family: 'Inter' },
      page: { canvas_width: 860, channel: 'smartstore', style_key: 'cool_minimal' },
      cuts: sectionTypes.map((sectionType, index) => ({
        section_id: `sec-${index}`,
        section_type: sectionType,
        layout_type: 'legacy',
        headline: `레거시 헤드라인 ${index + 1}`,
        subcopy: `본문 ${index + 1}`,
        supporting_text: index === 0 ? '보조 문구' : null,
        image_url: index === 1 ? 'asset-main' : null,
        background_style: 'clean',
      })),
      visual_layout: {
        layout_version: 'commerce_visual_v1',
        width: 860,
        category: 'Living',
        style_key: 'cool_minimal',
        background_key: 'cooling-blue',
        cuts: sectionTypes.map((sectionType, index) => ({
          section_id: `sec-${index}`,
          section_type: sectionType,
          layout_type: index === 0 ? 'problem_visual' : index === 1 ? 'solution_visual' : 'benefit_cards',
          headline: `비주얼 헤드라인 ${index + 1}`,
          subcopy: `비주얼 본문 ${index + 1}`,
          supporting_text: index === 0 ? '보조 문구' : null,
          image_role: index === 1 ? 'product_main' : 'lifestyle_scene',
          image_asset_ref: index === 1 ? 'asset-main' : null,
          image_url: index === 1 ? 'asset-main' : null,
          visual_slot: {
            kind: index === 1 ? 'image' : 'placeholder',
            asset_ref: index === 1 ? 'asset-main' : null,
            image_url: index === 1 ? 'asset-main' : null,
            fallback_label: '선택된 배경 비주얼',
          },
          badges: ['강력 냉각', '저소음'],
          background_tone: 'cool_blue',
          emphasis_level: index === 1 ? 2 : 1,
        })),
      },
    },
    embedded_assets: [],
  };
}

describe('visual commerce Figma renderer', () => {
  let figmaMock: any;

  function collectText(node: MockNode): MockNode[] {
    const current = node.characters ? [node] : [];
    return [...current, ...node.children.flatMap((child) => collectText(child))];
  }

  beforeEach(() => {
    figmaMock = {
      createFrame: () => new MockNode(),
      createText: () => new MockNode(),
      createRectangle: () => new MockNode(),
      createImage: (bytes: Uint8Array) => ({ hash: `hash-${bytes.length}` }),
      loadFontAsync: jest.fn().mockResolvedValue(true),
    };
  });

  it('renders a 860px visual commerce frame with seven named sections', async () => {
    const result = await renderVisualCommercePage(makePackage(), { 'asset-main': new Uint8Array([1, 2, 3]) }, figmaMock);

    expect(result.root.width).toBe(860);
    expect(result.root.name).toContain('루메나 휴대용 무선 냉각선풍기');
    expect(result.sections).toHaveLength(7);
    expect(result.sections[0].name).toBe('01_problem_statement');
    expect(result.sections[0].height).toBeGreaterThanOrEqual(480);
    expect(result.sections[0].children.some((node: MockNode) => node.name === 'visual_placeholder')).toBe(true);
    expect(result.sections[1].children.some((node: MockNode) => node.name === 'visual_image')).toBe(true);
  });

  it('creates editable headline, body and badge text nodes inside visual sections', async () => {
    const result = await renderVisualCommercePage(makePackage(), {}, figmaMock);
    const firstSectionText = collectText(result.sections[0]);

    expect(firstSectionText.some((node: MockNode) => node.characters === '비주얼 헤드라인 1')).toBe(true);
    expect(firstSectionText.some((node: MockNode) => node.characters === '비주얼 본문 1')).toBe(true);
    expect(firstSectionText.some((node: MockNode) => node.characters === '강력 냉각')).toBe(true);
    expect(result.warnings.some((warning: any) => warning.code === 'VISUAL_PLACEHOLDER_USED')).toBe(true);
  });
});
