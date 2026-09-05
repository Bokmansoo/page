"""LG-16-A5 common MP4 assembly over the durable A4 scene clips."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import threading
from uuid import uuid4
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.config import settings
from src.db.models import AgentRun, Asset, ImageGenerationJobRecord
from src.services.prompt_intelligence_service import canonical_hash
from src.services.video_scene_generation_service import (
    _current_video,
    _latest_jobs,
    _scene_identity,
    _scene_rows,
)
from src.services.video_project_version_service import finalize_video_project_version


VIDEO_ASSEMBLY_SCHEMA_VERSION = "lg16-video-assembly-v1"
VIDEO_ASSEMBLY_PROFILE_ID = "common_shortform_mp4"
VIDEO_ASSEMBLY_PROFILE_VERSION = 1
VIDEO_ASSEMBLY_TARGETS = ["reels", "tiktok", "youtube_shorts"]
_CLIP_STATUSES = frozenset({"needs_review", "approved", "completed"})
_QUALITY_PASS = "PASS"
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


class VideoAssemblyError(ValueError):
    """Bounded A5 failure; raw FFmpeg diagnostics never enter persistence."""


def _temp_dir_parent() -> str:
    # Keep disposable media beside the configured runtime storage.  This also
    # avoids Windows pytest temp ACLs while remaining outside the repository's
    # tracked source tree in normal deployments.
    parent = Path(settings.UPLOAD_DIR).resolve() / ".video-tmp"
    parent.mkdir(parents=True, exist_ok=True)
    return str(parent)


def _run(db: Session, run_id: str, project_id: str) -> AgentRun:
    run = db.query(AgentRun).filter_by(id=run_id, project_id=project_id).one_or_none()
    if run is None:
        raise VideoAssemblyError("VIDEO_RUN_NOT_FOUND")
    return run


def _ffmpeg(binary: str) -> str:
    value = shutil.which(binary)
    if not value:
        raise VideoAssemblyError("FFMPEG_UNAVAILABLE")
    return value


def _probe(path: Path) -> dict[str, Any]:
    try:
        probe = _ffmpeg("ffprobe")
        result = subprocess.run(
            [probe, "-v", "error", "-show_entries", "format=duration:stream=codec_name,width,height,codec_type", "-of", "json", str(path)],
            check=False, capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            raise VideoAssemblyError("VIDEO_MEDIA_PROBE_FAILED")
        data = json.loads(result.stdout or "{}")
    except (OSError, ValueError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        raise VideoAssemblyError("VIDEO_MEDIA_PROBE_FAILED") from exc
    streams = [item for item in list(data.get("streams") or []) if isinstance(item, dict) and item.get("codec_type") == "video"]
    if not streams:
        raise VideoAssemblyError("VIDEO_VIDEO_STREAM_MISSING")
    stream = streams[0]
    try:
        duration = float(dict(data.get("format") or {}).get("duration") or 0)
        width, height = int(stream.get("width") or 0), int(stream.get("height") or 0)
    except (TypeError, ValueError) as exc:
        raise VideoAssemblyError("VIDEO_MEDIA_PROBE_INVALID") from exc
    if duration <= 0 or width <= 0 or height <= 0:
        raise VideoAssemblyError("VIDEO_MEDIA_PROBE_INVALID")
    return {"duration_seconds": duration, "width": width, "height": height, "codec_name": str(stream.get("codec_name") or "")}


def _clip_rows(db: Session, run: AgentRun, video: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    storyboard, raw_scenes = _scene_rows(video)
    scenes = sorted(raw_scenes, key=lambda item: int(item.get("order") or 0))
    orders = [int(item.get("order") or 0) for item in scenes]
    if orders != list(range(1, len(scenes) + 1)):
        raise VideoAssemblyError("VIDEO_STORYBOARD_ORDER_INVALID")
    jobs = _latest_jobs(db, run.id, run.project_id)
    rows: list[dict[str, Any]] = []
    video_ref = {"id": video.id, "version": int(video.version), "hash": str(video.canonical_hash)}
    generation_video = video
    final_ref = dict((video.video_manifest_json or {}).get("final_output_ref") or {})
    source_ref = dict(final_ref.get("source_video_project_ref") or {})
    if source_ref.get("id") and source_ref.get("id") != video.id:
        generation_video = db.query(type(video)).filter_by(
            id=source_ref["id"], workspace_id=run.workspace_id, project_id=run.project_id,
        ).one_or_none() or video
    storyboard_ref = {
        "id": str(storyboard.get("storyboard_id") or ""), "version": 1,
        "hash": str(storyboard.get("canonical_hash") or ""),
    }
    if not storyboard_ref["id"] or len(storyboard_ref["hash"]) != 64:
        raise VideoAssemblyError("VIDEO_STORYBOARD_REF_INVALID")
    for scene in scenes:
        scene_id = str(scene.get("scene_id") or "")
        job = jobs.get(scene_id)
        if job is None or str(job.status) not in _CLIP_STATUSES or not job.output_asset_id:
            raise VideoAssemblyError("VIDEO_CLIP_NOT_READY")
        snapshot = dict(job.input_snapshot or {}).get("video_generation")
        expected_generation_ref = {"id": generation_video.id, "version": int(generation_video.version), "hash": str(generation_video.canonical_hash)}
        current_ref = {"id": video.id, "version": int(video.version), "hash": str(video.canonical_hash)}
        if isinstance(snapshot, Mapping) and snapshot.get("video_project_ref") == current_ref:
            job_generation_video = video
        elif isinstance(snapshot, Mapping) and snapshot.get("video_project_ref") == expected_generation_ref:
            job_generation_video = generation_video
        else:
            job_generation_video = None
        if job_generation_video is None or snapshot.get("storyboard_ref") != storyboard_ref or str(snapshot.get("scene_id") or "") != scene_id:
            raise VideoAssemblyError("VIDEO_CLIP_STALE")
        expected_hash = canonical_hash(_scene_identity(job_generation_video, storyboard, scene, int(job.generation_attempt or 1)))
        if str(job.idempotency_key or "") != expected_hash:
            raise VideoAssemblyError("VIDEO_CLIP_STALE")
        asset = db.query(Asset).filter_by(id=job.output_asset_id, project_id=run.project_id).one_or_none()
        if asset is None or asset.mime_type != "video/mp4" or not asset.file_path:
            raise VideoAssemblyError("VIDEO_CLIP_ASSET_INVALID")
        path = Path(asset.file_path)
        if not path.is_file() or path.stat().st_size <= 0:
            raise VideoAssemblyError("VIDEO_CLIP_ASSET_MISSING")
        media = _probe(path)
        content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if str(asset.content_hash or "") != content_hash:
            raise VideoAssemblyError("VIDEO_CLIP_HASH_MISMATCH")
        rows.append({
            "scene_id": scene_id,
            "asset": asset,
            "asset_ref": {"id": asset.id, "version": 1, "hash": content_hash},
            "content_hash": content_hash,
            **media,
        })
    geometries = {(item["width"], item["height"]) for item in rows}
    if len(geometries) != 1:
        raise VideoAssemblyError("VIDEO_CLIP_GEOMETRY_MISMATCH")
    return {"video_project_ref": video_ref, "storyboard_ref": storyboard_ref}, rows


def _identity(video: Any, storyboard: Mapping[str, Any], rows: list[dict[str, Any]]) -> str:
    return canonical_hash({
        "schema_version": VIDEO_ASSEMBLY_SCHEMA_VERSION,
        "storyboard_hash": str(storyboard["storyboard_ref"]["hash"]),
        "ordered_scene_ids": [str(item["scene_id"]) for item in rows],
        "selected_clip_refs": [{"scene_id": item["scene_id"], "asset_id": item["asset"].id, "content_hash": item["content_hash"]} for item in rows],
        "profile_id": VIDEO_ASSEMBLY_PROFILE_ID,
        "profile_version": VIDEO_ASSEMBLY_PROFILE_VERSION,
        "media_contract": {"container": "video/mp4", "audio": "silent_allowed", "captions": "none"},
    })


def _thumbnail_asset(db: Session, project_id: str, final_asset: Asset) -> Asset:
    """Extract one deterministic first frame; no provider or raw diagnostics persist."""
    filename = f"ai_generated/video_thumbnail_{str(final_asset.content_hash)[:32]}.png"
    output_path = Path(settings.UPLOAD_DIR) / filename
    existing = db.query(Asset).filter_by(project_id=project_id, filename=filename, asset_role="video_thumbnail").one_or_none()
    if existing is not None:
        if existing.content_hash and output_path.is_file() and hashlib.sha256(output_path.read_bytes()).hexdigest() == str(existing.content_hash):
            return existing
        raise VideoAssemblyError("VIDEO_THUMBNAIL_HASH_MISMATCH")
    source_path = Path(str(final_asset.file_path))
    if not source_path.is_file():
        source_path = Path(settings.UPLOAD_DIR) / source_path
    if not source_path.is_file():
        raise VideoAssemblyError("VIDEO_OUTPUT_MISSING")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(_temp_dir_parent()) / f"thumbnail-{uuid4().hex}.png"
    try:
        ffmpeg = _ffmpeg("ffmpeg")
        result = subprocess.run(
            [ffmpeg, "-y", "-v", "error", "-i", str(source_path), "-frames:v", "1", str(temporary)],
            check=False, capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0 or not temporary.is_file() or temporary.stat().st_size <= 0:
            raise VideoAssemblyError("VIDEO_THUMBNAIL_FAILED")
        content = temporary.read_bytes()
        content_hash = hashlib.sha256(content).hexdigest()
        output_path.write_bytes(content)
        asset = Asset(
            project_id=project_id, source_type="ai_generated", usage_status="blocked", filename=filename,
            file_path=str(output_path), mime_type="image/png", file_size=len(content), asset_role="video_thumbnail",
            quality_status="accepted", identity_status="passed", width=final_asset.width, height=final_asset.height,
            image_format="png", content_hash=content_hash,
        )
        db.add(asset)
        db.flush()
        return asset
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VideoAssemblyError("VIDEO_THUMBNAIL_FAILED") from exc
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _manifest(video_refs: dict[str, Any], rows: list[dict[str, Any]], assembly_hash: str, *, final_asset: Asset | None = None, output: dict[str, Any] | None = None) -> dict[str, Any]:
    geometry = {"width": rows[0]["width"], "height": rows[0]["height"]}
    result = {
        "schema_version": VIDEO_ASSEMBLY_SCHEMA_VERSION,
        "status": "completed" if final_asset is not None else "started",
        "video_project_ref": video_refs["video_project_ref"],
        "storyboard_ref": video_refs["storyboard_ref"],
        "scene_count": len(rows),
        "ordered_scene_ids": [item["scene_id"] for item in rows],
        "selected_clip_refs": [
            {"scene_id": item["scene_id"], "asset_ref": item["asset_ref"], "content_hash": item["content_hash"], "duration_seconds": item["duration_seconds"], "width": item["width"], "height": item["height"]}
            for item in rows
        ],
        "profile": {"profile_id": VIDEO_ASSEMBLY_PROFILE_ID, "profile_version": VIDEO_ASSEMBLY_PROFILE_VERSION, "container": "video/mp4", "audio_policy": "silent_allowed", "caption_policy": "none", "geometry_policy": "require_equal_geometry"},
        "assembly_hash": assembly_hash,
        "final_asset_ref": {"id": final_asset.id, "version": 1, "hash": str(final_asset.content_hash)} if final_asset is not None else None,
        "duration_seconds": float(output["duration_seconds"]) if output else None,
        "geometry": dict(output.get("geometry") or geometry) if output else geometry,
        "output_hash": str(output["output_hash"]) if output else None,
        "quality_verdict": str(output["quality_verdict"]) if output else None,
        "common_targets": list(VIDEO_ASSEMBLY_TARGETS),
    }
    result["manifest_hash"] = canonical_hash({key: value for key, value in result.items() if key != "manifest_hash"})
    return result


def _render(paths: list[Path], output: Path) -> dict[str, Any]:
    listing = Path(_temp_dir_parent()) / f"concat-{uuid4().hex}.txt"
    try:
        ffmpeg = _ffmpeg("ffmpeg")
        listing.write_text("\n".join(f"file '{str(path.resolve()).replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'" for path in paths), encoding="utf-8")
        result = subprocess.run(
            [ffmpeg, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(output)],
            check=False, capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0 or not output.is_file() or output.stat().st_size <= 0:
            raise VideoAssemblyError("VIDEO_FFMPEG_FAILED")
        return _probe(output)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VideoAssemblyError("VIDEO_FFMPEG_FAILED") from exc
    finally:
        try:
            listing.unlink(missing_ok=True)
        except OSError:
            pass


@contextmanager
def _semantic_lock(db: Session, key: str):
    bind = db.get_bind()
    if getattr(bind.dialect, "name", "") == "postgresql":
        lock_bind = bind if hasattr(bind, "connect") else getattr(bind, "engine", None)
        if lock_bind is None:
            raise VideoAssemblyError("VIDEO_ASSEMBLY_LOCK_UNAVAILABLE")
        connection = lock_bind.connect()
        try:
            connection.execute(text("SELECT pg_advisory_lock(hashtext(:key))"), {"key": key})
            connection.commit()
            yield
        finally:
            try:
                connection.execute(text("SELECT pg_advisory_unlock(hashtext(:key))"), {"key": key})
                connection.commit()
            finally:
                connection.close()
    else:
        with _LOCKS_GUARD:
            lock = _LOCKS.setdefault(key, threading.Lock())
        with lock:
            yield


def assemble_common_video(*, run_id: str, project_id: str, db: Session) -> dict[str, Any]:
    """Assemble current, quality-eligible scene clips into one common MP4."""

    run = _run(db, run_id, project_id)
    video = _current_video(db, run)
    video_refs, rows = _clip_rows(db, run, video)
    storyboard = {"storyboard_ref": video_refs["storyboard_ref"]}
    assembly_hash = _identity(video, storyboard, rows)
    key = f"lg16-video-assembly:{project_id}:{assembly_hash}"
    with _semantic_lock(db, key):
        db.expire_all()
        run = _run(db, run_id, project_id)
        video = _current_video(db, run)
        video_refs, rows = _clip_rows(db, run, video)
        storyboard = {"storyboard_ref": video_refs["storyboard_ref"]}
        assembly_hash = _identity(video, storyboard, rows)
        filename = f"ai_generated/video_final_{assembly_hash[:32]}.mp4"
        projected = dict((run.outputs_json or {}).get("langgraph_video_assembly") or {})
        existing = db.query(Asset).filter_by(project_id=project_id, filename=filename, mime_type="video/mp4").one_or_none()
        if projected.get("assembly_hash") == assembly_hash and projected.get("final_asset_ref") and existing is not None:
            return projected

        finalized_ref = dict((video.video_manifest_json or {}).get("final_output_ref") or {})
        if finalized_ref.get("assembly_hash") == assembly_hash and existing is not None and str(existing.id) == str(finalized_ref.get("id")) and str(existing.content_hash) == str(finalized_ref.get("hash")):
            final = _manifest(video_refs, rows, assembly_hash, final_asset=existing, output={"duration_seconds": _probe(Path(existing.file_path))["duration_seconds"], "geometry": {"width": existing.width, "height": existing.height}, "output_hash": existing.content_hash, "quality_verdict": _QUALITY_PASS})
            from src.services.langgraph_run_service import AgentRunEventJournal
            AgentRunEventJournal.append_video_assembly(run, db, event_type="video_assembly_completed", video=video_refs, assembly=final)
            db.commit()
            return final

        from src.services.langgraph_run_service import AgentRunEventJournal

        started = _manifest(video_refs, rows, assembly_hash)
        AgentRunEventJournal.append_video_assembly(run, db, event_type="video_assembly_started", video=video_refs, assembly=started)
        db.commit()

        try:
            output_path = Path(settings.UPLOAD_DIR) / filename
            output_path.parent.mkdir(parents=True, exist_ok=True)
            if existing is None:
                rendered_path = Path(_temp_dir_parent()) / f"final-{uuid4().hex}.mp4"
                try:
                    output = _render([Path(item["asset"].file_path) for item in rows], rendered_path)
                    content = rendered_path.read_bytes()
                    output_path.write_bytes(content)
                finally:
                    try:
                        rendered_path.unlink(missing_ok=True)
                    except OSError:
                        pass
            else:
                output = _probe(Path(existing.file_path))
                content = Path(existing.file_path).read_bytes()
            output_hash = hashlib.sha256(content).hexdigest()
            if output["width"] != rows[0]["width"] or output["height"] != rows[0]["height"]:
                raise VideoAssemblyError("VIDEO_OUTPUT_GEOMETRY_INVALID")
            expected_duration = sum(float(item["duration_seconds"]) for item in rows)
            if abs(float(output["duration_seconds"]) - expected_duration) > max(0.05, expected_duration * 0.05):
                raise VideoAssemblyError("VIDEO_OUTPUT_DURATION_MISMATCH")
            if existing is None:
                existing = Asset(
                    project_id=project_id, source_type="ai_generated", usage_status="blocked", filename=filename,
                    file_path=str(output_path), mime_type="video/mp4", file_size=len(content), asset_role="video_final",
                    quality_status="accepted", identity_status="passed", width=int(output["width"]), height=int(output["height"]),
                    image_format="mp4", content_hash=output_hash,
                )
                db.add(existing)
                db.flush()
            elif str(existing.content_hash or "") != output_hash:
                raise VideoAssemblyError("VIDEO_OUTPUT_HASH_MISMATCH")
            thumbnail = _thumbnail_asset(db, project_id, existing)
            finalized = finalize_video_project_version(
                db, parent=video, final_asset=existing, thumbnail_asset=thumbnail,
                assembly_hash=assembly_hash, profile_id=VIDEO_ASSEMBLY_PROFILE_ID,
                profile_version=VIDEO_ASSEMBLY_PROFILE_VERSION,
            )
            final_video_refs = dict(video_refs)
            final_video_refs["video_project_ref"] = {"id": str(finalized.id), "version": int(finalized.version), "hash": str(finalized.canonical_hash)}
            final = _manifest(final_video_refs, rows, assembly_hash, final_asset=existing, output={"duration_seconds": output["duration_seconds"], "geometry": {"width": output["width"], "height": output["height"]}, "output_hash": output_hash, "quality_verdict": _QUALITY_PASS})
            AgentRunEventJournal.append_video_assembly(run, db, event_type="video_assembly_completed", video=final_video_refs, assembly=final)
            db.commit()
            return final
        except VideoAssemblyError as exc:
            db.rollback()
            failed = _manifest(video_refs, rows, assembly_hash)
            failed["status"] = "failed"
            AgentRunEventJournal.append_video_assembly(run, db, event_type="video_assembly_failed", video=video_refs, assembly=failed)
            db.commit()
            raise exc
        except Exception as exc:
            db.rollback()
            failed = _manifest(video_refs, rows, assembly_hash)
            failed["status"] = "failed"
            AgentRunEventJournal.append_video_assembly(run, db, event_type="video_assembly_failed", video=video_refs, assembly=failed)
            db.commit()
            raise VideoAssemblyError("VIDEO_ASSEMBLY_FAILED") from exc


assemble_video = assemble_common_video
