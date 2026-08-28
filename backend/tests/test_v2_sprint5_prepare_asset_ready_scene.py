from src.services.storyboard_image_generation_service import prepare_storyboard_jobs

from test_v2_sprint5_ai_redesign import _project


def test_explicit_redesign_preparation_includes_asset_ready_visual_scene(db_session, tmp_path):
    project, _reference = _project(db_session, tmp_path)
    project.planning_draft["cards"][0]["image_requirement"] = "asset_ready"
    db_session.commit()

    jobs = prepare_storyboard_jobs(project, db_session)

    assert len(jobs) == 1
    assert {job["section_type"] for job in jobs} == {"hero"}
    assert {job["status"] for job in jobs} == {"awaiting_approval"}
