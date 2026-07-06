import { access, readdir, readFile, stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const RESULT_ROUTE = "/workspace/projects/[id]/result/page";
const SOURCE_EXTENSIONS = new Set([".css", ".js", ".jsx", ".ts", ".tsx"]);

async function collectSourceFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(
    entries.map(async (entry) => {
      const entryPath = path.join(directory, entry.name);
      if (entry.isDirectory()) {
        return collectSourceFiles(entryPath);
      }
      return SOURCE_EXTENSIONS.has(path.extname(entry.name)) ? [entryPath] : [];
    })
  );
  return nested.flat();
}

export async function inspectProductionBuild(rootDirectory) {
  const errors = [];
  const buildIdPath = path.join(rootDirectory, ".next", "BUILD_ID");
  const manifestPath = path.join(
    rootDirectory,
    ".next",
    "server",
    "app-paths-manifest.json"
  );

  try {
    await access(buildIdPath);
    await access(manifestPath);
  } catch {
    return {
      ok: false,
      errors: ["Production build is missing. Run `npm.cmd run start:fresh`."],
    };
  }

  let manifest;
  try {
    manifest = JSON.parse(await readFile(manifestPath, "utf8"));
  } catch {
    errors.push("Production route manifest is unreadable. Rebuild the frontend.");
    manifest = {};
  }

  if (!Object.hasOwn(manifest, RESULT_ROUTE)) {
    errors.push(
      "The result route is missing from the production build. Run `npm.cmd run start:fresh`."
    );
  }

  const sourceDirectory = path.join(rootDirectory, "src");
  const [buildStat, sourceFiles] = await Promise.all([
    stat(buildIdPath),
    collectSourceFiles(sourceDirectory),
  ]);
  const staleFiles = [];

  for (const sourceFile of sourceFiles) {
    const sourceStat = await stat(sourceFile);
    if (sourceStat.mtimeMs > buildStat.mtimeMs) {
      staleFiles.push(path.relative(rootDirectory, sourceFile));
    }
  }

  if (staleFiles.length > 0) {
    errors.push(
      `Frontend source is newer than the production build (${staleFiles[0]}${
        staleFiles.length > 1 ? ` and ${staleFiles.length - 1} more` : ""
      }). Run \`npm.cmd run start:fresh\`.`
    );
  }

  return { ok: errors.length === 0, errors };
}

async function main() {
  const result = await inspectProductionBuild(process.cwd());
  if (!result.ok) {
    for (const error of result.errors) {
      console.error(`[production-build-check] ${error}`);
    }
    process.exitCode = 1;
    return;
  }
  console.log("[production-build-check] Build is fresh and includes the result route.");
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await main();
}
