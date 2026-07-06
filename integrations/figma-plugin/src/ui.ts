import { validatePackage } from './payload-validator';
import { DetailPagePackage } from './contracts';

export class FigmaPluginUiClient {
  private backendUrl = 'http://localhost:8000/api/v1';

  async importCode(code: string): Promise<any> {
    const normalized = code.trim().replace(/\s+/g, '').toUpperCase();
    let formatted = normalized;
    if (normalized.startsWith("SF") && normalized.length === 10) {
      formatted = `SF-${normalized.slice(2, 6)}-${normalized.slice(6)}`;
    }

    const res = await fetch(`${this.backendUrl}/figma-plugin/import`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ code: formatted })
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({ detail: 'Import failed' }));
      throw new Error(errData.detail || `Error ${res.status}`);
    }

    const data = await res.json();
    validatePackage({
      schema_version: data.schema_version || data.payload?.schema_version,
      payload: data.payload,
      embedded_assets: data.embedded_assets || []
    });
    return data;
  }

  async importJson(fileContent: string): Promise<DetailPagePackage> {
    const parsed = JSON.parse(fileContent);
    const validated = validatePackage(parsed);
    return validated;
  }

  async fetchAsset(assetRef: string, token: string): Promise<Uint8Array> {
    const res = await fetch(`${this.backendUrl}/figma-plugin/assets/${assetRef}`, {
      headers: {
        'Authorization': `Bearer ${token}`
      }
    });

    if (!res.ok) {
      throw new Error(`Failed to fetch asset ${assetRef}`);
    }

    const arrayBuffer = await res.arrayBuffer();
    return new Uint8Array(arrayBuffer);
  }
}

// Dom Binding bootstrap
if (typeof document !== 'undefined') {
  document.addEventListener('DOMContentLoaded', () => {
    const client = new FigmaPluginUiClient();

    const tabCode = document.getElementById('tab-code')!;
    const tabJson = document.getElementById('tab-json')!;
    const contentCode = document.getElementById('content-code')!;
    const contentJson = document.getElementById('content-json')!;
    const btnImportCode = document.getElementById('btn-import-code') as HTMLButtonElement;
    const ticketCodeInput = document.getElementById('ticket-code') as HTMLInputElement;
    const dropZone = document.getElementById('drop-zone')!;
    const fileInput = document.getElementById('file-input') as HTMLInputElement;
    const statusBox = document.getElementById('status-box')!;
    const statusMessage = document.getElementById('status-message')!;
    const warningBox = document.getElementById('warning-box')!;

    const showStatus = (msg: string, type: 'loading' | 'success' | 'error', warnings: any[] = []) => {
      statusBox.className = `status-card ${type}`;
      statusBox.style.display = 'block';
      statusMessage.textContent = msg;
      
      if (warnings.length > 0) {
        warningBox.innerHTML = '';
        warnings.forEach(w => {
          const li = document.createElement('li');
          li.textContent = `[${w.section_type}] ${w.message}`;
          warningBox.appendChild(li);
        });
        warningBox.style.display = 'block';
      } else {
        warningBox.style.display = 'none';
      }
    };

    // Tabs toggle
    tabCode.addEventListener('click', () => {
      tabCode.classList.add('active');
      tabJson.classList.remove('active');
      contentCode.classList.add('active');
      contentJson.classList.remove('active');
    });

    tabJson.addEventListener('click', () => {
      tabJson.classList.add('active');
      tabCode.classList.remove('active');
      contentJson.classList.add('active');
      contentCode.classList.remove('active');
    });

    // Import code action
    btnImportCode.addEventListener('click', async () => {
      const code = ticketCodeInput.value.trim();
      if (!code) {
        showStatus('코드를 입력하세요.', 'error');
        return;
      }

      showStatus('티켓 교환 중...', 'loading');
      btnImportCode.disabled = true;

      try {
        const ticketData = await client.importCode(code);
        showStatus('이미지 자산 다운로드 중...', 'loading');
        
        const imageBytesByRef: Record<string, number[]> = {};
        const assetMap = ticketData.asset_map || {};
        const token = ticketData.asset_session_token;

        for (const assetRef of Object.keys(assetMap)) {
          try {
            const bytes = await client.fetchAsset(assetRef, token);
            imageBytesByRef[assetRef] = Array.from(bytes);
          } catch (e) {
            console.warn(`Failed to fetch asset ${assetRef}`, e);
          }
        }

        showStatus('Figma 캔버스에 그리는 중...', 'loading');
        
        parent.postMessage({
          pluginMessage: {
            type: 'render-package',
            package: {
              schema_version: ticketData.payload.schema_version || '1.0',
              payload: ticketData.payload,
              embedded_assets: []
            },
            imageBytesByRef
          }
        }, '*');

      } catch (err: any) {
        showStatus(err.message || '가져오기에 실패했습니다.', 'error');
        btnImportCode.disabled = false;
      }
    });

    // JSON drop/select zone
    dropZone.addEventListener('click', () => {
      fileInput.click();
    });

    fileInput.addEventListener('change', (e) => {
      const file = fileInput.files?.[0];
      if (file) {
        const reader = new FileReader();
        reader.onload = async (evt) => {
          const content = evt.target?.result as string;
          try {
            showStatus('JSON 패키지 유효성 검사 중...', 'loading');
            const pkg = await client.importJson(content);
            
            showStatus('임베디드 이미지 변환 중...', 'loading');
            const imageBytesByRef: Record<string, number[]> = {};
            const embedded = pkg.embedded_assets || [];
            
            for (const asset of embedded) {
              const bin = atob(asset.base64);
              const bytes = new Uint8Array(bin.length);
              for (let i = 0; i < bin.length; i++) {
                bytes[i] = bin.charCodeAt(i);
              }
              imageBytesByRef[asset.asset_ref] = Array.from(bytes);
            }

            showStatus('Figma 캔버스에 그리는 중...', 'loading');
            parent.postMessage({
              pluginMessage: {
                type: 'render-package',
                package: pkg,
                imageBytesByRef
              }
            }, '*');

          } catch (err: any) {
            showStatus(err.message || '유효하지 않은 JSON 패키지 파일입니다.', 'error');
          }
        };
        reader.readAsText(file);
      }
    });

    // Handle messages back from main plugin thread
    window.onmessage = (event) => {
      const msg = event.data.pluginMessage;
      if (!msg) return;

      if (msg.type === 'render-complete') {
        showStatus('성공적으로 상세페이지 프레임이 생성되었습니다!', 'success', msg.warnings);
        btnImportCode.disabled = false;
      } else if (msg.type === 'render-error') {
        showStatus(`렌더링 오류: ${msg.error}`, 'error');
        btnImportCode.disabled = false;
      }
    };
  });
}
