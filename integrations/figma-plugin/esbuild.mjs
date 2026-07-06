import esbuild from 'esbuild';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

async function build() {
  fs.mkdirSync('dist', { recursive: true });

  // Build main thread code
  await esbuild.build({
    entryPoints: ['src/code.ts'],
    bundle: true,
    platform: 'neutral',
    target: 'es2017',
    outfile: 'dist/code.js',
    minify: false,
  });

  // Build UI thread code
  await esbuild.build({
    entryPoints: ['src/ui.ts'],
    bundle: true,
    platform: 'browser',
    target: 'es2017',
    outfile: 'dist/ui.js',
    minify: false,
  });

  // Inline UI JS into UI HTML
  const htmlTemplate = fs.readFileSync('src/ui.html', 'utf8');
  const jsContent = fs.readFileSync('dist/ui.js', 'utf8');
  
  // Append script tag inside body
  const inlinedHtml = htmlTemplate.replace('</body>', `<script>\n${jsContent}\n</script>\n</body>`);

  fs.writeFileSync('dist/ui.html', inlinedHtml, 'utf8');
  console.log('Figma Plugin build succeeded.');
}

build().catch(err => {
  console.error(err);
  process.exit(1);
});
