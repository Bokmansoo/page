import os
import json
import zipfile

from PIL import Image

from src.services.channel_export_service import (
    create_channel_export_bundle,
    get_channel_preset,
    safe_split_heights,
)


def test_channel_presets_are_versioned_and_replaceable():
    coupang = get_channel_preset("coupang")
    smartstore = get_channel_preset("smartstore")

    assert coupang.version
    assert smartstore.version
    assert coupang.width > 0
    assert smartstore.max_segment_height > 0


def test_safe_split_prefers_section_boundaries_without_overlap_or_gap():
    ranges = safe_split_heights(1300, [300, 450, 550], 700)

    assert ranges == [(0, 300), (300, 750), (750, 1300)]
    assert ranges[0][0] == 0
    assert ranges[-1][1] == 1300
    assert all(previous[1] == current[0] for previous, current in zip(ranges, ranges[1:]))


def test_channel_bundle_keeps_master_content_and_packages_parts(tmp_path):
    master_path = tmp_path / "master.png"
    image = Image.new("RGB", (100, 1500), "white")
    for y, color in [(0, "red"), (500, "green"), (1000, "blue")]:
        image.paste(color, (0, y, 100, y + 500))
    image.save(master_path)
    image.close()

    bundle = create_channel_export_bundle(
        master_path=os.fspath(master_path), output_dir=os.fspath(tmp_path),
        project_slug="test", preset_key="coupang", output_format="png",
        section_heights=[500, 500, 500],
        generation_plan={"version": 2, "provider_mode": "api_not_connected", "scenes": [{"id": "hero", "mock_status": "generation_pending"}]},
    )

    assert os.path.isfile(bundle["long_image"])
    assert os.path.isfile(bundle["package_zip"])
    with Image.open(bundle["long_image"]) as rendered:
        assert rendered.width == get_channel_preset("coupang").width
        assert rendered.height == 12900
    assert bundle["manifest"]["parts"]
    with zipfile.ZipFile(bundle["package_zip"]) as archive:
        assert "manifest.json" in archive.namelist()
        assert bundle["manifest"]["master"] in archive.namelist()
        assert json.loads(archive.read("generation-plan.json"))["provider_mode"] == "api_not_connected"
