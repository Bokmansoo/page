export async function waitForExportAssets(): Promise<{
  ok: boolean;
  errors: string[];
}> {
  const assetTimeoutMs = 10000;
  await Promise.race([
    document.fonts.ready,
    new Promise<void>((resolve) => window.setTimeout(resolve, assetTimeoutMs)),
  ]);
  const errors: string[] = [];

  await Promise.all(
    Array.from(document.images).map(
      (image) =>
        new Promise<void>((resolve) => {
          let settled = false;
          const finish = (error?: string) => {
            if (settled) return;
            settled = true;
            if (error) errors.push(error);
            resolve();
          };

          if (image.complete) {
            if (!image.naturalWidth) {
              errors.push(image.currentSrc || image.src);
            }
            resolve();
            return;
          }
          const timeout = window.setTimeout(() => {
            finish(image.currentSrc || image.src || "image load timeout");
          }, assetTimeoutMs);
          image.addEventListener("load", () => {
            window.clearTimeout(timeout);
            finish();
          }, { once: true });
          image.addEventListener(
            "error",
            () => {
              window.clearTimeout(timeout);
              finish(image.currentSrc || image.src);
            },
            { once: true }
          );
        })
    )
  );

  return { ok: errors.length === 0, errors };
}
