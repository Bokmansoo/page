import { DetailPagePackage } from './contracts';

export function validatePackage(data: any): DetailPagePackage {
  if (!data || typeof data !== 'object') {
    throw new Error('INVALID_PACKAGE_FORMAT');
  }

  if (data.schema_version !== '1.0') {
    throw new Error('UNSUPPORTED_SCHEMA_VERSION');
  }

  const { payload } = data;
  if (!payload || typeof payload !== 'object') {
    throw new Error('MISSING_PAYLOAD');
  }

  if (!payload.project || typeof payload.project !== 'object') {
    throw new Error('MISSING_PROJECT_INFO');
  }

  if (!payload.brand || typeof payload.brand !== 'object') {
    throw new Error('MISSING_BRAND_INFO');
  }

  if (!payload.page || typeof payload.page !== 'object') {
    throw new Error('MISSING_PAGE_INFO');
  }

  if (!Array.isArray(payload.cuts)) {
    throw new Error('MISSING_CUTS');
  }
  if (payload.schema_version !== '1.0') {
    throw new Error('UNSUPPORTED_PAYLOAD_SCHEMA_VERSION');
  }
  if (payload.cuts.length !== 7) {
    throw new Error('INVALID_CUT_COUNT');
  }

  if (payload.visual_layout !== undefined) {
    if (!payload.visual_layout || typeof payload.visual_layout !== 'object') {
      throw new Error('INVALID_VISUAL_LAYOUT');
    }
    if (payload.visual_layout.layout_version !== 'commerce_visual_v1') {
      throw new Error('UNSUPPORTED_VISUAL_LAYOUT_VERSION');
    }
    if (!Array.isArray(payload.visual_layout.cuts)) {
      throw new Error('MISSING_VISUAL_CUTS');
    }
    if (payload.visual_layout.cuts.length !== 7) {
      throw new Error('INVALID_VISUAL_CUT_COUNT');
    }
  }

  return data as DetailPagePackage;
}
