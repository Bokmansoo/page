import {
  FigmaRenderer,
  FigmaRenderPayload,
  parseFigmaExecutionResult
} from '../src/figma-renderer';

describe('FigmaRenderer Unit Tests', () => {
  let renderer: FigmaRenderer;
  let mockPayload: FigmaRenderPayload;

  beforeEach(() => {
    renderer = new FigmaRenderer();
    mockPayload = {
      schema_version: '1.0',
      project: {
        id: 'p-1',
        name: '루메나 선풍기',
        category: 'Living'
      },
      brand: {
        name: '루메나',
        primary_color: '#5B7CFA',
        font_family: 'Inter'
      },
      page: {
        canvas_width: 860,
        channel: 'smartstore',
        style_key: 'living_style'
      },
      cuts: [
        {
          section_id: 'cut-1',
          section_type: 'intro',
          layout_type: 'hero_visual',
          headline: '무선 선풍기의 정점',
          subcopy: '루메나 무선 선풍기 시리즈',
          supporting_text: 'Living & Premium',
          image_url: 'https://cdn.example.com/hero.jpg',
          background_style: 'clean_intro'
        }
      ]
    };
  });

  test('should successfully parse figma design url and extract file key', () => {
    const figmaUrl = 'https://www.figma.com/design/ABCD1234efgh5678/Project-Design?node-id=0-1';
    const key = renderer.parseFileKey(figmaUrl);
    expect(key).toBe('ABCD1234efgh5678');
  });

  test('should throw invalid url error for malformed urls', () => {
    const malformedUrl = 'https://www.figma.com/invalid/url/structure';
    expect(() => renderer.parseFileKey(malformedUrl)).toThrow();
  });

  test('should block localhost and local files under ASSET_URL_NOT_PUBLIC policy', () => {
    mockPayload.cuts[0].image_url = 'http://localhost:8000/hero.jpg';
    expect(() => renderer.compilePayloadToFigmaNodes(mockPayload)).toThrow(
      /Asset image URL is not public/
    );

    mockPayload.cuts[0].image_url = 'file:///C:/local/hero.jpg';
    expect(() => renderer.compilePayloadToFigmaNodes(mockPayload)).toThrow(
      /Asset image URL is not public/
    );
  });

  test('should compile valid payload to figma nodes config matching canvas requirements', () => {
    const parentNode = renderer.compilePayloadToFigmaNodes(mockPayload);
    expect(parentNode.type).toBe('FRAME');
    expect(parentNode.name).toBe('Sellform / 루메나 선풍기');
    expect(parentNode.layoutMode).toBe('VERTICAL');
    expect(parentNode.children.length).toBe(1);

    const cutNode = parentNode.children[0];
    expect(cutNode.type).toBe('FRAME');
    expect(cutNode.name).toBe('Cut 1: intro');
    expect(cutNode.children.length).toBe(4); // headline, subcopy, supporting_copy, image slot
  });

  test('should compile the canonical payload emitted by the Sellform backend', () => {
    const canonicalPayload: any = {
      schema_version: '1.0',
      project: {
        id: 'p-1',
        name: 'Test product',
        category: 'Living'
      },
      brand: {
        name: 'Sellform',
        primary_color: '#123456',
        font_family: 'Inter'
      },
      page: {
        canvas_width: 860,
        channel: 'smartstore',
        style_key: 'problem_solution'
      },
      cuts: [
        {
          section_id: 'section-1',
          section_type: 'header',
          layout_type: 'hero_visual',
          headline: 'Headline',
          subcopy: 'Subcopy',
          supporting_text: 'Evidence',
          image_url: null,
          background_style: 'clean_header'
        }
      ]
    };

    const compiled = renderer.compilePayloadToFigmaNodes(canonicalPayload);

    expect(compiled.name).toBe('Sellform / Test product');
    expect(compiled.width).toBe(860);
    expect(compiled.children[0].name).toBe('Cut 1: header');
    expect(compiled.children[0].children[2].characters).toBe('Evidence');
  });

  test('builds use_figma code that returns the real root and image slot ids', () => {
    const code = renderer.buildUseFigmaCode(mockPayload);

    expect(code).toContain('figma.createFrame()');
    expect(code).toContain('rootNodeId');
    expect(code).toContain('imageSlots');
    expect(code).not.toContain('imageRef');
  });

  test('rejects a Figma response without a real created node id', () => {
    expect(() => parseFigmaExecutionResult({ content: [] })).toThrow(
      /INVALID_MCP_RESPONSE/
    );
  });

  test('parses a real node id and image slot ids from MCP content', () => {
    const parsed = parseFigmaExecutionResult({
      content: [{
        type: 'text',
        text: '{"rootNodeId":"12:34","imageSlots":{"cut-1":"56:78"}}'
      }]
    });

    expect(parsed.rootNodeId).toBe('12:34');
    expect(parsed.imageSlots['cut-1']).toBe('56:78');
  });
});
