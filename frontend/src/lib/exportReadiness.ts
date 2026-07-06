export async function waitForExportAssets(): Promise<{
  ok: boolean;
  errors: string[];
}> {
  await document.fonts.ready;
  const errors: string[] = [];

  await Promise.all(
    Array.from(document.images).map(
      (image) =>
        new Promise<void>((resolve) => {
          if (image.complete) {
            if (!image.naturalWidth) {
              errors.push(image.currentSrc || image.src);
            }
            resolve();
            return;
          }
          image.addEventListener("load", () => resolve(), { once: true });
          image.addEventListener(
            "error",
            () => {
              errors.push(image.currentSrc || image.src);
              resolve();
            },
            { once: true }
          );
        })
    )
  );

  return { ok: errors.length === 0, errors };
}
