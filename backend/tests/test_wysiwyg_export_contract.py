import os
import zipfile
from unittest.mock import patch

from src.api.exports import run_export_task
from src.db.models import (
    Brand,
    DetailPageVersion,
    ExportJob,
    ProductPage,
    ProductProject,
    User,
    Workspace,
)


def _create_project_with_page(db_session, project_id="export-project-id"):
    user = User(id=f"{project_id}-user", email=f"{project_id}@example.com", name="Export User")
    workspace = Workspace(id=f"{project_id}-ws", name="Export Workspace", owner_id=user.id)
    brand = Brand(id=f"{project_id}-brand", workspace_id=workspace.id, name="Export Brand")
    project = ProductProject(
        id=project_id,
        workspace_id=workspace.id,
        brand_id=brand.id,
        name="Export Product",
        category="Living",
    )
    page = ProductPage(id=f"{project_id}-page", project_id=project.id)
    db_session.add_all([user, workspace, brand, project, page])
    db_session.commit()
    return project, page, user


def _create_job(db_session, project_id, user_id):
    job = ExportJob(
        project_id=project_id,
        preset_name="smartstore",
        status="pending",
        created_by=user_id,
    )
    db_session.add(job)
    db_session.commit()
    return job


def test_export_task_fails_without_final_version_and_does_not_use_latest_draft(
    db_session,
    testing_session_local,
):
    project, page, user = _create_project_with_page(db_session)
    db_session.add(
        DetailPageVersion(
            project_id=project.id,
            name="Latest draft",
            style_key="minimal",
            sections_json={"sections": [{"title": "draft only"}]},
            is_final=False,
        )
    )
    job = _create_job(db_session, project.id, user.id)
    db_session.commit()

    with patch("src.api.exports.SessionLocal", testing_session_local), patch(
        "src.services.export_service.capture_next_render_export"
    ) as run_export:
        run_export_task(project.id, page.id, job.id, "smartstore")

    db_session.refresh(job)
    assert job.status == "failed"
    assert "Final detail page version not found" in job.error_message
    run_export.assert_not_called()


def test_export_task_uses_explicit_final_version_id(
    db_session,
    testing_session_local,
    tmp_path,
):
    project, page, user = _create_project_with_page(db_session, "explicit-final-project")
    draft = DetailPageVersion(
        project_id=project.id,
        name="Draft",
        style_key="minimal",
        sections_json={"sections": [{"title": "draft"}]},
        is_final=False,
    )
    final = DetailPageVersion(
        project_id=project.id,
        name="Final",
        style_key="minimal",
        sections_json={"sections": [{"title": "final"}]},
        is_final=True,
    )
    db_session.add_all([draft, final])
    job = _create_job(db_session, project.id, user.id)
    db_session.commit()

    # A newer final can be selected while this queued export is still pending.
    final.is_final = False
    db_session.add(
        DetailPageVersion(
            project_id=project.id,
            name="Newer final",
            style_key="minimal",
            sections_json={"sections": [{"title": "newer final"}]},
            is_final=True,
        )
    )
    db_session.commit()

    image_path = tmp_path / "final.png"
    zip_path = tmp_path / "final.zip"
    image_path.write_bytes(b"png")
    zip_path.write_bytes(b"zip")

    with patch("src.api.exports.SessionLocal", testing_session_local), patch(
        "src.services.export_service.capture_next_render_export",
        return_value={
            "long_vertical_image": os.fspath(image_path),
            "section_images_zip": os.fspath(zip_path),
        },
    ) as capture_export:
        run_export_task(
            project.id,
            page.id,
            job.id,
            "smartstore",
            final_version_id=final.id,
        )

    db_session.refresh(job)
    assert job.status == "completed"
    assert job.output_images
    assert capture_export.call_args.kwargs["version_id"] == final.id
    assert capture_export.call_args.kwargs["project_id"] == project.id
    assert capture_export.call_args.kwargs["auth_headers"] == {
        "X-Mock-User-Id": user.id,
        "X-Mock-Workspace-Id": project.workspace_id,
    }


def test_next_render_export_captures_exact_final_version(tmp_path):
    from src.services.export_service import capture_next_render_export

    events = []

    class FakeLocator:
        def __init__(self, name):
            self.name = name

        def screenshot(self, *, path, type, quality=None):
            events.append(("screenshot", self.name, type, quality))
            with open(path, "wb") as output:
                output.write(b"\x89PNG\r\n\x1a\n" if type == "png" else b"\xff\xd8\xff")

        def count(self):
            return 2

        def nth(self, index):
            return FakeLocator(f"section-{index}")

    class FakePage:
        def goto(self, url, *, wait_until, timeout):
            events.append(("goto", url, wait_until, timeout))

        def wait_for_selector(self, selector, *, state, timeout):
            events.append(("wait", selector, state, timeout))

        def locator(self, selector):
            events.append(("locator", selector))
            return FakeLocator(selector)

    class FakeBrowser:
        def new_page(self, **kwargs):
            events.append(("new_page", kwargs))
            return FakePage()

        def close(self):
            events.append(("close",))

    class FakeChromium:
        def launch(self, *, headless):
            events.append(("launch", headless))
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    result = capture_next_render_export(
        project_id="project-1",
        version_id="final-123",
        output_format="png",
        output_dir=os.fspath(tmp_path),
        render_base_url="http://127.0.0.1:3100",
        auth_headers={"X-Mock-User-Id": "user-1", "X-Mock-Workspace-Id": "ws-1"},
        playwright=FakePlaywright(),
    )

    goto_event = next(event for event in events if event[0] == "goto")
    assert "/workspace/projects/project-1/render?" in goto_event[1]
    assert "version_id=final-123" in goto_event[1]
    assert "user_id=user-1" in goto_event[1]
    assert "workspace_id=ws-1" in goto_event[1]
    assert ("wait", "html[data-export-ready='true']", "attached", 30000) in events
    assert os.path.exists(result["long_vertical_image"])
    with zipfile.ZipFile(result["section_images_zip"]) as archive:
        assert archive.namelist() == ["01-section.png", "02-section.png"]
