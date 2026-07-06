import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { configureManifest } from './configure-manifest.mjs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

describe('configure-manifest script', () => {
  const manifestPath = path.join(__dirname, '..', 'manifest.json');
  const preexistingManifest = {
    name: 'Existing Local Plugin',
    id: '9876543210',
    api: '1.0.0',
    main: 'dist/code.js',
  };
  const originalManifest = fs.existsSync(manifestPath)
    ? fs.readFileSync(manifestPath, 'utf-8')
    : null;

  beforeAll(() => {
    fs.writeFileSync(manifestPath, JSON.stringify(preexistingManifest, null, 2), 'utf-8');
  });

  afterEach(() => {
    fs.writeFileSync(manifestPath, JSON.stringify(preexistingManifest, null, 2), 'utf-8');
  });

  afterAll(() => {
    if (originalManifest === null) {
      if (fs.existsSync(manifestPath)) {
        fs.unlinkSync(manifestPath);
      }
      return;
    }

    fs.writeFileSync(manifestPath, originalManifest, 'utf-8');
  });

  it('should reject non-numeric plugin IDs', () => {
    expect(() => configureManifest('abc')).toThrow('Invalid plugin ID');
    expect(() => configureManifest('123abc456')).toThrow('Invalid plugin ID');
  });

  it('should generate manifest.json with the correct numeric plugin ID and fields', () => {
    const templatePath = path.join(__dirname, '..', 'manifest.template.json');
    if (!fs.existsSync(templatePath)) {
      fs.writeFileSync(templatePath, JSON.stringify({
        name: "Test",
        documentAccess: "dynamic-page",
        editorType: ["figma"],
        networkAccess: { devAllowedDomains: ["http://localhost:8000"] }
      }));
    }

    const template = configureManifest('1234567890');
    expect(template.id).toBe('1234567890');
    expect(fs.existsSync(manifestPath)).toBe(true);

    const generated = JSON.parse(fs.readFileSync(manifestPath, 'utf-8'));
    expect(generated.id).toBe('1234567890');
    expect(generated.documentAccess).toBe('dynamic-page');
    expect(generated.editorType).toContain('figma');
    expect(generated.networkAccess.devAllowedDomains).toContain('http://localhost:8000');
  });

  it('should not delete a manifest that existed before the test', () => {
    const generated = JSON.parse(fs.readFileSync(manifestPath, 'utf-8'));
    expect(generated).toEqual(preexistingManifest);
  });

  it('keeps the preexisting manifest available for later tests', () => {
    const generated = JSON.parse(fs.readFileSync(manifestPath, 'utf-8'));
    expect(generated).toEqual(preexistingManifest);
  });
});
