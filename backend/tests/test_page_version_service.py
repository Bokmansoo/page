try:
    from src.services.page_version_service import (
        create_page_version,
        restore_page_version,
        mark_final_version,
        list_page_versions,
    )
except ImportError:
    from backend.src.services.page_version_service import (
        create_page_version,
        restore_page_version,
        mark_final_version,
        list_page_versions,
    )


def test_create_and_restore_page_version():
    version = create_page_version(
        project_id="project-1",
        name="v1 문제 해결형 초안",
        sections=[
            {"key": "problem_statement", "title": "작은 불편", "body": "더운 날 외출이 번거롭습니다."},
        ],
        style_key="problem_solution",
    )

    restored = restore_page_version(version.id)

    assert restored.project_id == "project-1"
    assert restored.name == "v1 문제 해결형 초안"
    assert restored.sections[0]["key"] == "problem_statement"


def test_only_one_final_version_per_project():
    v1 = create_page_version("project-1", "v1", [], "problem_solution")
    v2 = create_page_version("project-1", "v2", [], "spec_focused")

    mark_final_version(v2.id)

    versions = list_page_versions("project-1")
    final_versions = [version for version in versions if version.is_final]

    assert len(final_versions) == 1
    assert final_versions[0].id == v2.id
