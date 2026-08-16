from __future__ import annotations

import asyncio
import wave
from datetime import date
from pathlib import Path
from struct import pack
from threading import get_ident
from typing import cast

import pytest

from guidesync_agent.agent_runtime.video_presentation import video_plan_from_model_output
from guidesync_agent.controllers.run_artifacts import ArtifactPayload, load_stored_artifact
from guidesync_agent.reports import ArtifactContent
from guidesync_agent.schemas import (
    EvidenceBundle,
    GuideSyncRunRequest,
    GuideSyncRunResult,
    ProjectWorkflowTask,
    ProjectWorkflowTaskKind,
    PublicationChange,
    PublicationReport,
    PublicationScreenshotRef,
    ReportLocale,
    RepositoryInput,
    VideoAudioSegment,
    VideoPresentationModelOutput,
    VideoPresentationPlan,
    VideoPresentationPolicy,
    VideoPresentationSlide,
    VideoPresentationStatus,
    VideoPresentationSummary,
    VideoPresentationWorkflowInput,
)
from guidesync_agent.services.video.media import (
    VIDEO_FRAME_HEIGHT,
    VIDEO_FRAME_WIDTH,
    build_slide_segment_command,
)
from guidesync_agent.services.video.presentation import (
    VideoGenerationOutcome,
    enqueue_video_presentation,
    produce_video_artifacts_without_blocking,
    update_run_video_state,
    validate_presentation_duration,
)
from guidesync_agent.services.video.presentation_artifacts import (
    restore_slide_artifacts,
    video_publication_artifact_names,
)
from guidesync_agent.services.video.rendering import (
    PreparedSlideScreenshot,
    render_slide_html,
    slide_artifact_name,
    validate_slide_png,
)
from guidesync_agent.services.video.tts import TtsBatchResult, validate_audio_segment
from guidesync_agent.video_tts_cli import pcm16_bytes


def publication_report() -> PublicationReport:
    return PublicationReport(
        locale=ReportLocale.ENGLISH,
        product_name="Starlight",
        title="Starlight release notes",
        summary="Navigation and configuration are clearer.",
        user_value="The updated workflows are easier to understand.",
        release_date=date(2026, 8, 11),
        changes=[
            PublicationChange(
                id="change-menu",
                claim_id="claim-menu",
                title="Menu feedback",
                summary="The mobile menu shows its open state.",
                why_it_matters="People can see how to close it.",
                screenshots=[
                    PublicationScreenshotRef(
                        artifact_name="screenshot-menu-open-prepared.png",
                        scenario_id="menu-open",
                        caption="The open mobile menu.",
                        alt_text="Open Starlight mobile menu with a close icon.",
                        width=390,
                        height=844,
                    )
                ],
            ),
            PublicationChange(
                id="change-config",
                claim_id="claim-config",
                title="Configuration update",
                summary="Social links use an array configuration.",
                why_it_matters="Configuration is explicit and ordered.",
            ),
        ],
        call_to_action="Try the updated workflow.",
    )


def test_pcm16_conversion_accepts_sherpa_sample_lists() -> None:
    body = pcm16_bytes([-2.0, -1.0, 0.0, 0.5, 1.0, 2.0])

    assert len(body) == 12
    assert body[:2] == b"\x01\x80"
    assert body[-2:] == b"\xff\x7f"


def model_output(*, screenshot: str = "screenshot-menu-open-prepared.png"):
    return VideoPresentationModelOutput(
        slide_headlines=["Release overview", "Menu feedback", "Configuration update"],
        slide_bodies=[
            "Two user-facing workflows changed.",
            "The open state is now visible.",
            "Social links now use an ordered array.",
        ],
        slide_narrations=[
            "This release updates two documented workflows.",
            "On mobile, the menu now shows a close icon while it is open.",
            "Social link configuration now uses an explicit ordered array.",
        ],
        change_ids=["change-menu", "change-menu", "change-config"],
        claim_ids=["claim-menu", "claim-menu", "claim-config"],
        screenshot_artifact_names=["", screenshot, ""],
    )


def run_result(policy: VideoPresentationPolicy) -> GuideSyncRunResult:
    request = GuideSyncRunRequest(
        run_id="project-test-video-run",
        goal="Create release notes.",
        repositories=[RepositoryInput(name="repo", ref="HEAD")],
    )
    return GuideSyncRunResult(
        run_id=request.run_id,
        status="completed",
        request=request,
        evidence=EvidenceBundle(),
        video_presentation=VideoPresentationSummary(policy=policy),
    )


def test_video_plan_accepts_only_matching_publication_refs() -> None:
    plan = video_plan_from_model_output(
        "project-test-video-run",
        publication_report(),
        model_output(),
    )

    assert len(plan.slides) == 3
    assert plan.slides[1].screenshot_artifact_names == [
        "screenshot-menu-open-prepared.png"
    ]
    assert plan.slides[2].screenshot_artifact_names == []


def test_video_media_generation_runs_outside_async_worker_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = run_result(VideoPresentationPolicy.OPTIONAL)
    report = publication_report()
    plan = video_plan_from_model_output(run.run_id, report, model_output())
    task = ProjectWorkflowTask(
        project_id="project-test-video",
        kind=ProjectWorkflowTaskKind.VIDEO_PRESENTATION,
        input=VideoPresentationWorkflowInput(run_id=run.run_id),
    )
    event_loop_thread = get_ident()
    media_threads: list[int] = []
    expected = cast(VideoGenerationOutcome, object())

    def fake_produce_video_artifacts(*_args: object) -> VideoGenerationOutcome:
        media_threads.append(get_ident())
        return expected

    monkeypatch.setattr(
        "guidesync_agent.services.video.presentation.produce_video_artifacts",
        fake_produce_video_artifacts,
    )

    result = asyncio.run(
        produce_video_artifacts_without_blocking(
            task,
            run,
            report,
            plan,
            VideoPresentationSummary(
                policy=VideoPresentationPolicy.OPTIONAL,
                status=VideoPresentationStatus.RUNNING,
            ),
        )
    )

    assert result is expected
    assert media_threads and media_threads[0] != event_loop_thread


def test_video_plan_rejects_raw_or_unapproved_screenshot_ref() -> None:
    with pytest.raises(ValueError, match="not publication-approved"):
        video_plan_from_model_output(
            "project-test-video-run",
            publication_report(),
            model_output(screenshot="raw-worker-capture.png"),
        )


def test_video_plan_rejects_claim_mismatch() -> None:
    output = model_output().model_copy(
        update={"claim_ids": ["claim-menu", "invented-claim", "claim-config"]}
    )

    with pytest.raises(ValueError, match="does not match"):
        video_plan_from_model_output(
            "project-test-video-run",
            publication_report(),
            output,
        )


def test_video_plan_rejects_model_markup_or_remote_urls() -> None:
    output = model_output().model_copy(
        update={
            "slide_bodies": [
                "Two user-facing workflows changed.",
                '<img src="https://example.com/private.png">',
                "Social links now use an ordered array.",
            ]
        }
    )

    with pytest.raises(ValueError, match="plain text"):
        video_plan_from_model_output(
            "project-test-video-run",
            publication_report(),
            output,
        )


def test_text_only_slide_uses_full_width_controlled_template() -> None:
    slide = VideoPresentationSlide(
        id="slide-01",
        position=1,
        headline="Release overview",
        body="A concise overview without a screenshot.",
        narration="This release has a concise overview.",
        change_id="change-menu",
        claim_id="claim-menu",
    )

    rendered = render_slide_html(slide, publication_report(), None, 3)

    assert 'class="story text-only"' in rendered
    assert 'class="visual"' not in rendered
    assert "grid-template-columns: minmax(0, 1280px)" in rendered
    assert f"width: {VIDEO_FRAME_WIDTH}px; height: {VIDEO_FRAME_HEIGHT}px" in rendered
    assert "http://" not in rendered
    assert "https://" not in rendered


def test_screenshot_slide_uses_large_contained_prepared_visual() -> None:
    slide = VideoPresentationSlide(
        id="slide-02",
        position=2,
        headline="Menu feedback",
        body="The open state is now visible.",
        narration="The open state is now visible on mobile.",
        change_id="change-menu",
        claim_id="claim-menu",
        screenshot_artifact_names=["screenshot-menu-open-prepared.png"],
    )
    screenshot = PreparedSlideScreenshot(
        data_url="data:image/png;base64,cHJlcGFyZWQ=",
        caption="The prepared publication screenshot.",
        alt_text="Open mobile menu.",
    )

    rendered = render_slide_html(slide, publication_report(), screenshot, 3)

    assert 'class="story with-visual"' in rendered
    assert "minmax(820px, 1.28fr)" in rendered
    assert "height: 640px; object-fit: contain" in rendered
    assert screenshot.data_url in rendered


def test_resume_reuses_only_slide_with_matching_checkpoint_hash(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bodies: dict[str, bytes] = {}
    checkpoints = []
    artifacts = {}
    for position in range(1, 4):
        artifact_name = slide_artifact_name(position)
        body = bytearray(1_024)
        body[:8] = b"\x89PNG\r\n\x1a\n"
        body[16:24] = pack(">II", VIDEO_FRAME_WIDTH, VIDEO_FRAME_HEIGHT)
        body[-1] = position
        source = tmp_path / "source" / artifact_name
        source.parent.mkdir(exist_ok=True)
        source.write_bytes(body)
        bodies[artifact_name] = bytes(body)
        checkpoints.append(validate_slide_png(source))
        artifacts[artifact_name] = f"s3://bucket/{artifact_name}"
    run = run_result(VideoPresentationPolicy.OPTIONAL).model_copy(
        update={"artifacts": artifacts}
    )
    plan = VideoPresentationPlan(
        run_id=run.run_id,
        prompt_version="test",
        slides=[
            VideoPresentationSlide(
                id="slide-01",
                position=1,
                headline="Release overview",
                body="A concise overview.",
                narration="This is a concise release overview.",
                change_id="change-menu",
                claim_id="claim-menu",
            ),
            VideoPresentationSlide(
                id="slide-02",
                position=2,
                headline="Second update",
                body="A second concise update.",
                narration="This is the second concise update.",
                change_id="change-menu",
                claim_id="claim-menu",
            ),
            VideoPresentationSlide(
                id="slide-03",
                position=3,
                headline="Third update",
                body="A third concise update.",
                narration="This is the third concise update.",
                change_id="change-config",
                claim_id="claim-config",
            ),
        ],
    )
    monkeypatch.setattr(
        "guidesync_agent.services.video.presentation_artifacts.read_artifact",
        lambda uri: ArtifactContent(
            body=bodies[uri.rsplit("/", 1)[-1]],
            content_type="image/png",
        ),
    )

    restored = restore_slide_artifacts(run, plan, tmp_path / "restored", checkpoints)
    stale_checkpoints = [
        checkpoints[0].model_copy(update={"sha256": "0" * 64}),
        *checkpoints[1:],
    ]
    stale = restore_slide_artifacts(
        run,
        plan,
        tmp_path / "stale",
        stale_checkpoints,
    )

    assert set(restored) == set(artifacts)
    assert stale == {}


def test_ffmpeg_segment_command_uses_web_compatible_bounded_settings(tmp_path: Path) -> None:
    command = build_slide_segment_command(
        tmp_path / "slide.png",
        tmp_path / "audio.wav",
        tmp_path / "segment.mp4",
        12.4,
        0.4,
    )

    assert command[0] == "ffmpeg"
    assert "libx264" in command
    assert "aac" in command
    assert "yuv420p" in command
    video_filter = command[command.index("-vf") + 1]
    assert (
        f"scale={VIDEO_FRAME_WIDTH}:{VIDEO_FRAME_HEIGHT}:flags=lanczos:"
        "force_original_aspect_ratio=decrease"
    ) in video_filter
    assert f"pad={VIDEO_FRAME_WIDTH}:{VIDEO_FRAME_HEIGHT}" in video_filter
    assert command[command.index("-crf") + 1] == "18"
    assert command[command.index("-t") + 1] == "12.400"
    assert "apad=pad_dur=0.400" in command


def test_wav_validation_records_non_empty_duration(tmp_path: Path) -> None:
    path = tmp_path / "video-narration-01.wav"
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(b"\x00\x00" * 8_000)

    segment = validate_audio_segment(path, "slide-01")

    assert segment.duration_seconds == 0.5
    assert len(segment.sha256) == 64


def test_video_duration_is_bounded_before_ffmpeg() -> None:
    segment = VideoAudioSegment(
        slide_id="slide-01",
        artifact_name="video-narration-01.wav",
        duration_seconds=61,
        sha256="a" * 64,
    )
    tts = TtsBatchResult(
        backend_version="1.13.4",
        model="kokoro-en-v0_19",
        voice="bm_lewis",
        voice_id=10,
        speed=1,
        segments=[
            segment,
            segment.model_copy(update={"slide_id": "slide-02"}),
            segment.model_copy(update={"slide_id": "slide-03"}),
        ],
    )

    with pytest.raises(ValueError, match="exceeds"):
        validate_presentation_duration(tts)


def test_mp4_artifact_is_served_inline_for_public_player(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "guidesync_agent.controllers.run_artifacts.read_artifact",
        lambda _uri: ArtifactContent(body=b"video", content_type="video/mp4"),
    )

    artifact = load_stored_artifact("video-presentation.mp4", "s3://bucket/video.mp4")

    assert isinstance(artifact, ArtifactPayload)
    assert artifact.headers["Content-Disposition"].startswith("inline;")


def test_regeneration_uses_a_new_public_video_artifact_key() -> None:
    first = video_publication_artifact_names("workflow-first")
    regenerated = video_publication_artifact_names("workflow-regenerated")

    assert first.video == "video-presentation-workflow-first.mp4"
    assert regenerated.video != first.video
    assert regenerated.transcript != first.transcript
    assert regenerated.manifest != first.manifest


@pytest.mark.parametrize("policy", list(VideoPresentationPolicy)[1:])
def test_video_failure_does_not_change_published_report(
    monkeypatch: pytest.MonkeyPatch,
    policy: VideoPresentationPolicy,
) -> None:
    stored = run_result(policy).model_copy(
        update={
            "video_presentation": VideoPresentationSummary(
                policy=policy,
                status=VideoPresentationStatus.COMPLETED,
                video_artifact_name="video-presentation.mp4",
            )
        }
    )

    class FakeRunStore:
        def get(self, run_id: str):
            assert run_id == stored.run_id
            return stored

        def save(self, result: GuideSyncRunResult) -> None:
            nonlocal stored
            stored = result

        def record_run_event(self, *args) -> None:
            return None

    monkeypatch.setattr(
        "guidesync_agent.services.video.presentation.create_run_store",
        FakeRunStore,
    )

    update_run_video_state(
        stored.run_id,
        stored.video_presentation.model_copy(
            update={
                "status": VideoPresentationStatus.FAILED,
                "error_message": "TTS failed.",
            }
        ),
    )

    assert stored.status == "completed"
    assert stored.video_presentation.status is VideoPresentationStatus.FAILED
    assert stored.video_presentation.video_artifact_name == "video-presentation.mp4"
    assert stored.findings == []


def test_manual_video_enqueue_requires_publication_and_preserves_existing_video(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = run_result(VideoPresentationPolicy.DISABLED).model_copy(
        update={
            "video_presentation": VideoPresentationSummary(
                policy=VideoPresentationPolicy.OPTIONAL,
                status=VideoPresentationStatus.COMPLETED,
                video_artifact_name="video-presentation.mp4",
            )
        }
    )
    report: PublicationReport | None = None
    queued_tasks = []

    class FakeRunStore:
        def get(self, _run_id: str):
            return stored

        def get_publication_report(self, _run_id: str):
            return report

        def save(self, result: GuideSyncRunResult) -> None:
            nonlocal stored
            stored = result

        def record_run_event(self, *args) -> None:
            return None

    class FakeWorkflowStore:
        def enqueue(self, task):
            if queued_tasks:
                return queued_tasks[0]
            queued_tasks.append(task)
            return task

    monkeypatch.setattr(
        "guidesync_agent.services.video.presentation.create_run_store",
        FakeRunStore,
    )
    monkeypatch.setattr(
        "guidesync_agent.services.video.presentation.create_project_workflow_store",
        FakeWorkflowStore,
    )

    with pytest.raises(ValueError, match="ready publication report"):
        enqueue_video_presentation(stored.run_id, regenerate=True)

    report = publication_report()
    summary = enqueue_video_presentation(stored.run_id, regenerate=True)

    assert summary.status is VideoPresentationStatus.QUEUED
    assert summary.video_artifact_name == "video-presentation.mp4"
    assert stored.status == "completed"
    assert len(queued_tasks) == 1
    assert queued_tasks[0].depends_on_task_ids == []
    assert queued_tasks[0].input.regenerate is True

    repeated = enqueue_video_presentation(stored.run_id, regenerate=True)

    assert repeated.workflow_task_id == summary.workflow_task_id
    assert len(queued_tasks) == 1
