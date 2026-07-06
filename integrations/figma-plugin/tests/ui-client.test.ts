import { FigmaPluginUiClient } from '../src/ui';

describe('UI Client Tests', () => {
  let client: FigmaPluginUiClient;
  let fetchMock: jest.Mock;

  beforeEach(() => {
    client = new FigmaPluginUiClient();
    fetchMock = jest.fn();
    global.fetch = fetchMock;
  });

  const sevenCuts = Array.from({ length: 7 }, (_, index) => ({
    section_id: `s${index + 1}`,
    section_type: `section_${index + 1}`,
    layout_type: 'features',
    headline: `Title ${index + 1}`,
    subcopy: 'Copy',
    supporting_text: null,
    image_url: null,
    background_style: 'clean',
  }));

  it('normalizes and redeems a Sellform code', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: jest.fn().mockResolvedValue({
        ticket_id: 't-123',
        payload: {
          schema_version: '1.0',
          project: { id: 'p1', name: 'Proj', category: 'Living' },
          brand: { name: 'Brand', primary_color: '#fff', font_family: 'Inter' },
          page: { canvas_width: 860, channel: 'naver', style_key: 'modern' },
          cuts: sevenCuts
        },
        asset_map: {},
        asset_session_token: 'token-abc'
      })
    });

    const result = await client.importCode('sf 8k4p 2m7q');
    
    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/api/v1/figma-plugin/import',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ code: 'SF-8K4P-2M7Q' })
      })
    );
    expect(result.payload.schema_version).toBe('1.0');
  });

  it('parses the JSON fallback through the same validator', async () => {
    const pkg = {
      schema_version: '1.0',
      payload: {
        schema_version: '1.0',
        project: { id: 'p1', name: 'Proj', category: 'Living' },
        brand: { name: 'Brand', primary_color: '#fff', font_family: 'Inter' },
        page: { canvas_width: 860, channel: 'naver', style_key: 'modern' },
        cuts: sevenCuts
      },
      embedded_assets: []
    };
    const file = JSON.stringify(pkg);
    const result = await client.importJson(file);
    expect(result).toEqual(pkg);
  });
});
