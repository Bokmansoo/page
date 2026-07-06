import pytest
from types import SimpleNamespace
from src.services import visual_package_planner
from src.services.visual_package_planner import VisualPackagePlanner
from src.services.image_generation_contract import ImageGenerationJob
from src.services.commerce_visual_cut_builder import CommerceVisualCut

class MockProject:
    def __init__(self, id, name, selected_background=None):
        self.id = id
        self.name = name
        self.selected_background = selected_background or "cooling-blue"

class MockSection:
    def __init__(self, id, section_type, title, body_copy, image_asset_id=None):
        self.id = id
        self.section_type = section_type
        self.title = title
        self.body_copy = body_copy
        self.image_asset_id = image_asset_id

class MockPage:
    def __init__(self, sections):
        self.sections = sections

class MockAsset:
    def __init__(self, id, filename, mime_type, source_type="uploaded"):
        self.id = id
        self.filename = filename
        self.mime_type = mime_type
        self.source_type = source_type


def test_resolve_sales_strategy_prefers_confirmed_user_decision():
    confirmed = {
        "target_customer": "직접 확정한 고객",
        "buyer_problem": "직접 확정한 고민",
        "main_selling_point": "직접 확정한 소구점",
        "tone": "직접 확정한 톤",
        "selected_direction": "emotional",
    }
    project = SimpleNamespace(
        intake_snapshot={"confirmed_sales_strategy": confirmed},
    )

    resolved = visual_package_planner.resolve_sales_strategy(
        project,
        generated_strategy={"target_customer": "자동 생성 고객"},
    )

    assert resolved == confirmed


def test_visual_package_signature_changes_when_inputs_change():
    project = SimpleNamespace(
        id="project-1",
        name="상품",
        selected_style="problem_solution",
        selected_background="cooling-blue",
    )
    page = MockPage(
        sections=[MockSection("sec-1", "header", "제목", "본문")]
    )
    assets = [MockAsset("asset-1", "front.jpg", "image/jpeg")]

    first = visual_package_planner.build_visual_package_signature(
        project,
        page,
        assets,
        {"target_customer": "고객 A"},
    )
    second = visual_package_planner.build_visual_package_signature(
        project,
        page,
        assets,
        {"target_customer": "고객 B"},
    )

    assert first != second

def test_visual_package_planning_flow():
    # 1. Setup mock data
    project = MockProject(id="proj-1", name="루메나 휴대용 선풍기", selected_background="cooling-blue")
    
    sections = [
        MockSection(
            id="sec-1",
            section_type="header",
            title="루메나 휴대용 선풍기",
            body_copy="언제 어디서나 시원한 바람을 제공합니다.",
            image_asset_id="asset-1" # original product photo mapped
        ),
        MockSection(
            id="sec-2",
            section_type="problem_statement",
            title="더운 여름철 야외 활동",
            body_copy="조금만 걸어도 땀이 흐르는 무더위 속에서 힘드셨나요?",
            image_asset_id=None # needs generation
        )
    ]
    page = MockPage(sections=sections)
    
    assets = [
        MockAsset(id="asset-1", filename="fan-front.png", mime_type="image/png"),
        MockAsset(id="asset-2", filename="unknown.jpg", mime_type="application/pdf")
    ]
    
    # 2. Add mock sales strategy
    sales_strategy = {
        "target_customer": "야외 활동을 자주 하는 직장인",
        "buyer_problem": "무더위로 가득한 출퇴근 길",
        "main_selling_point": "강풍 3단계 강력 서큘레이터형 팬",
        "tone": "시원하고 에너제틱한 블루 톤"
    }
    
    planner = VisualPackagePlanner()
    jobs = planner.plan_visual_package(project, page, assets, sales_strategy)
    
    assert len(jobs) == 2
    
    # First job should be mapped to header -> representative_product
    job1 = jobs[0]
    assert isinstance(job1, ImageGenerationJob)
    assert job1.job_id.startswith("job-")
    assert job1.section_id == "sec-1"
    assert job1.role == "representative_product"
    assert job1.status == "planned"
    assert job1.source_asset_ids == ["asset-1"]
    
    # Second job should be mapped to problem_statement -> problem_scene
    job2 = jobs[1]
    assert job2.job_id.startswith("job-")
    assert job2.section_id == "sec-2"
    assert job2.role == "problem_scene"
    assert job2.status == "needs_generation"
    
    # Verify sales strategy details are woven into the prompt
    assert "출퇴근 길" in job2.prompt
    assert "Strictly do NOT include any text" in job2.prompt
    assert "text" in job2.negative_prompt
