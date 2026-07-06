import datetime
import uuid
import logging
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from src.api.auth import get_current_user_and_workspace
from src.db.database import get_db
from src.db.models import (
    ProductProject, ProductFact, Asset, JobStatus, AiJobLog, 
    ProductPage, PageSection, ExportJob, PublishedPage, Brand, User, AuditLog
)
from src.services.compliance_checker import PageComplianceChecker
from src.services.generation_status_service import GenerationStatusService

router = APIRouter(prefix="/operations", tags=["Operations"])
logger = logging.getLogger(__name__)

# =====================================================================
# API Endpoints
# =====================================================================

@router.get("/stats")
def get_operations_stats(
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    
    # 1. Query all projects in this workspace
    projects = db.query(ProductProject).filter(
        ProductProject.workspace_id == workspace.id
    ).all()
    
    project_list = []
    
    # AI Job counts and failures
    total_ai_jobs = 0
    failed_ai_jobs = 0
    total_ai_duration_ms = 0
    total_ai_cost = 0.0
    
    # Export Job counts and failures
    total_export_jobs = 0
    failed_export_jobs = 0
    total_export_duration_seconds = 0
    completed_export_count = 0
    
    # Category statistics dictionary
    # categories: Fashion, Beauty, Food, Living
    category_stats = {
        "Fashion": {"project_count": 0, "total_issues": 0, "blocker_count": 0, "major_count": 0, "warning_count": 0},
        "Beauty": {"project_count": 0, "total_issues": 0, "blocker_count": 0, "major_count": 0, "warning_count": 0},
        "Food": {"project_count": 0, "total_issues": 0, "blocker_count": 0, "major_count": 0, "warning_count": 0},
        "Living": {"project_count": 0, "total_issues": 0, "blocker_count": 0, "major_count": 0, "warning_count": 0}
    }
    
    for project in projects:
        # Determine category normalization (default to Living if not set)
        cat = project.category or "Living"
        if cat not in category_stats:
            category_stats[cat] = {"project_count": 0, "total_issues": 0, "blocker_count": 0, "major_count": 0, "warning_count": 0}
            
        category_stats[cat]["project_count"] += 1
        
        # Get AI logs for this project
        ai_logs = db.query(AiJobLog).filter(AiJobLog.project_id == project.id).all()
        project_ai_count = len(ai_logs)
        project_ai_cost = sum(log.estimated_cost or 0.0 for log in ai_logs)
        project_ai_duration = sum(log.duration_ms for log in ai_logs)
        
        last_ai_status = "none"
        if ai_logs:
            sorted_ai_logs = sorted(ai_logs, key=lambda x: x.created_at, reverse=True)
            last_ai_status = sorted_ai_logs[0].status
            
        for log in ai_logs:
            total_ai_jobs += 1
            if log.status == "failed":
                failed_ai_jobs += 1
            total_ai_duration_ms += log.duration_ms
            total_ai_cost += (log.estimated_cost or 0.0)
            
        # Get Export jobs for this project
        export_jobs = db.query(ExportJob).filter(ExportJob.project_id == project.id).all()
        project_export_count = len(export_jobs)
        
        last_export_status = "none"
        if export_jobs:
            sorted_exports = sorted(export_jobs, key=lambda x: x.created_at, reverse=True)
            last_export_status = sorted_exports[0].status
            
        for job in export_jobs:
            total_export_jobs += 1
            if job.status == "failed":
                failed_export_jobs += 1
            if job.status == "completed" and job.completed_at and job.created_at:
                diff = (job.completed_at - job.created_at).total_seconds()
                total_export_duration_seconds += diff
                completed_export_count += 1
                
        # Get Compliance check issues for the page
        page = db.query(ProductPage).filter(ProductPage.project_id == project.id).first()
        blocker_count = 0
        major_count = 0
        warning_count = 0
        
        if page:
            compliance = PageComplianceChecker.inspect_page(db, page)
            for issue in compliance.get("issues", []):
                sev = issue.get("severity")
                if sev == "Blocker":
                    blocker_count += 1
                elif sev == "Major":
                    major_count += 1
                elif sev == "Warning":
                    warning_count += 1
                    
        total_issues = blocker_count + major_count + warning_count
        category_stats[cat]["total_issues"] += total_issues
        category_stats[cat]["blocker_count"] += blocker_count
        category_stats[cat]["major_count"] += major_count
        category_stats[cat]["warning_count"] += warning_count
        
        project_list.append({
            "id": project.id,
            "name": project.name,
            "category": project.category,
            "status": project.status,
            "current_step": project.current_step,
            "created_at": project.created_at,
            "updated_at": project.updated_at,
            "ai_jobs": {
                "count": project_ai_count,
                "total_cost": project_ai_cost,
                "total_duration_ms": project_ai_duration,
                "last_status": last_ai_status
            },
            "export_jobs": {
                "count": project_export_count,
                "last_status": last_export_status
            },
            "issues": {
                "blocker": blocker_count,
                "major": major_count,
                "warning": warning_count
            }
        })
        
    # Calculate averages and rates
    ai_job_success_rate = 100.0
    ai_job_failure_rate = 0.0
    if total_ai_jobs > 0:
        ai_job_failure_rate = round((failed_ai_jobs / total_ai_jobs) * 100, 1)
        ai_job_success_rate = round(100.0 - ai_job_failure_rate, 1)
        
    average_ai_duration_seconds = 0.0
    if total_ai_jobs > 0:
        average_ai_duration_seconds = round((total_ai_duration_ms / total_ai_jobs) / 1000.0, 1)
        
    export_job_success_rate = 100.0
    export_job_failure_rate = 0.0
    if total_export_jobs > 0:
        export_job_failure_rate = round((failed_export_jobs / total_export_jobs) * 100, 1)
        export_job_success_rate = round(100.0 - export_job_failure_rate, 1)
        
    average_export_duration_seconds = 0.0
    if completed_export_count > 0:
        average_export_duration_seconds = round(total_export_duration_seconds / completed_export_count, 1)
        
    # Add average issues per project in category stats
    for cname, cdata in category_stats.items():
        p_count = cdata["project_count"]
        cdata["average_issues_per_project"] = round(cdata["total_issues"] / p_count, 2) if p_count > 0 else 0.0

    return {
        "summary": {
            "total_projects": len(projects),
            "total_ai_jobs": total_ai_jobs,
            "ai_job_success_rate": ai_job_success_rate,
            "ai_job_failure_rate": ai_job_failure_rate,
            "average_ai_duration_seconds": average_ai_duration_seconds,
            "total_ai_cost": round(total_ai_cost, 4),
            "total_export_jobs": total_export_jobs,
            "export_job_success_rate": export_job_success_rate,
            "export_job_failure_rate": export_job_failure_rate,
            "average_export_duration_seconds": average_export_duration_seconds
        },
        "category_stats": category_stats,
        "projects": project_list
    }


@router.post("/seed", status_code=status.HTTP_201_CREATED)
def seed_operations_data(
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    user = auth_ctx["user"]
    workspace = auth_ctx["workspace"]
    
    # Get active brand for the workspace
    brand = db.query(Brand).filter(Brand.workspace_id == workspace.id).first()
    if not brand:
        # Create a default brand if it doesn't exist
        brand = Brand(
            id="00000000-0000-0000-0000-000000000003",
            workspace_id=workspace.id,
            name="Default Brand",
            brand_colors={"primary": "#4F46E5", "secondary": "#10B981"},
            font_tone="modern",
            default_disclaimer="본 상품은 100% 정품이며 정식 세관 검사를 거쳤습니다."
        )
        db.add(brand)
        db.commit()
        db.refresh(brand)
        
    brand_id = brand.id
    
    # Realistic Seed Data Definitions
    seed_projects = [
        # =====================================================================
        # FASHION (3 projects)
        # =====================================================================
        {
            "name": "천연 소가죽 클래식 로퍼",
            "category": "Fashion",
            "status": "ready",
            "current_step": "export",
            "raw_input_text": "중국 공장에서 직접 공수한 수제 클래식 남성 로퍼. 천연 소가죽 소재로 발이 편안합니다.",
            "facts": [
                {"text": "소재: 천연 소가죽 100%", "status": "confirmed", "source": "공장 스펙 시트"},
                {"text": "색상: 클래식 블랙, 다크 브라운", "status": "confirmed", "source": "공장 사진"},
                {"text": "굽높이: 3cm 아웃솔 포함", "status": "confirmed", "source": "실측 실사"},
                {"text": "제조국: 대한민국 공작소 OEM", "status": "confirmed", "source": "소싱 계약서"}
            ],
            "assets": [
                {"filename": "leather_loafer_main.jpg", "type": "sourced", "size": 154200, "path": "/uploads/mocks/leather_loafer_main.jpg"},
                {"filename": "leather_loafer_detail.jpg", "type": "self_shot", "size": 240500, "path": "/uploads/mocks/leather_loafer_detail.jpg"}
            ],
            "ai_runs": [
                {"provider": "openai", "model": "gpt-4o", "duration": 11500, "cost": 0.045, "status": "success"}
            ],
            "exports": [
                {"preset": "coupang", "status": "completed", "duration": 5200}
            ],
            "publication": {"slug": "leather-loafers", "store_url": "https://coupang.com/vp/products/loafers-classic"},
            "sections": [
                {"type": "header", "title": "클래식의 정석, 천연 소가죽 수제 로퍼", "body": "천연 소가죽 100% 소재로 신을수록 내 발에 꼭 맞춰지는 착화감을 느껴보세요."},
                {"type": "features", "title": "부드럽고 튼튼한 100% 천연 가죽 소재", "body": "인조 가죽과 비교할 수 없는 고급스러운 광택과 자연스러운 주름이 멋을 더합니다."},
                {"type": "specifications", "title": "상품 상세 사양", "body": "소재: 천연 소가죽 100% | 굽높이: 3cm | 색상: 블랙, 브라운"}
            ]
        },
        {
            "name": "기능성 쿨링 드라이 반팔 티셔츠",
            "category": "Fashion",
            "status": "checking", # Compliance issues!
            "current_step": "facts_verification",
            "raw_input_text": "아웃도어 필수 기능성 드라이 티셔츠. 땀이 즉시 마르는 쿨스킨 소재. 100% 안전하고 물이 빠지거나 변색이 절대 없습니다.",
            "facts": [
                {"text": "소재 정보 누락: 태그 부착 안 됨", "status": "needs_revision", "source": "샘플 검사"},
                {"text": "특징: 100% 안전하고 영구 탈색 절대 없음", "status": "needs_revision", "source": "공급처 광고 카피"}
            ],
            "assets": [
                {"filename": "cooling_tshirt.jpg", "type": "sourced", "size": 95000, "path": "/uploads/mocks/cooling_tshirt.jpg"}
            ],
            "ai_runs": [
                {"provider": "google", "model": "gemini-1.5-flash", "duration": 8200, "cost": 0.008, "status": "success"}
            ],
            "exports": [],
            "publication": None,
            "sections": [
                {"type": "header", "title": "땀 흘리는 여름을 위한 극강의 기능성 쿨링 티셔츠", "body": "입는 순간 시원한 감촉과 함께 100% 안전하고 절대 변색되지 않는 고성능 원단을 경험해 보세요."},
                {"type": "features", "title": "빠른 땀 흡수와 강력한 건조 능력", "body": "특수 드라이 원단 구조로 아웃도어 스포츠나 야외 활동 시 항상 쾌적함을 유지합니다."}
            ]
        },
        {
            "name": "빈티지 워싱 데님 자켓",
            "category": "Fashion",
            "status": "draft",
            "current_step": "raw_input",
            "raw_input_text": "소싱 진행 중인 빈티지 워싱 블루 데님 아우터 자켓.",
            "facts": [],
            "assets": [],
            "ai_runs": [
                {"provider": "anthropic", "model": "claude-3-5-sonnet", "duration": 4800, "cost": 0.0, "status": "failed", "error": "Connection timeout to AI provider"}
            ],
            "exports": [],
            "publication": None,
            "sections": []
        },
        # =====================================================================
        # BEAUTY (3 projects)
        # =====================================================================
        {
            "name": "유기농 병풀 시카 진정 세럼",
            "category": "Beauty",
            "status": "ready",
            "current_step": "export",
            "raw_input_text": "청정 제주산 유기농 병풀 추출물 85% 함유 시카 세럼. 자극받은 피부 장벽을 진정시킵니다. 용량 50ml. 개봉 후 12개월 사용 권장.",
            "facts": [
                {"text": "용량: 50ml", "status": "confirmed", "source": "용기 라벨 인쇄"},
                {"text": "전성분: 병풀추출물 85%, 정제수, 글리세린, 부틸렌글라이콜 등", "status": "confirmed", "source": "박스 패키지 고시"},
                {"text": "사용기한: 제조일로부터 24개월, 개봉 후 12개월", "status": "confirmed", "source": "라벨 각인"}
            ],
            "assets": [
                {"filename": "cica_serum_main.jpg", "type": "sourced", "size": 182000, "path": "/uploads/mocks/cica_serum_main.jpg"},
                {"filename": "cica_texture.jpg", "type": "self_shot", "size": 310000, "path": "/uploads/mocks/cica_texture.jpg"}
            ],
            "ai_runs": [
                {"provider": "openai", "model": "gpt-4o", "duration": 12800, "cost": 0.052, "status": "success"}
            ],
            "exports": [
                {"preset": "smartstore", "status": "completed", "duration": 6500}
            ],
            "publication": {"slug": "cica-serum", "store_url": "https://smartstore.naver.com/beauty-cica-serum"},
            "sections": [
                {"type": "header", "title": "피부 장벽 무너짐에 마침표, 유기농 병풀 시카 세럼", "body": "정제수 대신 청정 제주 유기농 병풀 추출물을 가득 담아 예민한 피부를 빠르게 다독여줍니다."},
                {"type": "features", "title": "병풀 유효 성분 85%의 고농축 시카 진정 케어", "body": "외부 자극과 스트레스로 울긋불긋해진 민감성 피부에 순하고 끈적임 없는 수분 진정막을 형성합니다."},
                {"type": "specifications", "title": "화장품 전성분 및 안내", "body": "용량: 50ml | 주요 성분: 병풀 추출물 85% | 사용기한: 개봉 후 12개월"}
            ]
        },
        {
            "name": "비타민 C 브라이트닝 크림",
            "category": "Beauty",
            "status": "checking", # Compliance blockers!
            "current_step": "facts_verification",
            "raw_input_text": "영국산 프리미엄 순수 비타민C 20% 함유 얼굴 크림. 아토피 환자의 여드름 균을 100% 사멸하며 피부를 완벽히 치료하고 맑게 가꾸어줍니다.",
            "facts": [
                {"text": "효능: 완벽히 치료하고 아토피 환자의 여드름 균을 100% 사멸함", "status": "needs_revision", "source": "중국 소싱처 설명서"}
            ],
            "assets": [
                {"filename": "vit_c_cream.jpg", "type": "sourced", "size": 140000, "path": "/uploads/mocks/vit_c_cream.jpg"}
            ],
            "ai_runs": [
                {"provider": "openai", "model": "gpt-4o", "duration": 9600, "cost": 0.041, "status": "success"}
            ],
            "exports": [
                {"preset": "coupang", "status": "failed", "duration": 1500}
            ],
            "publication": None,
            "sections": [
                {"type": "header", "title": "피부 톤업을 위한 프리미엄 비타민 C 20% 크림", "body": "지친 피부에 순수 비타민 에너지를 급속 충전하여 아토피 환자 등 극민감성 트러블 피부의 여드름 균을 100% 사멸 및 완벽히 치료해 줍니다."}
            ]
        },
        {
            "name": "울트라 모이스처 립밤",
            "category": "Beauty",
            "status": "checking", # Missing ingredients blocker!
            "current_step": "facts_verification",
            "raw_input_text": "보습력이 매우 강력한 립밤. 용량 5g.",
            "facts": [
                {"text": "용량: 5g", "status": "unknown", "source": "라벨"}
            ],
            "assets": [],
            "ai_runs": [
                {"provider": "openai", "model": "gpt-4o-mini", "duration": 5800, "cost": 0.002, "status": "success"}
            ],
            "exports": [],
            "publication": None,
            "sections": [
                {"type": "header", "title": "메마른 입술을 위한 하루 종일 촉촉한 울트라 립밤", "body": "보습 성분들이 촉촉하고 생기 넘치는 입술을 장시간 유지해줍니다."}
            ]
        },
        # =====================================================================
        # FOOD (3 projects)
        # =====================================================================
        {
            "name": "NFC 유기농 100% 착즙 사과즙",
            "category": "Food",
            "status": "ready",
            "current_step": "export",
            "raw_input_text": "경북 영주 100% 사과 착즙즙. 물 한 방울 넣지 않은 NFC 공법 가공. 보관은 서늘한 실온 또는 냉장 보관. 밀/메밀 혼유 제조 시설 생산.",
            "facts": [
                {"text": "원재료: 유기농 사과 99.9%, 비타민C 0.1%", "status": "confirmed", "source": "식품 검사 필증"},
                {"text": "보관방법: 서늘한 실온 보관 또는 냉장 보관", "status": "confirmed", "source": "제품 박스"},
                {"text": "알레르기 유발 정보: 메밀 및 밀 혼유 제조 시설에서 가공", "status": "confirmed", "source": "HACCP 서류"}
            ],
            "assets": [
                {"filename": "apple_juice_main.jpg", "type": "sourced", "size": 112000, "path": "/uploads/mocks/apple_juice_main.jpg"}
            ],
            "ai_runs": [
                {"provider": "openai", "model": "gpt-4o", "duration": 11200, "cost": 0.048, "status": "success"}
            ],
            "exports": [
                {"preset": "coupang", "status": "completed", "duration": 5100}
            ],
            "publication": {"slug": "apple-juice", "store_url": "https://coupang.com/vp/products/applejuice-organic"},
            "sections": [
                {"type": "header", "title": "물 타지 않은 진짜 생(生) 사과즙 100%", "body": "경북 영주 사과를 물 한 방울, 색소 한 방울 섞지 않고 통째로 NFC 저온 압착하여 영양과 맛을 그대로 담았습니다."},
                {"type": "features", "title": "영양 성분을 그대로 살린 NFC 비가열 착즙 공법", "body": "고온 가열하지 않고 그대로 지그시 눌러 짜내어 사과 고유의 비타민C와 새콤달콤한 향이 가득 살아 숨 쉽니다."},
                {"type": "specifications", "title": "식품 영양 및 고시 정보", "body": "원재료: 국내산 사과 99.9% | 보관방법: 서늘한 실온 보관 | 알레르기 안내: 본 제품은 메밀 및 밀 혼유 제조 시설에서 제조되었습니다."}
            ]
        },
        {
            "name": "기력 충전 보양 장어즙",
            "category": "Food",
            "status": "checking", # Medical claims blocker!
            "current_step": "facts_verification",
            "raw_input_text": "국내산 민물장어 추출물 80% 함유 건강즙. 고혈압과 당뇨 예방 및 완벽 치료 특효약이며 만병통치약급 피로회복 직빵 효능 보유.",
            "facts": [
                {"text": "효능: 고혈압과 당뇨에 효과가 있는 만병통치약이며 피로회복 직빵", "status": "needs_revision", "source": "소싱 카탈로그"}
            ],
            "assets": [
                {"filename": "eel_extract.jpg", "type": "sourced", "size": 220000, "path": "/uploads/mocks/eel_extract.jpg"}
            ],
            "ai_runs": [
                {"provider": "anthropic", "model": "claude-3-5-sonnet", "duration": 13500, "cost": 0.082, "status": "success"}
            ],
            "exports": [],
            "publication": None,
            "sections": [
                {"type": "header", "title": "지치고 기력 없을 때, 국내산 민물 장어 보양즙", "body": "몸에 좋은 보양 장어를 아낌없이 가득 고아 낸 건강한 한 포. 고혈압 당뇨 완벽 치료의 특효약이며 만병통치약이자 피로회복 직빵인 건강 식품입니다."}
            ]
        },
        {
            "name": "무농약 건조 표고버섯",
            "category": "Food",
            "status": "draft",
            "current_step": "raw_input",
            "raw_input_text": "국내산 지리산 무농약 건 표고버섯 슬라이스.",
            "facts": [],
            "assets": [],
            "ai_runs": [],
            "exports": [],
            "publication": None,
            "sections": []
        },
        # =====================================================================
        # LIVING (3 projects)
        # =====================================================================
        {
            "name": "초강력 마그네틱 차량용 거치대",
            "category": "Living",
            "status": "ready",
            "current_step": "export",
            "raw_input_text": "송풍구 거치 타입 마그네틱 스마트폰 거치대. 네오디뮴 N52 자석 탑재. 재질 알루미늄 합금. 크기 50mm x 50mm. 흔들림 없음.",
            "facts": [
                {"text": "재질: 고급 알루미늄 합금 및 네오디뮴 N52 등급 자석", "status": "confirmed", "source": "제조사 서류"},
                {"text": "치수: 헤드 지름 50mm, 길이 50mm", "status": "confirmed", "source": "버니어캘리퍼스 측정 실사"}
            ],
            "assets": [
                {"filename": "magnetic_mount_main.jpg", "type": "sourced", "size": 89000, "path": "/uploads/mocks/magnetic_mount_main.jpg"},
                {"filename": "magnetic_mount_car.jpg", "type": "self_shot", "size": 178000, "path": "/uploads/mocks/magnetic_mount_car.jpg"}
            ],
            "ai_runs": [
                {"provider": "openai", "model": "gpt-4o", "duration": 8900, "cost": 0.038, "status": "success"}
            ],
            "exports": [
                {"preset": "smartstore", "status": "completed", "duration": 4800}
            ],
            "publication": {"slug": "magnetic-holder", "store_url": "https://smartstore.naver.com/living-car-mount"},
            "sections": [
                {"type": "header", "title": "비포장도로에서도 흔들림 없는 초강력 자석 스마트폰 거치대", "body": "우수한 고정력의 네오디뮴 N52 자석과 알루미늄 메탈 바디로 주행 중 떨어질 염려 없이 안전하게 사용하세요."},
                {"type": "features", "title": "초강력 N52 자석 6개 탑재의 강력한 흡착력", "body": "스마트폰을 가져다 대기만 하면 즉각 강력 결합되며 스마트폰 내비게이션 및 GPS 신호 방해 없이 작동합니다."},
                {"type": "specifications", "title": "거치대 상세 스펙 안내", "body": "재질: 알루미늄 합금, 네오디뮴 자석 | 규격: 50mm x 50mm | 구성품: 본체, 마그네틱 플레이트 2개"}
            ]
        },
        {
            "name": "친환경 무독성 아동용 식기 세트",
            "category": "Living",
            "status": "checking", # KC Cert missing blocker!
            "current_step": "facts_verification",
            "raw_input_text": "옥수수 전분 생분해 플라스틱 소재로 만든 친환경 무독성 어린이/아동용 식기. 식판, 대접, 숟가락, 젓가락 세트.",
            "facts": [
                {"text": "사용대상: 아동용/어린이 식판 세트", "status": "confirmed", "source": "소싱 의뢰 스펙"}
            ],
            "assets": [
                {"filename": "kid_tableware.jpg", "type": "sourced", "size": 125000, "path": "/uploads/mocks/kid_tableware.jpg"}
            ],
            "ai_runs": [
                {"provider": "openai", "model": "gpt-4o", "duration": 9400, "cost": 0.042, "status": "success"}
            ],
            "exports": [],
            "publication": None,
            "sections": [
                {"type": "header", "title": "우리 아이를 위한 건강한 선택, 옥수수 생분해 아동용 식판 세트", "body": "옥수수 전분 친환경 소재로 100% 무독성이며 안심하고 밥을 줄 수 있는 어린이 전용 식기입니다."}
            ]
        },
        {
            "name": "다용도 실리콘 밀폐용기",
            "category": "Living",
            "status": "ready",
            "current_step": "export",
            "raw_input_text": "냉동실, 전자레인지, 오븐 모두 사용 가능한 100% 플래티넘 실리콘 용기. 용량 500ml. 타사 제품 100% 완벽 호환 절대 깨지지 않음.",
            "facts": [
                {"text": "재질: 100% 플래티넘 실리콘 식기용 등급", "status": "confirmed", "source": "SGS 시험 성적서"},
                {"text": "용량: 500ml", "status": "confirmed", "source": "실측 계량"},
                {"text": "특징: 100% 호환 및 절대 파손 없음", "status": "needs_revision", "source": "제조사 광고 문구"}
            ],
            "assets": [
                {"filename": "silicone_container.jpg", "type": "sourced", "size": 105000, "path": "/uploads/mocks/silicone_container.jpg"}
            ],
            "ai_runs": [
                {"provider": "openai", "model": "gpt-4o", "duration": 10200, "cost": 0.040, "status": "success"}
            ],
            "exports": [
                {"preset": "coupang", "status": "completed", "duration": 5300}
            ],
            "publication": {"slug": "silicone-container", "store_url": "https://coupang.com/vp/products/silicone-container-500ml"},
            "sections": [
                {"type": "header", "title": "오븐부터 냉동실까지 다용도 플래티넘 실리콘 용기", "body": "100% 순수 플래티넘 실리콘 재질로 고온에서도 환경호르몬 검출 걱정 없이 냉동, 냉장, 전자레인지까지 한 번에 활용하세요."},
                {"type": "features", "title": "환경호르몬 ZERO 안심 소재 실리콘", "body": "타사 뚜껑과 100% 호환되며 절대 파손되지 않아 유아 이유식 용기로도 추천합니다."}
            ]
        }
    ]
    
    # 2. Delete existing projects that match seed names (for idempotence)
    seed_names = [p["name"] for p in seed_projects]
    existing_seed_projects = db.query(ProductProject).filter(
        ProductProject.workspace_id == workspace.id,
        ProductProject.name.in_(seed_names)
    ).all()
    
    for ep in existing_seed_projects:
        db.delete(ep)
    db.commit()
    
    # 3. Insert new seed data
    for p_def in seed_projects:
        # Create Project
        project = ProductProject(
            workspace_id=workspace.id,
            brand_id=brand_id,
            name=p_def["name"],
            status=p_def["status"],
            current_step=p_def["current_step"],
            category=p_def["category"],
            category_confirmed=True if p_def["status"] != "draft" else False,
            category_confirmed_by=user.id if p_def["status"] != "draft" else None,
            category_confirmed_at=datetime.datetime.utcnow() if p_def["status"] != "draft" else None,
            raw_input_text=p_def["raw_input_text"]
        )
        db.add(project)
        db.flush() # Populate project.id
        
        # Create Assets
        assets_map = {}
        for a_def in p_def["assets"]:
            asset = Asset(
                project_id=project.id,
                source_type=a_def["type"],
                filename=a_def["filename"],
                file_path=a_def["path"],
                mime_type="image/jpeg",
                file_size=a_def["size"]
            )
            db.add(asset)
            db.flush()
            assets_map[a_def["filename"]] = asset.id
            
        # Create Facts
        facts_list = []
        for f_def in p_def["facts"]:
            fact = ProductFact(
                project_id=project.id,
                fact_text=f_def["text"],
                source_text=f_def["source"],
                verification_status=f_def["status"]
            )
            db.add(fact)
            db.flush()
            facts_list.append(fact)
            
        # Create AI Runs (AiJobLog & JobStatus)
        for r_def in p_def["ai_runs"]:
            ai_log = AiJobLog(
                project_id=project.id,
                task_type="fact_extraction",
                provider=r_def["provider"],
                model_name=r_def["model"],
                prompt_version="1.0.0",
                duration_ms=r_def["duration"],
                input_tokens=1500 if r_def["status"] == "success" else None,
                output_tokens=800 if r_def["status"] == "success" else None,
                estimated_cost=r_def["cost"] if r_def["status"] == "success" else 0.0,
                status=r_def["status"],
                error_message=r_def.get("error"),
                created_at=datetime.datetime.utcnow() - datetime.timedelta(minutes=30)
            )
            db.add(ai_log)
            
        # Create JobStatus representing the last AI analysis job
        if p_def["ai_runs"]:
            last_run = p_def["ai_runs"][-1]
            job_status = JobStatus(
                project_id=project.id,
                status="completed" if last_run["status"] == "success" else "failed",
                error_message=last_run.get("error")
            )
            db.add(job_status)
            
        # Create Page Draft and Page Sections
        if p_def["sections"]:
            page = ProductPage(
                project_id=project.id,
                theme_color="#4F46E5" if p_def["category"] == "Fashion" else ("#10B981" if p_def["category"] == "Beauty" else ("#EF4444" if p_def["category"] == "Food" else "#3B82F6")),
                font_family="sans-serif"
            )
            db.add(page)
            db.flush()
            
            for idx, sec_def in enumerate(p_def["sections"]):
                # Map some fact IDs to association
                assoc_ids = []
                if sec_def["type"] == "specifications" and facts_list:
                    assoc_ids = [f.id for f in facts_list if f.verification_status == "confirmed"]
                    
                # Link asset ID if header or features
                asset_id = None
                if sec_def["type"] in ["header", "features"] and list(assets_map.values()):
                    asset_id = list(assets_map.values())[0]
                    
                section = PageSection(
                    page_id=page.id,
                    section_type=sec_def["type"],
                    title=sec_def["title"],
                    body_copy=sec_def["body"],
                    associated_fact_ids=assoc_ids,
                    image_asset_id=asset_id,
                    sort_order=idx,
                    is_visible=True
                )
                db.add(section)
            db.flush()
            
            # Create Exports
            for e_def in p_def["exports"]:
                export_job = ExportJob(
                    project_id=project.id,
                    preset_name=e_def["preset"],
                    status=e_def["status"],
                    error_message="Blocker compliance issues must be resolved before export." if e_def["status"] == "failed" else None,
                    zip_asset_id=None,
                    output_images=["/uploads/exports/slide1.jpg", "/uploads/exports/slide2.jpg"] if e_def["status"] == "completed" else None,
                    created_by=user.id,
                    created_at=datetime.datetime.utcnow() - datetime.timedelta(minutes=15),
                    completed_at=datetime.datetime.utcnow() - datetime.timedelta(minutes=15) + datetime.timedelta(milliseconds=e_def["duration"]) if e_def["status"] == "completed" else datetime.datetime.utcnow() - datetime.timedelta(minutes=14)
                )
                db.add(export_job)
                
            # Create Publication
            if p_def["publication"] and page:
                pub = PublishedPage(
                    project_id=project.id,
                    page_id=page.id,
                    slug=p_def["publication"]["slug"],
                    is_active=True,
                    external_store_url=p_def["publication"]["store_url"],
                    config={"show_faq": True, "before_after_slider": {"enabled": False}, "video_url": None}
                )
                db.add(pub)
                
        # Write Audit Log
        audit_log = AuditLog(
            workspace_id=workspace.id,
            user_id=user.id,
            action="seed_project_created",
            entity_type="project",
            entity_id=project.id,
            payload={"name": project.name, "category": project.category, "status": project.status}
        )
        db.add(audit_log)
        
    db.commit()
    logger.info(f"Seeded 12 operations projects for workspace {workspace.id}.")
    
    return {
        "status": "seeded",
        "message": "Successfully seeded 12 realistic projects with job logs, compliance states, page drafts, and exports."
    }


@router.get("/generation-status")
def get_generation_status_dashboard(
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    workspace = auth_ctx["workspace"]
    return GenerationStatusService(db).get_workspace_status(workspace.id)


@router.get("/projects/{project_id}/generation-status")
def get_project_generation_status(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    workspace = auth_ctx["workspace"]
    try:
        return GenerationStatusService(db).get_project_status(project_id, workspace.id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
