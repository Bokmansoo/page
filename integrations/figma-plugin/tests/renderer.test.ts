import { renderDetailPage } from '../src/renderer';
import { DetailPagePackage } from '../src/contracts';

class MockNode {
  name: string = '';
  width: number = 0;
  height: number = 0;
  layoutMode: string = '';
  fills: any[] = [];
  children: MockNode[] = [];
  characters: string = '';
  fontName: any = null;
  fontSize: number = 0;
  primaryAxisSizingMode: string = '';
  counterAxisSizingMode: string = '';
  paddingLeft: number = 0;
  paddingRight: number = 0;
  paddingTop: number = 0;
  paddingBottom: number = 0;

  resize(w: number, h: number) {
    this.width = w;
    this.height = h;
  }

  appendChild(node: MockNode) {
    this.children.push(node);
  }
}

describe('Figma Renderer Tests', () => {
  let figmaMock: any;
  let validPackage: DetailPagePackage;

  beforeEach(() => {
    figmaMock = {
      createFrame: () => new MockNode(),
      createText: () => new MockNode(),
      createRectangle: () => new MockNode(),
      createImage: (bytes: Uint8Array) => ({ hash: 'mock_hash_123', bytes }),
      loadFontAsync: jest.fn().mockResolvedValue(true)
    };

    validPackage = {
      schema_version: '1.0',
      payload: {
        schema_version: '1.0',
        project: { id: 'p1', name: 'Cool Cooler', category: 'Living' },
        brand: { name: 'Brand', primary_color: '#5B7CFA', font_family: 'Inter' },
        page: { canvas_width: 860, channel: 'naver', style_key: 'modern' },
        cuts: Array.from({ length: 7 }, (_, index) => ({
          section_id: `s${index + 1}`,
          section_type:
            index === 0
              ? 'header'
              : index === 6
                ? 'product_information'
                : `section_${index + 1}`,
          layout_type: index === 6 ? 'specs' : 'features',
          headline: index === 0 ? '시원함의 혁명' : `제목 ${index + 1}`,
          subcopy: '본문 텍스트입니다',
          supporting_text: index === 6 ? null : '추가 사항',
          image_url: index === 0 ? 'asset_0' : null,
          background_style: 'clean'
        }))
      },
      embedded_assets: []
    };
  });

  it('should compile valid payload to figma nodes config matching canvas requirements', async () => {
    const imageBytes = {
      'asset_0': new Uint8Array([1, 2, 3])
    };

    const result = await renderDetailPage(validPackage, imageBytes, figmaMock);

    expect(result.root.width).toBe(860);
    expect(result.root.layoutMode).toBe('VERTICAL');
    expect(result.sections).toHaveLength(7);
    expect(result.sections[0].paddingLeft).toBe(56);
    expect(result.sections[0].paddingRight).toBe(56);
    expect(result.sections[0].paddingTop).toBe(64);
    expect(result.sections[0].paddingBottom).toBe(64);
    expect(result.warnings).toHaveLength(0); // Should be 0 since asset_0 has bytes
  });

  it('should raise warnings and use placeholders if image bytes are missing', async () => {
    const result = await renderDetailPage(validPackage, {}, figmaMock);

    expect(result.sections).toHaveLength(7);
    expect(result.warnings).toHaveLength(1);
    expect(result.warnings[0].code).toBe('IMAGE_PLACEHOLDER_USED');
    expect(result.warnings[0].section_type).toBe('header');
  });

  it('falls back to Inter when the requested font cannot be loaded', async () => {
    validPackage.payload.brand.font_family = 'Missing Font';
    figmaMock.loadFontAsync = jest.fn(({ family }) => {
      if (family === 'Missing Font') {
        return Promise.reject(new Error('font missing'));
      }
      return Promise.resolve(true);
    });

    const result = await renderDetailPage(validPackage, {}, figmaMock);
    const firstTextNode = result.sections[0].children.find(
      (node: MockNode) => Boolean(node.characters),
    );

    expect(figmaMock.loadFontAsync).toHaveBeenCalledWith({
      family: 'Inter',
      style: 'Regular',
    });
    expect(firstTextNode.fontName.family).toBe('Inter');
  });
});
