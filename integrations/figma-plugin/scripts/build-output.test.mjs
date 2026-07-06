import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

describe('compiled Figma plugin output', () => {
  it('does not emit optional chaining unsupported by the Figma plugin runtime', () => {
    const codePath = path.join(__dirname, '..', 'dist', 'code.js');
    const uiPath = path.join(__dirname, '..', 'dist', 'ui.js');

    const code = fs.readFileSync(codePath, 'utf-8');
    const ui = fs.readFileSync(uiPath, 'utf-8');

    expect(code).not.toContain('?.');
    expect(ui).not.toContain('?.');
  });
});
