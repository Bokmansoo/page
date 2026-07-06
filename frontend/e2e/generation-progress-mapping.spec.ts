import { expect, test } from "@playwright/test";

import {
  monotonicProgressStage,
  progressStepIndex,
} from "../src/lib/generationProgress";

test("completed review editor status stays on the QA step", () => {
  expect(progressStepIndex("review_editor")).toBe(7);
});

test("late polling responses cannot move progress backwards", () => {
  expect(monotonicProgressStage("page_assembly", "product_understanding")).toBe(
    "page_assembly"
  );
  expect(monotonicProgressStage("page_assembly", "qa_review")).toBe("qa_review");
});
