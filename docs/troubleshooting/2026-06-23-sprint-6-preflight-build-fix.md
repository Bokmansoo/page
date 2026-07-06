# 트러블슈팅: Sprint 6 진입 전 프론트 빌드 실패

| 항목 | 내용 |
| --- | --- |
| 일자 | 2026-06-23 |
| 증상 | `npm.cmd run build` 실행 시 ESLint `no-explicit-any` 오류로 빌드 실패 |
| 위치 | `frontend/src/app/workspace/projects/[id]/publish/page.tsx` |

## 1. 증상

프론트엔드 전체 빌드에서 다음 오류가 발생했다.

```text
./src/app/workspace/projects/[id]/publish/page.tsx
162:19  Error: Unexpected any. Specify a different type.  @typescript-eslint/no-explicit-any
```

## 2. 원인

`handlePublish`의 `catch` 블록에서 에러 메시지를 읽기 위해 `catch (err: any)`를 사용하고 있었다. 현재 ESLint 설정에서는 명시적 `any` 사용이 빌드 실패로 처리된다.

## 3. 조치

`catch (err: unknown)`으로 변경하고, `err instanceof Error`로 타입을 좁혀 메시지를 꺼내도록 수정했다.

## 4. 검증

- `npm.cmd run build`: 통과
- `uv run --project . pytest -q`: `43 passed, 148 warnings`

## 5. 남은 사항

`frontend/src/app/p/[id]/page.tsx`에 `<img>` 사용 경고가 남아 있다. 현재는 warning이라 빌드 차단 요인은 아니며, Sprint 6 또는 성능 최적화 단계에서 `next/image` 전환을 검토하면 된다.
