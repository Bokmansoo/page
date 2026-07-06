# Sellform Sprint 22 Living Golden Path UX Troubleshooting

## 1. Issue: TypeScript Build Failure due to Explicit Any Type
- **발생 증상**: 프론트엔드 최적화 빌드(`npm run build`) 수행 시, `@typescript-eslint/no-explicit-any` 규칙 위반으로 인해 빌드가 실패함.
  ```text
  ./src/app/workspace/projects/[id]/page-editor/page.tsx
  60:42  Error: Unexpected any. Specify a different type.  @typescript-eslint/no-explicit-any
  131:53  Error: Unexpected any. Specify a different type.  @typescript-eslint/no-explicit-any
  ```
- **원인 분석**: `page-editor/page.tsx` 내에서 프로젝트 데이터를 보관하는 `project` 상태의 초기값 타입이 `useState<any>(null)`로 지정되어 있었고, 팩트의 verification_status를 필터링하는 화살표 함수 내 매개변수 타입이 `(f: any)`로 기술되어 있었습니다.
- **해결 조치**: 
  - `ProductProject` 및 `Fact` 인터페이스 타입을 정의하여 `any`를 걷어냈습니다.
  ```typescript
  interface ProductProject {
    id: string;
    workspace_id: string;
    brand_id: string;
    name: string;
    product_url: string;
    image_url: string | null;
    status: string;
    current_step: string;
    category: string | null;
    category_confirmed: boolean;
    category_confirmed_at: string | null;
    created_at: string;
    updated_at: string;
  }

  interface Fact {
    id: string;
    project_id: string;
    fact_text: string;
    verification_status: 'confirmed' | 'unconfirmed' | 'rejected';
  }
  ```
  - `useState<ProductProject | null>(null)`과 `(f: Fact)`로 정밀 매핑하여 컴파일 타임 에러를 완벽하게 해결했습니다.

## 2. Issue: Layout Overlap in Export Page with New Headers
- **발생 증상**: `export/page.tsx`에 `WorkflowStepHeader`와 `NextActionPanel`을 새로 삽입하면서 기존의 `p-6` 클래스를 가진 grid 레이아웃 상단 마진이 겹쳐서 디자인이 비좁아 보이고 어색하게 틀어지는 현상이 관찰됨.
- **원인 분석**: grid container에 `p-6`가 전체적으로 잡혀있는 상태에서 상단에 헤더와 패널을 배치했기 때문에 발생한 레이아웃 위계 불일치입니다.
- **해결 조치**:
  - `WorkflowStepHeader`와 `NextActionPanel`을 `max-w-6xl w-full mx-auto px-6 pt-6`로 감싸 별도 정적 영역으로 헤더 바로 하단에 배치했습니다.
  - 본문 grid container의 클래스를 `p-6` 대신 `px-6 pb-6`로 조정하여, 전체 스크롤 영역 내에서도 구성 요소 간의 간격(Gap)이 일정한 비율을 유지하도록 개선했습니다.
---

## 3. Issue: Facts Page Runtime Crash When `assets` Field Is Missing

- **발생 증상**: Playwright E2E 실행 중 사실 확인 페이지(`/workspace/projects/[id]/facts`)가 렌더링 단계에서 크래시했습니다.

  ```text
  TypeError: Cannot read properties of undefined (reading 'length')
  Source: frontend/src/app/workspace/projects/[id]/facts/page.tsx
  ```

- **원인 분석**:
  - 프론트엔드 `ProductProject` 타입은 `assets: Asset[]`를 필수값으로 가정했습니다.
  - 하지만 API 응답 또는 테스트 mock에서 `assets` 필드가 누락될 수 있었고, 이 상태에서 `project.assets.length`, `project.assets.map`, `project.assets.find`를 직접 호출해 런타임 오류가 발생했습니다.

- **해결 조치**:
  - `ProductProject.assets`를 optional로 변경했습니다.
  - 렌더링 진입부에서 `const projectAssets = project.assets ?? []` fallback을 만들고, 화면 전체에서 해당 안전 배열을 사용하도록 수정했습니다.
  - E2E mock 데이터에도 `assets: []`를 명시해 정상 응답 형태를 더 분명히 했습니다.

- **검증**:

  ```powershell
  cd frontend
  npm.cmd run test:e2e
  npm.cmd run build
  ```

  - E2E: 3 passed
  - Build: PASS

- **재발 방지**:
  - 이후 API 응답 필드가 optional이거나 backend/frontend 계약이 변할 수 있는 영역은 UI에서 안전 fallback을 둡니다.
  - Sprint 22 핵심 플로우는 Playwright E2E로 회귀 검증합니다.
