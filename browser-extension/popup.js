const $ = (id) => document.getElementById(id);
let preview = null;
let capturedScreenshot = null;

function api(path) { return `${$('apiBase').value.replace(/\/$/, '')}${path}`; }
function setStatus(message, ok = false) { const el = $('status'); el.textContent = message; el.className = ok ? 'ok' : ''; }
async function stored() { return chrome.storage.local.get(['sellformExtensionToken', 'sellformApiBase']); }
async function request(path, options = {}) {
  const state = await stored();
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  if (state.sellformExtensionToken) headers['X-Sellform-Extension-Token'] = state.sellformExtensionToken;
  const response = await fetch(api(path), { ...options, headers });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail || body));
  return body;
}

function adapterFor(url) {
  const host = new URL(url).hostname.toLowerCase();
  if (host === 'detail.1688.com' || host.endsWith('.1688.com')) return '1688-visible-product-v1';
  if (host.endsWith('taobao.com') || host.endsWith('tmall.com')) return 'taobao-visible-product-v1';
  if (host.endsWith('xiaohongshu.com') || host.endsWith('xhslink.com')) return 'xiaohongshu-visible-product-v1';
  if (host.endsWith('coupang.com')) return 'coupang-visible-product-v1';
  if (host === 'smartstore.naver.com' || host.endsWith('.smartstore.naver.com')) return 'smartstore-visible-product-v1';
  return 'generic-visible-selection-v1';
}

async function activeTabData() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id || !tab.url?.startsWith('http')) throw new Error('http(s) 상품 페이지 탭에서만 사용할 수 있습니다.');
  const [result] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: () => {
      const visible = (node) => { const s = getComputedStyle(node); const r = node.getBoundingClientRect(); return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 1 && r.height > 1; };
      const adapterSelectors = {
        '1688-visible-product-v1': ['.detail-gallery img', '.offer-img img', '.detail-desc img'],
        'taobao-visible-product-v1': ['#J_ImgBooth', '.tb-main-pic img', '.descV8-singleImage img'],
        'xiaohongshu-visible-product-v1': ['.note-slider img', '.swiper-slide img', '[class*="note"] img'],
        'coupang-visible-product-v1': ['.prod-image img', '#repImageContainer img', '.product-detail-content img'],
        'smartstore-visible-product-v1': ['[class*="product"] img', '[class*="detail"] img'],
      };
      const host = location.hostname.toLowerCase();
      const adapter = host.includes('1688.com') ? '1688-visible-product-v1'
        : (host.endsWith('taobao.com') || host.endsWith('tmall.com')) ? 'taobao-visible-product-v1'
        : (host.endsWith('xiaohongshu.com') || host.endsWith('xhslink.com')) ? 'xiaohongshu-visible-product-v1'
        : host.endsWith('coupang.com') ? 'coupang-visible-product-v1'
        : host.includes('smartstore.naver.com') ? 'smartstore-visible-product-v1'
        : 'generic-visible-selection-v1';
      const selectedRange = window.getSelection();
      const pickedElement = window.__sellformCaptureDomSelection;
      let selectedHtml = '';
      if (selectedRange?.rangeCount) { const wrap = document.createElement('div'); wrap.append(selectedRange.getRangeAt(0).cloneContents()); selectedHtml = wrap.innerHTML.slice(0, 30000); }
      if (!selectedHtml && pickedElement?.html) selectedHtml = pickedElement.html;
      const allNodes = [...document.images];
      const selectors = adapterSelectors[adapter] || [];
      const preferred = selectors.flatMap((selector) => [...document.querySelectorAll(selector)]);
      const imageNodes = [...preferred, ...allNodes].filter((image, index, items) => items.indexOf(image) === index);
      const seen = new Set();
      const images = imageNodes.filter((img) => visible(img) && (img.currentSrc || img.src) && img.naturalWidth > 120)
        .map((img, order) => ({ url: img.currentSrc || img.src, order, alt: (img.alt || '').slice(0, 300) }))
        .filter((image) => { if (seen.has(image.url)) return false; seen.add(image.url); return true; }).slice(0, 20);
      const documentItems = [...document.querySelectorAll('h1,h2,h3,h4,[itemprop="name"],table tr,dl dt,dl dd')]
        .filter(visible).map((node, order) => ({ kind: /^(H1|H2|H3|H4)$/.test(node.tagName) ? 'heading' : 'spec', value: (node.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 1000), order }))
        .filter((item) => item.value).slice(0, 30);
      return { url: location.href, title: document.title, language: document.documentElement.lang || navigator.language, adapter, selectedText: selectedRange?.toString().trim() || pickedElement?.text || '', selectedHtml, images, documentItems };
    },
  });
  return { ...result.result, tabId: tab.id, windowId: tab.windowId };
}

function renderProjects(projects) {
  const select = $('projectSelect'); select.replaceChildren();
  const blank = document.createElement('option'); blank.value = ''; blank.textContent = '대상 프로젝트를 선택하세요'; select.append(blank);
  projects.forEach((project) => { const option = document.createElement('option'); option.value = project.id; option.textContent = project.name; select.append(option); });
}
async function loadProjects() { renderProjects((await request('/browser-extension/projects')).projects || []); }

function renderImages(images) {
  const container = $('imageChoices'); container.replaceChildren();
  images.forEach((image, index) => {
    const label = document.createElement('label'); label.className = 'image-choice';
    const img = document.createElement('img'); img.src = image.url; img.alt = image.alt || ''; img.referrerPolicy = 'no-referrer';
    const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.dataset.url = image.url; checkbox.checked = index < 4;
    const text = document.createElement('span'); text.textContent = image.alt || '이 이미지 포함';
    label.append(img, checkbox, text); container.append(label);
  });
}
function renderDocuments(items) {
  const container = $('documentChoices'); container.replaceChildren();
  items.forEach((item, index) => {
    const label = document.createElement('label'); label.className = 'document-choice';
    const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.dataset.index = String(index); checkbox.checked = item.kind === 'heading' && index < 3;
    const text = document.createElement('span'); text.textContent = `${item.kind === 'heading' ? '제목' : '사양'}: ${item.value}`;
    label.append(checkbox, text); container.append(label);
  });
}
async function dataUrlForImage(url, index) {
  const origin = `${new URL(url).origin}/*`;
  const allowed = await chrome.permissions.contains({ origins: [origin] });
  if (!allowed && !(await chrome.permissions.request({ origins: [origin] }))) throw new Error(`이미지 주소 접근 권한을 허용하지 않았습니다: ${new URL(url).hostname}`);
  const response = await fetch(url, { credentials: 'omit' });
  if (!response.ok) throw new Error(`이미지를 가져오지 못했습니다 (${response.status}). 화면 스크린샷을 포함해 보세요.`);
  const blob = await response.blob();
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(blob.type)) throw new Error('JPEG, PNG, WebP 형식의 이미지만 전송할 수 있습니다.');
  if (blob.size > 8 * 1024 * 1024) throw new Error('선택한 이미지가 8MB를 초과합니다.');
  const dataUrl = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = reject; reader.readAsDataURL(blob); });
  return { data_url: dataUrl, filename: `selected-image-${index + 1}.${blob.type.split('/')[1].replace('jpeg', 'jpg')}`, source_url: url, role: 'selected_image' };
}
async function captureScreenshot(tab) {
  const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: 'png' });
  return { data_url: dataUrl, filename: 'current-tab-screenshot.png', source_url: tab.url, role: 'screenshot' };
}
function selectedDocumentOrder() {
  const selected = [...document.querySelectorAll('#documentChoices input:checked')].map((input) => preview.documentItems[Number(input.dataset.index)]);
  const typed = $('selectedText').value.trim();
  if (typed) selected.push({ kind: 'text', value: typed.slice(0, 3000), order: 900 });
  return selected.map((item, order) => ({ kind: item.kind, value: item.value, order }));
}
function payloadBase() {
  const typed = $('selectedText').value.trim();
  return { url: preview.url, page_title: preview.title, language: preview.language, site_adapter: preview.adapter, selected_text: typed || null, selected_html: preview.selectedHtml || null, selected_image_urls: [], document_order: selectedDocumentOrder(), captured_at: new Date().toISOString() };
}

async function initialise() {
  const state = await stored(); if (state.sellformApiBase) $('apiBase').value = state.sellformApiBase;
  if (state.sellformExtensionToken) { $('connectPanel').hidden = true; $('capturePanel').hidden = false; $('connectionState').textContent = '연결됨 — 현재 탭에서 직접 검토한 공개 상품 자료만 전송할 수 있습니다.'; try { await loadProjects(); } catch (error) { setStatus(`프로젝트를 불러오지 못했습니다: ${error.message}`); } }
}
$('connect').addEventListener('click', async () => {
  try { const data = await request('/browser-extension/connection-codes/exchange', { method: 'POST', body: JSON.stringify({ connection_code: $('connectionCode').value, extension_version: '0.2.0' }) }); await chrome.storage.local.set({ sellformExtensionToken: data.extension_token, sellformApiBase: $('apiBase').value }); await initialise(); setStatus('연결되었습니다.', true); } catch (error) { setStatus(`연결 실패: ${error.message}`); }
});
$('capture').addEventListener('click', async () => {
  try { preview = await activeTabData(); capturedScreenshot = null; $('selectedText').value = preview.selectedText; renderImages(preview.images); renderDocuments(preview.documentItems); const result = await request('/browser-extension/captures/preview', { method: 'POST', body: JSON.stringify(payloadBase()) }); $('send').disabled = false; setStatus(`미리보기 완료: ${preview.adapter} 어댑터 · 이미지 ${preview.images.length}개, 문서 항목 ${result.document_order.length}개를 직접 선택하세요.`, true); } catch (error) { setStatus(`미리보기 실패: ${error.message}`); }
});
$('chooseDom').addEventListener('click', async () => {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id) throw new Error('현재 탭을 찾지 못했습니다.');
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: () => {
      const previous = document.getElementById('__sellform_capture_picker_style'); previous?.remove();
      const style = document.createElement('style'); style.id = '__sellform_capture_picker_style'; style.textContent = '*:hover { outline: 2px solid #00a878 !important; cursor: crosshair !important; }'; document.documentElement.append(style);
      const finish = (event) => { event.preventDefault(); event.stopPropagation(); const node = event.target; window.__sellformCaptureDomSelection = { text: (node.textContent || '').trim().slice(0, 20000), html: (node.outerHTML || '').slice(0, 30000) }; style.remove(); document.removeEventListener('click', finish, true); document.removeEventListener('keydown', cancel, true); };
      const cancel = (event) => { if (event.key === 'Escape') { style.remove(); document.removeEventListener('click', finish, true); document.removeEventListener('keydown', cancel, true); } };
      document.addEventListener('click', finish, true); document.addEventListener('keydown', cancel, true);
    }});
    setStatus('상품 페이지에서 가져올 문구·사양 영역을 한 번 클릭한 뒤, 확장 프로그램을 다시 열어 미리보기를 누르세요.', true);
  } catch (error) { setStatus(`DOM 영역 선택 시작 실패: ${error.message}`); }
});
$('takeScreenshot').addEventListener('click', async () => { try { if (!preview) throw new Error('먼저 현재 탭 미리보기를 실행하세요.'); capturedScreenshot = await captureScreenshot(preview); setStatus('현재 보이는 화면 스크린샷을 전송에 포함합니다.', true); } catch (error) { setStatus(`스크린샷 실패: ${error.message}`); } });
$('send').addEventListener('click', async () => {
  try {
    if (!preview || !$('projectSelect').value) throw new Error('대상 프로젝트를 먼저 선택하세요.');
    setStatus('선택한 이미지 파일을 안전하게 확인 중입니다…');
    const urls = [...document.querySelectorAll('#imageChoices input:checked')].map((input) => input.dataset.url);
    const selected_image_blobs = await Promise.all(urls.map(dataUrlForImage));
    const body = { project_id: $('projectSelect').value, ...payloadBase(), selected_image_urls: urls, selected_image_blobs, screenshot: capturedScreenshot };
    const data = await request('/browser-extension/captures', { method: 'POST', body: JSON.stringify(body) }); setStatus(`참고용 실제 파일 ${data.stored_asset_ids.length}개를 프로젝트에 저장했습니다.`, true); $('send').disabled = true;
  } catch (error) { setStatus(`전송 실패: ${error.message}`); }
});
initialise();
