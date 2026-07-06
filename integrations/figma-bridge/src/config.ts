import dotenv from 'dotenv';
import path from 'path';

// Load workspace .env
dotenv.config({ path: path.join(__dirname, '../../../.env') });

export const config = {
  HOST: process.env.SELLFORM_FIGMA_BRIDGE_HOST || '127.0.0.1',
  PORT: process.env.SELLFORM_FIGMA_BRIDGE_PORT ? parseInt(process.env.SELLFORM_FIGMA_BRIDGE_PORT) : 3417,
  BRIDGE_TOKEN: process.env.SELLFORM_FIGMA_BRIDGE_TOKEN || '',
  FIGMA_MCP_URL: process.env.SELLFORM_FIGMA_MCP_URL || 'https://mcp.figma.com/mcp',
  OAUTH_REDIRECT_URI: process.env.SELLFORM_FIGMA_OAUTH_REDIRECT_URI || 'http://127.0.0.1:3417/oauth/callback',
  OAUTH_STORE_PATH: process.env.SELLFORM_FIGMA_OAUTH_STORE_PATH || '.sellform/figma-oauth.json',
  TIMEOUT_MS: process.env.SELLFORM_FIGMA_BRIDGE_TIMEOUT_SECONDS 
    ? parseInt(process.env.SELLFORM_FIGMA_BRIDGE_TIMEOUT_SECONDS) * 1000 
    : 120000,
};
