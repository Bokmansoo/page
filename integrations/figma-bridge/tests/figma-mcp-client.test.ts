import { FigmaMcpClient } from '../src/figma-mcp-client';

describe('FigmaMcpClient official MCP contract', () => {
  test('uses Streamable HTTP and discovers the official Figma tools', () => {
    const client = new FigmaMcpClient();

    expect(client.transportKind()).toBe('streamable-http');
    expect(client.requiredTools()).toEqual(['use_figma']);
    expect(client.optionalTools()).toContain('upload_assets');
  });

  test('creates native nodes and uploads image bytes into returned image slots', async () => {
    const client = new FigmaMcpClient();
    (client as any).availableTools = new Set(['use_figma', 'upload_assets']);
    const calls: Array<{ name: string; args: Record<string, unknown> }> = [];
    jest.spyOn(client, 'callFigmaTool').mockImplementation(async (name, args) => {
      calls.push({ name, args });
      if (name === 'use_figma') {
        return {
          content: [
            {
              type: 'text',
              text: JSON.stringify({
                rootNodeId: '10:20',
                imageSlots: { 'section-1': '30:40' },
              }),
            },
          ],
        };
      }
      return {
        content: [
          {
            type: 'text',
            text: 'https://uploads.figma.test/upload/asset-1',
          },
        ],
      };
    });
    const fetchMock = jest
      .spyOn(global, 'fetch')
      .mockResolvedValueOnce(
        new Response(Buffer.from('image-bytes'), {
          status: 200,
          headers: { 'content-type': 'image/png' },
        }),
      )
      .mockResolvedValueOnce(new Response(null, { status: 200 }));

    const result = await client.exportLayout(
      'FILE_KEY',
      'https://www.figma.com/design/FILE_KEY/Test',
      {
        schema_version: '1.0',
        project: {
          id: 'project-1',
          name: 'Test product',
          category: 'Living',
        },
        brand: {
          name: 'Sellform',
          primary_color: '#5B7CFA',
          font_family: 'Inter',
        },
        page: {
          canvas_width: 860,
          channel: 'coupang',
          style_key: 'modern',
        },
        cuts: [
          {
            section_id: 'section-1',
            section_type: 'header',
            layout_type: 'hero',
            headline: 'Title',
            supporting_text: 'Evidence',
            image_url: 'https://cdn.example.test/product.png',
          },
        ],
      },
    );

    expect(result.rootNodeId).toBe('10:20');
    expect(calls.map(call => call.name)).toEqual(['use_figma', 'upload_assets']);
    expect(calls[1].args).toMatchObject({
      fileKey: 'FILE_KEY',
      nodeId: '30:40',
      count: 1,
      scaleMode: 'FILL',
    });
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      'https://cdn.example.test/product.png',
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      'https://uploads.figma.test/upload/asset-1',
      expect.objectContaining({ method: 'POST' }),
    );

    fetchMock.mockRestore();
  });
});
