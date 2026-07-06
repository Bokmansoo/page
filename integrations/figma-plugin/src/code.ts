import { renderDetailPage } from './renderer';
import { validatePackage } from './payload-validator';

figma.showUI(__html__, { width: 340, height: 460 });

figma.ui.onmessage = async (msg) => {
  if (msg.type === 'render-package') {
    try {
      const validated = validatePackage(msg.package);
      const imageBytesByRef: Record<string, Uint8Array> = {};

      for (const [ref, bytes] of Object.entries(msg.imageBytesByRef)) {
        if (bytes instanceof Uint8Array) {
          imageBytesByRef[ref] = bytes;
        } else if (Array.isArray(bytes) || bytes instanceof ArrayBuffer) {
          imageBytesByRef[ref] = new Uint8Array(bytes as any);
        } else {
          // If it is a base64 string or other format, convert or handle
          imageBytesByRef[ref] = new Uint8Array(Object.values(bytes) as any);
        }
      }

      const result = await renderDetailPage(validated, imageBytesByRef, figma);

      if (result.root) {
        figma.currentPage.selection = [result.root];
        figma.viewport.scrollAndZoomIntoView([result.root]);
      }

      figma.ui.postMessage({
        type: 'render-complete',
        warnings: result.warnings
      });
    } catch (err: any) {
      console.error(err);
      figma.ui.postMessage({
        type: 'render-error',
        error: err.message || 'Rendering failed'
      });
    }
  }
};
