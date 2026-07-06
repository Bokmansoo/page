# Sprint 71 보완 코드리뷰: 출력 이력 페이지

> 리뷰 일자: 2026-07-06  
> 원 리뷰 문서: `docs/reviews/2026-07-06-sprint-71-export-history-page-code-review.md`  
> 기획 문서: `docs/superpowers/plans/2026-07-06-sellform-sprint-71-export-history-page.md`

---

## 1. 보완이 필요했던 이유

초기 코드리뷰 문서에는 Sprint 71이 승인된 것으로 기록되어 있었지만, 실제 E2E 검증에서 strict mode selector 충돌이 발생했다.

실패 지점:

- `page.getByText("PNG")`
  - 안내 문구의 `PNG, JPG...`
  - 테이블 badge의 `PNG`
  - 두 요소가 동시에 매칭되어 strict mode 실패

- `page.getByText("다시 다운로드")`
  - 안내 문구의 `다시 다운로드`
  - 실제 다운로드 링크의 `다시 다운로드`
  - 두 요소가 동시에 매칭되어 strict mode 실패

---

## 2. 보완 수정

수정 파일:

- `frontend/e2e/export-history.spec.ts`

수정 내용:

- `PNG`, `JPG` 검증을 `exact: true`로 변경
- `다시 다운로드` 검증을 텍스트 검색이 아닌 링크 role 기준으로 변경

```ts
await expect(page.getByText("PNG", { exact: true })).toBeVisible();
await expect(page.getByText("JPG", { exact: true })).toBeVisible();
await expect(page.getByRole("link", { name: "다시 다운로드" })).toBeVisible();
```

---

## 3. 재검증

```bash
cd frontend
npx.cmd playwright test e2e/export-history.spec.ts --project=chromium --reporter=line
```

결과:

```text
1 passed
```

---

## 4. 최종 판정

**보완 후 승인 (Approved after fixes).**

Sprint 71의 핵심 요구사항은 현재 검증 기준으로 충족한다.

- `출력 이력` 메뉴 클릭 시 alert 없이 `/workspace/exports`로 이동
- 출력 이력 페이지가 표시됨
- export 목록의 상품명, 형식, 상태, 실패 사유가 표시됨
- 완료된 export는 `다시 다운로드` 링크가 표시됨
- Sprint 71 E2E가 통과함

---

## 5. 참고

백엔드 검증은 별도 확인에서 이미 통과했다.

```bash
uv run --project backend pytest backend/tests/test_export_history_api.py -q
```

결과:

```text
3 passed
```
