import fs from 'fs';
import path from 'path';
import readline from 'readline';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export function configureManifest(pluginId) {
  if (!/^\d+$/.test(pluginId)) {
    throw new Error("Invalid plugin ID. Must be a numeric string.");
  }

  const templatePath = path.join(__dirname, '..', 'manifest.template.json');
  const outputPath = path.join(__dirname, '..', 'manifest.json');

  const template = JSON.parse(fs.readFileSync(templatePath, 'utf-8'));
  template.id = pluginId;

  fs.writeFileSync(outputPath, JSON.stringify(template, null, 2), 'utf-8');
  return template;
}

function runInteractive() {
  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout
  });

  rl.question('Enter your numeric Figma Plugin ID: ', (answer) => {
    try {
      configureManifest(answer.trim());
      console.log('Successfully generated manifest.json with plugin ID:', answer);
    } catch (err) {
      console.error('Error:', err.message);
    } finally {
      rl.close();
    }
  });
}

const args = process.argv.slice(2);
const invokedPath = process.argv[1] ? path.resolve(process.argv[1]) : '';
const isRunDirectly = invokedPath === __filename;

// If run directly
if (isRunDirectly) {
  if (args.length > 0) {
    try {
      configureManifest(args[0]);
      console.log('Successfully generated manifest.json with plugin ID:', args[0]);
    } catch (err) {
      console.error('Error:', err.message);
      process.exit(1);
    }
  } else {
    runInteractive();
  }
}
