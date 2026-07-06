import logging
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from src.db.models import AgentRun, ProductPage, PageSection, ProductProject, ProductFact
from src.services.compliance import check_compliance, ComplianceIssue

logger = logging.getLogger(__name__)


def build_qa_warning_issue(warning: Any) -> Dict[str, Any]:
    if isinstance(warning, dict):
        return {
            "severity": "Blocker",
            "rule": warning.get("code") or "IMAGE_QUALITY_CHECK",
            "message": warning.get("message") or "상세페이지 이미지 검수가 필요합니다.",
            "section_id": warning.get("section_id"),
        }

    message = str(warning).strip() if warning is not None else ""
    return {
        "severity": "Blocker",
        "rule": "IMAGE_QUALITY_CHECK",
        "message": message or "상세페이지 이미지 검수가 필요합니다.",
        "section_id": None,
    }


class PageComplianceChecker:
    @staticmethod
    def inspect_page(db: Session, page: ProductPage) -> Dict[str, Any]:
        """
        Inspect all visible sections of the product page for compliance issues and asset integrity.
        Returns a dict:
        {
            "can_export": bool,
            "issues": [
                {
                    "severity": "Blocker" | "Major" | "Warning",
                    "rule": str,
                    "message": str,
                    "section_id": str or None
                }
            ]
        }
        """
        project = page.project
        category = project.category or "Living"
        product_name = project.name
        
        issues_list = []
        can_export = True

        # 활성화된 섹션만 검사
        visible_sections = [sec for sec in page.sections if sec.is_visible]

        # 1. 각 섹션별 문구 규제 검수 (check_compliance 활용)
        for section in visible_sections:
            section_text = f"{section.title or ''} {section.body_copy or ''}".strip()
            if not section_text:
                continue
            
            # 해당 섹션과 연결된 사실 카드가 있으면 함께 수집
            associated_facts = []
            if section.associated_fact_ids:
                facts = db.query(ProductFact).filter(
                    ProductFact.id.in_(section.associated_fact_ids)
                ).all()
                associated_facts = [
                    {"id": f.id, "fact_text": f.fact_text, "source_text": f.source_text}
                    for f in facts
                ]

            # 기존 검수 로직 실행
            compliance_issues = check_compliance(
                category=category,
                product_name=product_name,
                raw_input=section_text,
                extracted_facts=associated_facts
            )

            for issue in compliance_issues:
                issues_list.append({
                    "severity": issue.severity,
                    "rule": issue.rule,
                    "message": f"[{section.section_type}] {issue.message}",
                    "section_id": section.id
                })
                if issue.severity == "Blocker":
                    can_export = False

            if section.section_type in ["features", "header"] and not section.image_asset_id:
                issues_list.append({
                    "severity": "Warning",
                    "rule": "섹션 이미지 누락",
                    "message": f"'{section.title or section.section_type}' 섹션에 이미지 자산이 설정되지 않았습니다.",
                    "section_id": section.id
                })

        # Integrate the latest agent QA output; ProductPage itself has no outputs column.
        latest_run = (
            db.query(AgentRun)
            .filter(AgentRun.project_id == page.project_id)
            .order_by(AgentRun.created_at.desc())
            .first()
        )
        run_outputs = latest_run.outputs_json if latest_run else None
        if isinstance(run_outputs, dict):
            qa_review = run_outputs.get("qa_review")
            if qa_review and isinstance(qa_review, dict):
                if not qa_review.get("can_export", True):
                    can_export = False
                    for warning in qa_review.get("warnings") or []:
                        issues_list.append(build_qa_warning_issue(warning))

        return {
            "can_export": can_export,
            "issues": issues_list
        }
