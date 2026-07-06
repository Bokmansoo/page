import express from 'express';
import { config } from './config';
import { FigmaMcpClient } from './figma-mcp-client';
import { FigmaRenderer } from './figma-renderer';

const app = express();
app.use(express.json());

const mcpClient = new FigmaMcpClient();
const renderer = new FigmaRenderer();

// Middleware: Validate Bridge Token
const authMiddleware = (req: express.Request, res: express.Response, next: express.NextFunction) => {
  if (!config.BRIDGE_TOKEN) {
    return res.status(503).json({
      error_code: 'BRIDGE_NOT_CONFIGURED',
      error_message: 'SELLFORM_FIGMA_BRIDGE_TOKEN is required.'
    });
  }
  const token = req.headers['x-sellform-bridge-token'];
  if (token !== config.BRIDGE_TOKEN) {
    return res.status(401).json({
      error_code: 'BRIDGE_UNAUTHORIZED',
      error_message: 'Invalid X-Sellform-Bridge-Token header.'
    });
  }
  next();
};

// Endpoint: Trigger Figma MCP canvas export
app.post('/v1/exports', authMiddleware, async (req, res) => {
  const { job_id, target_file_url, payload } = req.body;

  if (!target_file_url || !payload) {
    return res.status(400).json({
      error_code: 'INVALID_REQUEST',
      error_message: 'Missing target_file_url or payload in request body.'
    });
  }

  // 1. Resolve design file key from Figma URL
  let fileKey = '';
  try {
    fileKey = renderer.parseFileKey(target_file_url);
  } catch (err: any) {
    return res.status(400).json({
      error_code: err.error_code || 'INVALID_FIGMA_URL',
      error_message: err.message
    });
  }

  // 2. Validate and compile payload before opening a remote session
  try {
    renderer.compilePayloadToFigmaNodes(payload);
  } catch (err: any) {
    return res.status(400).json({
      error_code: err.error_code || 'RENDER_FAILED',
      error_message: err.message
    });
  }

  // 3. Connect to Figma Remote MCP with Local OAuth verification
  const conn = await mcpClient.connect();
  if (!conn.success) {
    const status = conn.error_code === 'AUTH_REQUIRED' ? 401 : 500;
    const body: any = {
      error_code: conn.error_code,
      error_message: conn.error_message
    };
    if (conn.error_code === 'AUTH_REQUIRED') {
      body.auth_url = conn.auth_url || mcpClient.getAuthorizationUrl();
    }
    return res.status(status).json(body);
  }

  // 4. Create native nodes through use_figma and upload_assets.
  try {
    const result = await mcpClient.exportLayout(fileKey, target_file_url, payload);
    const nodeId = result.rootNodeId.replace(':', '-');
    const cleanUrl = target_file_url.split('?')[0];

    return res.status(200).json({
      result_file_url: cleanUrl,
      result_node_url: `${cleanUrl}?node-id=${nodeId}`
    });
  } catch (err: any) {
    console.error('Figma MCP tool call error:', err);
    const errorCode = err?.error_code || 'RENDER_FAILED';
    const clientErrorCodes = new Set([
      'ASSET_URL_NOT_PUBLIC',
      'IMAGE_UPLOAD_UNSUPPORTED',
      'INVALID_MCP_RESPONSE'
    ]);
    return res.status(clientErrorCodes.has(errorCode) ? 422 : 500).json({
      error_code: errorCode,
      error_message: `Figma MCP execution error: ${err.message || err}`
    });
  } finally {
    await mcpClient.disconnect();
  }
});

// Endpoint: Figma OAuth redirection callback receiver
app.get('/oauth/callback', async (req, res) => {
  const { code, state, error } = req.query;
  if (error) {
    return res.status(400).send(`<h1>Figma authorization failed: ${String(error)}</h1>`);
  }
  if (typeof code !== 'string' || typeof state !== 'string') {
    return res.status(400).send('<h1>Authorization code or state is missing.</h1>');
  }

  try {
    await mcpClient.finishAuthorization(code, state);

    return res.status(200).send(`
      <div style="font-family: sans-serif; text-align: center; margin-top: 100px;">
        <h1 style="color: #4F46E5;">Figma MCP 인증 완료!</h1>
        <p>Sellform으로 돌아가 내보내기를 다시 시도해 주세요.</p>
        <button onclick="window.close()" style="margin-top: 20px; padding: 10px 20px; background-color: #4F46E5; color: white; border: none; border-radius: 8px; cursor: pointer;">
          이 창 닫기
        </button>
      </div>
    `);
  } catch (err: any) {
    return res.status(500).send(`<h1>OAuth Callback failed: ${err.message || err}</h1>`);
  }
});

// Health check endpoint
app.get('/health', (req, res) => {
  res.status(200).json({ status: 'healthy', service: 'Figma Bridge Express' });
});

// Run server only when launched directly (not in testing environment)
if (require.main === module) {
  app.listen(config.PORT, config.HOST, () => {
    console.log(`Figma Bridge Express server running on http://${config.HOST}:${config.PORT}`);
  });
}

export default app;
export { mcpClient };
