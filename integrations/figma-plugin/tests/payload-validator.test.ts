import { validatePackage } from '../src/payload-validator';

describe('Payload Validator Tests', () => {
  const makeCuts = () => Array.from({ length: 7 }, (_, index) => ({
    section_id: `s${index + 1}`,
    section_type: `section_${index + 1}`,
    layout_type: 'features',
    headline: `Title ${index + 1}`,
    subcopy: 'Copy',
    supporting_text: null,
    image_url: null,
    background_style: 'clean',
  }));

  const makeVisualCuts = () => makeCuts().map((cut, index) => ({
    ...cut,
    image_role: index === 0 ? 'product_main' : 'lifestyle_scene',
    image_asset_ref: index === 0 ? 'asset-main' : null,
    visual_slot: {
      kind: index === 0 ? 'image' : 'placeholder',
      asset_ref: index === 0 ? 'asset-main' : null,
      image_url: index === 0 ? 'asset-main' : null,
      fallback_label: '상품 비주얼',
    },
    badges: ['강력 냉각'],
    background_tone: 'cool_blue',
    emphasis_level: index === 0 ? 2 : 1,
  }));

  it('should throw error for unsupported schema version', () => {
    expect(() => validatePackage({ schema_version: '2.0' }))
      .toThrow('UNSUPPORTED_SCHEMA_VERSION');
  });

  it('should throw error for missing payload', () => {
    expect(() => validatePackage({ schema_version: '1.0' }))
      .toThrow('MISSING_PAYLOAD');
  });

  it('should throw error for missing cuts list', () => {
    expect(() => validatePackage({
      schema_version: '1.0',
      payload: {
        project: { id: 'p1', name: 'Proj', category: 'Living' },
        brand: { name: 'Brand', primary_color: '#fff', font_family: 'sans-serif' },
        page: { canvas_width: 860, channel: 'naver', style_key: 'modern' }
      }
    })).toThrow('MISSING_CUTS');
  });

  it('should validate correctly when all fields are correct', () => {
    const cuts = makeCuts();
    const pkg = {
      schema_version: '1.0',
      payload: {
        schema_version: '1.0',
        project: { id: 'p1', name: 'Proj', category: 'Living' },
        brand: { name: 'Brand', primary_color: '#fff', font_family: 'sans-serif' },
        page: { canvas_width: 860, channel: 'naver', style_key: 'modern' },
        cuts,
      },
      embedded_assets: []
    };
    expect(validatePackage(pkg)).toEqual(pkg);
  });

  it('rejects packages that do not contain the canonical seven cuts', () => {
    expect(() => validatePackage({
      schema_version: '1.0',
      payload: {
        schema_version: '1.0',
        project: { id: 'p1', name: 'Proj', category: 'Living' },
        brand: { name: 'Brand', primary_color: '#fff', font_family: 'Inter' },
        page: { canvas_width: 860, channel: 'naver', style_key: 'modern' },
        cuts: [],
      },
      embedded_assets: [],
    })).toThrow('INVALID_CUT_COUNT');
  });

  it('accepts the commerce visual layout extension', () => {
    const pkg = {
      schema_version: '1.0',
      payload: {
        schema_version: '1.0',
        project: { id: 'p1', name: 'Proj', category: 'Living' },
        brand: { name: 'Brand', primary_color: '#2D7DFF', font_family: 'Inter' },
        page: { canvas_width: 860, channel: 'naver', style_key: 'modern' },
        cuts: makeCuts(),
        visual_layout: {
          layout_version: 'commerce_visual_v1',
          width: 860,
          category: 'Living',
          style_key: 'modern',
          background_key: 'cooling-blue',
          cuts: makeVisualCuts(),
        },
      },
      embedded_assets: [],
    };

    expect(validatePackage(pkg)).toEqual(pkg);
  });

  it('rejects malformed visual layout cut counts', () => {
    expect(() => validatePackage({
      schema_version: '1.0',
      payload: {
        schema_version: '1.0',
        project: { id: 'p1', name: 'Proj', category: 'Living' },
        brand: { name: 'Brand', primary_color: '#2D7DFF', font_family: 'Inter' },
        page: { canvas_width: 860, channel: 'naver', style_key: 'modern' },
        cuts: makeCuts(),
        visual_layout: {
          layout_version: 'commerce_visual_v1',
          width: 860,
          category: 'Living',
          style_key: 'modern',
          background_key: 'cooling-blue',
          cuts: makeVisualCuts().slice(0, 6),
        },
      },
      embedded_assets: [],
    })).toThrow('INVALID_VISUAL_CUT_COUNT');
  });
});
