# Sellform V2 UX-2 Code Review

Date: 2026-08-06  
Scope: Coupang-style HTML-first detail page output in Mock mode

## Review result

UX-2 acceptance criteria are implemented for the Mock path.

- The fixed vertical template contains HERO, purchase context, three grounded feature sections, usage guidance, product details/components, and a final product-information section.
- Only `uploaded` and `self_shot` assets can be auto-placed in this Mock output. URL/supplier assets are excluded before page assembly.
- Any section without an allowed photo is an HTML/CSS section, never a fake image asset or a `photo required` final-page block.
- A Mock HTML HERO is export-safe. The final product-information section is always last; it becomes a fact-grounded spec table when approved facts exist and an honest notice section otherwise.
- Mock copy is Korean and excludes unsupported certification, safety, treatment, warranty, A/S, and performance claims.
- The result sidebar omits HTML sections, so it does not ask users to add images for deliberate HTML output.

## Verification

```text
backend/.venv/Scripts/python.exe -m pytest tests/test_agent_run_api.py tests/test_page_readiness_service.py tests/test_ux2_mock_output.py -q -p no:cacheprovider
```

Result: 22 passed.

```text
npm.cmd run lint
```

Result: passed with existing Next.js `<img>` and hook-dependency warnings.

```text
npm.cmd run test:e2e -- e2e/ux2-mock-output.spec.ts
```

Result: the UX-2 browser test passed. In this local environment Playwright leaves its dev-server process alive after completion, so the wrapper command reaches its timeout after reporting `ok 1`.

## Coverage added

- Mock assembly contains all three feature slots and excludes URL/supplier assets.
- A no-photo Mock run is export-ready and ends with `product_information`.
- Three seller-confirmed facts render as three grounded feature cards and a final spec table.
- Browser test verifies no `사진 필요` placeholder, final spec value rendering, and PNG browser download.

## Known boundary

Mock mode intentionally does not fabricate lifestyle scenes, such as a person using or charging the product. Those images remain for the image-generation-provider phase and must pass product-identity review before final output.
