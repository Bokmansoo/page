export const BACKEND_STAGE_GROUPS = [
  ["input_router", "source_collection", "product_understanding", "reference_analysis"],
  ["sales_strategy"],
  ["page_planning"],
  ["copywriting"],
  ["visual_planning"],
  ["image_generation"],
  ["page_assembly"],
  ["qa_review", "review_editor"],
] as const;

const STAGE_ORDER = [
  "input_router",
  "source_collection",
  "product_understanding",
  "reference_analysis",
  "sales_strategy",
  "page_planning",
  "copywriting",
  "visual_planning",
  "image_generation",
  "page_assembly",
  "qa_review",
  "review_editor",
] as const;

export function progressStepIndex(stage: string): number {
  const index = BACKEND_STAGE_GROUPS.findIndex((stages) =>
    (stages as readonly string[]).includes(stage)
  );
  return index >= 0 ? index : 0;
}

export function monotonicProgressStage(
  currentStage: string,
  incomingStage: string
): string {
  const currentRank = STAGE_ORDER.indexOf(currentStage as never);
  const incomingRank = STAGE_ORDER.indexOf(incomingStage as never);
  if (incomingRank < 0) return currentStage;
  return incomingRank >= currentRank ? incomingStage : currentStage;
}
