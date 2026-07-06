import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { inspectProductionBuild } from "../scripts/verify-production-build.mjs";

async function createFixture({ includeResultRoute = true, staleSource = false } = {}) {
  const root = await mkdtemp(path.join(os.tmpdir(), "sellform-build-check-"));
  const nextDir = path.join(root, ".next");
  const sourceDir = path.join(
    root,
    "src",
    "app",
    "workspace",
    "projects",
    "[id]",
    "result"
  );

  await mkdir(path.join(nextDir, "server"), { recursive: true });
  await mkdir(sourceDir, { recursive: true });
  await writeFile(path.join(nextDir, "BUILD_ID"), "build-1");
  await writeFile(
    path.join(nextDir, "server", "app-paths-manifest.json"),
    JSON.stringify(
      includeResultRoute
        ? {
            "/workspace/projects/[id]/result/page":
              "app/workspace/projects/[id]/result/page.js",
          }
        : {}
    )
  );
  await new Promise((resolve) => setTimeout(resolve, 20));
  await writeFile(path.join(sourceDir, "page.tsx"), "export default function Page() {}");

  if (!staleSource) {
    await new Promise((resolve) => setTimeout(resolve, 20));
    await writeFile(path.join(nextDir, "BUILD_ID"), "build-1");
  }

  return root;
}

test("rejects a production build that omits the result route", async () => {
  const root = await createFixture({ includeResultRoute: false });

  const result = await inspectProductionBuild(root);

  assert.equal(result.ok, false);
  assert.match(result.errors.join("\n"), /result route/i);
});

test("rejects a production build older than frontend source", async () => {
  const root = await createFixture({ staleSource: true });

  const result = await inspectProductionBuild(root);

  assert.equal(result.ok, false);
  assert.match(result.errors.join("\n"), /newer than the production build/i);
});

test("accepts a fresh production build containing the result route", async () => {
  const root = await createFixture();

  const result = await inspectProductionBuild(root);

  assert.deepEqual(result, { ok: true, errors: [] });
});
