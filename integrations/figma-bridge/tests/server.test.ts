jest.mock('@modelcontextprotocol/sdk/client/index.js', () => {
  return { Client: jest.fn() };
}, { virtual: true });

import request from 'supertest';
import app, { mcpClient } from '../src/server';
import { config } from '../src/config';

jest.mock('../src/figma-mcp-client');

describe('Figma Bridge Express Server Integration Tests', () => {
  let mockPayload: any;

  beforeEach(() => {
    (config as any).BRIDGE_TOKEN = 'test-bridge-token';
    // Standard mock setup
    jest.spyOn(mcpClient, 'getAuthorizationUrl').mockReturnValue('https://www.figma.com/oauth');
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
          image_url: 'https://cdn.example.com/hero.jpg',
          background_style: 'clean_intro'
        }
      ]
    };
  });

  test('should return 400 Bad Request if file URL or payload is missing', async () => {
    const res = await request(app)
      .post('/v1/exports')
      .set('X-Sellform-Bridge-Token', 'test-bridge-token')
      .send({
        target_file_url: '',
        payload: null
      });

    expect(res.status).toBe(400);
    expect(res.body.error_code).toBe('INVALID_REQUEST');
  });

  test('should return 401 Unauthorized with auth URL when OAuth is required', async () => {
    // Mock McpClient connect method to return AUTH_REQUIRED
    jest.spyOn(mcpClient, 'connect').mockResolvedValue({
      success: false,
      error_code: 'AUTH_REQUIRED',
      error_message: 'Figma OAuth authorization required.'
    });

    const res = await request(app)
      .post('/v1/exports')
      .set('X-Sellform-Bridge-Token', 'test-bridge-token')
      .send({
        target_file_url: 'https://www.figma.com/design/ABC123XYZ/Project-Name',
        payload: mockPayload
      });

    expect(res.status).toBe(401);
    expect(res.body.error_code).toBe('AUTH_REQUIRED');
    expect(res.body.auth_url).toContain('https://www.figma.com/oauth');
  });

  test('should successfully export layout and return node URLs if MCP tool call succeeds', async () => {
    // Mock connect success
    jest.spyOn(mcpClient, 'connect').mockResolvedValue({
      success: true
    });

    jest.spyOn(mcpClient, 'exportLayout').mockResolvedValue({
      rootNodeId: '12:34',
      imageSlots: {}
    });

    const res = await request(app)
      .post('/v1/exports')
      .set('X-Sellform-Bridge-Token', 'test-bridge-token')
      .send({
        target_file_url: 'https://www.figma.com/design/ABC123XYZ/Project-Name',
        payload: mockPayload
      });

    expect(res.status).toBe(200);
    expect(res.body.result_file_url).toBe('https://www.figma.com/design/ABC123XYZ/Project-Name');
    expect(res.body.result_node_url).toBe('https://www.figma.com/design/ABC123XYZ/Project-Name?node-id=12-34');
  });

  test('should reject an OAuth callback without state', async () => {
    const res = await request(app)
      .get('/oauth/callback')
      .query({ code: 'auth_code_123' });

    expect(res.status).toBe(400);
    expect(res.text).toContain('state');
  });

  test('should fail closed when the bridge token is not configured', async () => {
    (config as any).BRIDGE_TOKEN = '';

    const res = await request(app)
      .post('/v1/exports')
      .send({ target_file_url: 'https://www.figma.com/design/ABC/Test', payload: mockPayload });

    expect(res.status).toBe(503);
    expect(res.body.error_code).toBe('BRIDGE_NOT_CONFIGURED');
  });

  test('should complete OAuth only after state validation', async () => {
    jest.spyOn(mcpClient, 'finishAuthorization').mockResolvedValue();

    const res = await request(app)
      .get('/oauth/callback')
      .query({ code: 'auth_code_123', state: 'valid-state' });

    expect(res.status).toBe(200);
    expect(mcpClient.finishAuthorization).toHaveBeenCalledWith(
      'auth_code_123',
      'valid-state'
    );
  });
});
