# 테스트 실행 로그: Sellform Sprint 11 Facts UX

- 날짜: 2026-06-24
- 목적: 사실 확인 보드 문구 정상화와 자동 사실 생성 UX를 검증한다.

## 1. 프론트 빌드

```text
npm.cmd run build

결과:
▲ Next.js 14.2.35
   Creating an optimized production build ...
 ✓ Compiled successfully
   Linting and checking validity of types ...
   Collecting page data ...
   Generating static pages (9/9)
   Finalizing page optimization ...
   Collecting build traces ...
Route (app)                               Size     First Load JS
├ ƒ /workspace/projects/[id]/facts        7.23 kB         103 kB
```

## 2. 데스크톱 수동 QA

- **확인 경로**: `http://localhost:3000/workspace/projects/{project_id}/facts`
- **결과**:
  - **오타 및 번역 오류 해결**: 감사 모달 제목이 `"사실 카드 변경 이력 (감사 감사)"`에서 `"사실 카드 변경 이력 (감사 로그)"`로 명확하게 정상화되었습니다.
  - **용어 표준화**: UI 전반에 걸쳐 기획서의 표준 문구("소싱 근거 자료", "확인된 사실", "AI 후보", "수정 필요", "모름", "검증 완료 및 다음 단계" 등)가 일관성 있게 표시됩니다.
  - **AI 자동생성 안내**: AI 사실 카드 자동 생성 버튼의 안내 문구(`AI가 소싱 텍스트와 업로드 이미지를 바탕으로 사실 후보를 만듭니다...`)가 상단 헤더에 정교하게 배치되어 사용성이 개선되었습니다.
  - **URL Fallback 메시지**: 링크 수집 유예 시 원문 메시지 대신 `"링크 직접 수집은 아직 지원하지 않아 입력 텍스트와 업로드 이미지를 우선 분석했습니다."`가 친절하게 한글로 렌더링되는 것을 확인했습니다.
  - **카드 정보 구조 고도화**:
    - AI 후보 출처가 `manual_text` 대신 `"텍스트 근거"`, `image` 대신 `"이미지 근거"` 등으로 표준 한국어로 매핑되어 표시됩니다.
    - 신뢰도 역시 `신뢰도 95%` 형태로 포맷팅되어 표시됩니다.
    - 검수 필요 리스크 플래그가 `certification_review` 대신 `"인증/표기 확인 필요"` 등 한국어로 친절하게 매핑되어 노출됩니다.

## 3. 모바일 수동 QA

- **기준 폭**: 390px (iPhone 12 Pro / SE 규격)
- **결과**:
  - **상단 버튼 그룹 개선**: `flex-wrap gap-2` 구조를 적용하여 상단 우측의 3가지 액션 버튼(AI로 사실 카드 자동 생성, 사실 카드 수동 추가, 검증 완료 및 다음 단계)이 모바일 폭에서 화면 밖으로 밀리거나 깨지지 않고 정렬이 유지됩니다.
  - **빈 상태 레이아웃**: 사실 카드가 없을 때 보여주는 빈 상태 박스 내부에서 두 버튼("AI로 사실 카드 자동 생성", "사실 카드 수동 추가")이 자연스러운 정렬을 가지며 스크롤 없이 터치가 가능한 최적의 영역을 확보했습니다.

## 4. 판단

Sprint 11에서 목표한 사실 검증 보드의 모든 한글 텍스트 교정 및 모바일 반응형 UX 개선이 완벽하게 완료되었습니다.
