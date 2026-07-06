import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import type { OAuthClientProvider } from '@modelcontextprotocol/sdk/client/auth.js';
import type {
  OAuthClientInformationMixed,
  OAuthClientMetadata,
  OAuthTokens
} from '@modelcontextprotocol/sdk/shared/auth.js';
import { config } from './config';

interface StoredOAuthState {
  tokens?: OAuthTokens;
  clientInformation?: OAuthClientInformationMixed;
  codeVerifier?: string;
  state?: string;
  authorizationUrl?: string;
}

export class PersistentOAuthProvider implements OAuthClientProvider {
  private readonly filePath: string;
  private readonly metadata: OAuthClientMetadata;

  constructor(filePath: string = config.OAUTH_STORE_PATH) {
    this.filePath = path.isAbsolute(filePath)
      ? filePath
      : path.join(__dirname, '../../../', filePath);
    this.metadata = {
      client_name: 'Sellform Figma Bridge',
      redirect_uris: [config.OAUTH_REDIRECT_URI],
      grant_types: ['authorization_code', 'refresh_token'],
      response_types: ['code'],
      token_endpoint_auth_method: 'none'
    };
  }

  get redirectUrl(): string {
    return config.OAUTH_REDIRECT_URI;
  }

  get clientMetadata(): OAuthClientMetadata {
    return this.metadata;
  }

  public state(): string {
    const current = this.read();
    if (current.state) return current.state;
    const state = crypto.randomBytes(32).toString('hex');
    this.write({ ...current, state });
    return state;
  }

  public clientInformation(): OAuthClientInformationMixed | undefined {
    return this.read().clientInformation;
  }

  public saveClientInformation(clientInformation: OAuthClientInformationMixed): void {
    this.patch({ clientInformation });
  }

  public tokens(): OAuthTokens | undefined {
    return this.read().tokens;
  }

  public saveTokens(tokens: OAuthTokens): void {
    this.patch({ tokens, authorizationUrl: undefined });
  }

  public redirectToAuthorization(authorizationUrl: URL): void {
    this.patch({ authorizationUrl: authorizationUrl.toString() });
  }

  public saveCodeVerifier(codeVerifier: string): void {
    this.patch({ codeVerifier });
  }

  public codeVerifier(): string {
    const verifier = this.read().codeVerifier;
    if (!verifier) throw new Error('OAuth PKCE verifier is missing.');
    return verifier;
  }

  public authorizationUrl(): string | undefined {
    return this.read().authorizationUrl;
  }

  public validateState(receivedState: string): boolean {
    const expected = this.read().state;
    if (!expected || expected.length !== receivedState.length) return false;
    return crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(receivedState));
  }

  public invalidateCredentials(scope: 'all' | 'client' | 'tokens' | 'verifier' | 'discovery'): void {
    if (scope === 'all') {
      if (fs.existsSync(this.filePath)) fs.unlinkSync(this.filePath);
      return;
    }
    const current = this.read();
    if (scope === 'client') delete current.clientInformation;
    if (scope === 'tokens') delete current.tokens;
    if (scope === 'verifier') delete current.codeVerifier;
    this.write(current);
  }

  private read(): StoredOAuthState {
    try {
      if (fs.existsSync(this.filePath)) {
        return JSON.parse(fs.readFileSync(this.filePath, 'utf-8')) as StoredOAuthState;
      }
    } catch (error) {
      console.error('Failed to load Figma OAuth state:', error);
    }
    return {};
  }

  private patch(patch: Partial<StoredOAuthState>): void {
    this.write({ ...this.read(), ...patch });
  }

  private write(data: StoredOAuthState): void {
    fs.mkdirSync(path.dirname(this.filePath), { recursive: true });
    fs.writeFileSync(this.filePath, JSON.stringify(data, null, 2), {
      encoding: 'utf-8',
      mode: 0o600
    });
  }
}
