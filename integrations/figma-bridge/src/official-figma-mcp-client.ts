import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { UnauthorizedError } from '@modelcontextprotocol/sdk/client/auth.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';
import { config } from './config';
import { PersistentOAuthProvider } from './persistent-oauth-provider';
import {
  FigmaRenderer,
  FigmaExecutionResult,
  FigmaRenderPayload,
  parseFigmaExecutionResult
} from './figma-renderer';

export interface FigmaMcpConnectionResult {
  success: boolean;
  error_code?: string;
  error_message?: string;
  auth_url?: string;
}

export class OfficialFigmaMcpClient {
  private readonly oauthProvider: PersistentOAuthProvider;
  private client: Client | null = null;
  private transport: StreamableHTTPClientTransport | null = null;
  private availableTools = new Set<string>();

  constructor() {
    this.oauthProvider = new PersistentOAuthProvider();
  }

  public transportKind(): string {
    return 'streamable-http';
  }

  public requiredTools(): string[] {
    return ['use_figma'];
  }

  public optionalTools(): string[] {
    return ['upload_assets'];
  }

  public hasTool(name: string): boolean {
    return this.availableTools.has(name);
  }

  public getAuthorizationUrl(): string {
    return this.oauthProvider.authorizationUrl() || '';
  }

  public async connect(): Promise<FigmaMcpConnectionResult> {
    this.client = new Client(
      { name: 'SellformFigmaBridge', version: '1.0.0' },
      { capabilities: {} }
    );
    this.transport = new StreamableHTTPClientTransport(
      new URL(config.FIGMA_MCP_URL),
      { authProvider: this.oauthProvider }
    );
    try {
      await this.client.connect(this.transport);
      const tools = await this.client.listTools();
      this.availableTools = new Set(tools.tools.map(tool => tool.name));
      const missing = this.requiredTools().find(tool => !this.availableTools.has(tool));
      if (missing) {
        return {
          success: false,
          error_code: 'MCP_TOOL_UNSUPPORTED',
          error_message: `Figma Remote MCP does not expose ${missing}.`
        };
      }
      return { success: true };
    } catch (error: any) {
      if (error instanceof UnauthorizedError || error?.name === 'UnauthorizedError') {
        return {
          success: false,
          error_code: 'AUTH_REQUIRED',
          error_message: 'Figma OAuth authorization is required.',
          auth_url: this.getAuthorizationUrl()
        };
      }
      return {
        success: false,
        error_code: 'MCP_UNAVAILABLE',
        error_message: `Figma Remote MCP connection failed: ${error?.message || error}`
      };
    }
  }

  public async finishAuthorization(code: string, state: string): Promise<void> {
    if (!this.oauthProvider.validateState(state)) {
      throw new Error('OAuth state validation failed.');
    }
    const transport = new StreamableHTTPClientTransport(
      new URL(config.FIGMA_MCP_URL),
      { authProvider: this.oauthProvider }
    );
    await transport.finishAuth(code);
  }

  public async callFigmaTool(toolName: string, args: Record<string, unknown>): Promise<any> {
    if (!this.client || !this.availableTools.has(toolName)) {
      throw new Error(`MCP tool is unavailable: ${toolName}`);
    }
    return await this.client.callTool({ name: toolName, arguments: args });
  }

  public async exportLayout(
    fileKey: string,
    targetFileUrl: string,
    payload: FigmaRenderPayload
  ): Promise<FigmaExecutionResult> {
    const renderer = new FigmaRenderer();
    const response = await this.callFigmaTool('use_figma', {
      fileKey,
      description: `Create editable Sellform detail page for ${payload.project.name}`,
      code: renderer.buildUseFigmaCode(payload)
    });
    const result = parseFigmaExecutionResult(response);
    const cutsWithImages = payload.cuts.filter(cut => Boolean(cut.image_url));
    if (cutsWithImages.length && !this.hasTool('upload_assets')) {
      const error = new Error('Figma Remote MCP does not expose upload_assets.');
      (error as any).error_code = 'IMAGE_UPLOAD_UNSUPPORTED';
      throw error;
    }
    for (const cut of cutsWithImages) {
      const nodeId = result.imageSlots[cut.section_id];
      if (!nodeId || !cut.image_url) {
        const error = new Error(`Image slot was not returned for ${cut.section_id}.`);
        (error as any).error_code = 'INVALID_MCP_RESPONSE';
        throw error;
      }
      await this.uploadAsset(fileKey, nodeId, cut.image_url);
    }
    return result;
  }

  private async uploadAsset(fileKey: string, nodeId: string, sourceUrl: string): Promise<void> {
    const prepared = await this.callFigmaTool('upload_assets', {
      fileKey,
      nodeId,
      count: 1,
      scaleMode: 'FILL'
    });
    const endpoints = this.extractUploadEndpoints(prepared);
    if (!endpoints.uploadUrl) {
      const error = new Error('upload_assets did not return an upload URL.');
      (error as any).error_code = 'INVALID_MCP_RESPONSE';
      throw error;
    }
    const source = await fetch(sourceUrl);
    if (!source.ok) {
      const error = new Error(`Unable to download image asset: HTTP ${source.status}`);
      (error as any).error_code = 'ASSET_URL_NOT_PUBLIC';
      throw error;
    }
    const bytes = Buffer.from(await source.arrayBuffer());
    if (bytes.length > 10 * 1024 * 1024) {
      const error = new Error('Image asset exceeds the Figma 10MB limit.');
      (error as any).error_code = 'ASSET_URL_NOT_PUBLIC';
      throw error;
    }
    const uploaded = await fetch(endpoints.uploadUrl, {
      method: 'POST',
      headers: {
        'Content-Type': source.headers.get('content-type') || 'application/octet-stream'
      },
      body: bytes
    });
    if (!uploaded.ok) {
      throw new Error(`Figma asset upload failed: HTTP ${uploaded.status}`);
    }
    if (endpoints.commitUrl) {
      const committed = await fetch(endpoints.commitUrl, { method: 'POST' });
      if (!committed.ok) {
        throw new Error(`Figma asset commit failed: HTTP ${committed.status}`);
      }
    }
  }

  private extractUploadEndpoints(value: any): { uploadUrl?: string; commitUrl?: string } {
    const serialized = JSON.stringify(value);
    const uploadMatch = serialized.match(/https?:\\?\/\\?\/[^"\\\s]+upload[^"\\\s]*/i);
    const commitMatch = serialized.match(/https?:\\?\/\\?\/[^"\\\s]+commit[^"\\\s]*/i);
    return {
      uploadUrl: uploadMatch?.[0].replace(/\\\//g, '/'),
      commitUrl: commitMatch?.[0].replace(/\\\//g, '/')
    };
  }

  public async disconnect(): Promise<void> {
    if (this.transport) {
      try {
        await this.transport.terminateSession();
      } catch {
        // OAuth challenges do not always establish a server-side session.
      }
    }
    if (this.client) await this.client.close();
    this.client = null;
    this.transport = null;
    this.availableTools.clear();
  }
}
