import fs from 'fs';
import path from 'path';
import { config } from './config';

export interface OAuthTokens {
  accessToken?: string;
  refreshToken?: string;
  expiresAt?: number;
}

export class OAuthStore {
  private filePath: string;

  constructor() {
    // Resolve absolute path from project root
    this.filePath = path.isAbsolute(config.OAUTH_STORE_PATH)
      ? config.OAUTH_STORE_PATH
      : path.join(__dirname, '../../../', config.OAUTH_STORE_PATH);
  }

  public loadTokens(): OAuthTokens {
    try {
      if (fs.existsSync(this.filePath)) {
        const data = fs.readFileSync(this.filePath, 'utf-8');
        return JSON.parse(data) as OAuthTokens;
      }
    } catch (err) {
      console.error('Failed to load OAuth tokens from file:', err);
    }
    return {};
  }

  public saveTokens(tokens: OAuthTokens): void {
    try {
      const dir = path.dirname(this.filePath);
      if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
      }
      fs.writeFileSync(this.filePath, JSON.stringify(tokens, null, 2), 'utf-8');
    } catch (err) {
      console.error('Failed to save OAuth tokens to file:', err);
    }
  }

  public clearTokens(): void {
    try {
      if (fs.existsSync(this.filePath)) {
        fs.unlinkSync(this.filePath);
      }
    } catch (err) {
      console.error('Failed to delete OAuth tokens file:', err);
    }
  }
}
