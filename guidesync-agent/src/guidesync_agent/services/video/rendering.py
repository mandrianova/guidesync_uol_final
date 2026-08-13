from __future__ import annotations

# ruff: noqa: E501 - controlled slide CSS stays readable as complete declarations.
import base64
import hashlib
import html
import struct
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import sync_playwright

from guidesync_agent.reports import read_artifact
from guidesync_agent.schemas import (
    PublicationReport,
    VideoPresentationPlan,
    VideoPresentationSlide,
    VideoSlideArtifact,
)
from guidesync_agent.settings import get_settings
from guidesync_agent.storage import create_run_store

SLIDE_WIDTH = 1280
SLIDE_HEIGHT = 720


@dataclass(frozen=True)
class PreparedSlideScreenshot:
    data_url: str
    caption: str
    alt_text: str


def render_video_slides(
    plan: VideoPresentationPlan,
    report: PublicationReport,
    output_dir: Path,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    required_screenshots = {
        artifact_name
        for slide in plan.slides
        for artifact_name in slide.screenshot_artifact_names
    }
    screenshots = publication_screenshot_lookup(
        plan.run_id,
        report,
        required_screenshots,
    )
    rendered: dict[str, Path] = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=settings.browser.binary,
        )
        try:
            page = browser.new_page(
                viewport={"width": SLIDE_WIDTH, "height": SLIDE_HEIGHT},
                device_scale_factor=1,
            )
            for slide in plan.slides:
                screenshot = slide_screenshot(slide, screenshots)
                page.set_content(
                    render_slide_html(slide, report, screenshot, len(plan.slides)),
                    wait_until="load",
                    timeout=settings.video_presentation.render_timeout_ms,
                )
                page.evaluate("document.fonts.ready")
                page.locator("[data-video-slide]").wait_for(state="visible")
                if screenshot is not None and not page.locator(".visual img").evaluate(
                    "image => image.complete && image.naturalWidth > 0 && image.naturalHeight > 0"
                ):
                    raise ValueError(
                        f"Prepared screenshot did not decode for video slide {slide.position}."
                    )
                output_path = output_dir / slide_artifact_name(slide.position)
                page.screenshot(
                    path=str(output_path),
                    full_page=False,
                    animations="disabled",
                )
                validate_slide_png(output_path)
                rendered[output_path.name] = output_path
        finally:
            browser.close()
    return rendered


def publication_screenshot_lookup(
    run_id: str,
    report: PublicationReport,
    required_names: set[str] | None = None,
) -> dict[str, PreparedSlideScreenshot]:
    store = create_run_store()
    result: dict[str, PreparedSlideScreenshot] = {}
    for change in report.changes:
        for screenshot in change.screenshots:
            if required_names is not None and screenshot.artifact_name not in required_names:
                continue
            uri = store.get_artifact_uri(run_id, screenshot.artifact_name)
            if uri is None:
                raise ValueError(
                    f"Prepared publication screenshot is not registered: {screenshot.artifact_name}"
                )
            artifact = read_artifact(uri)
            if not artifact.content_type.startswith("image/") or not artifact.body:
                raise ValueError(
                    f"Prepared publication screenshot is not a decodable image: "
                    f"{screenshot.artifact_name}"
                )
            encoded = base64.b64encode(artifact.body).decode("ascii")
            result[screenshot.artifact_name] = PreparedSlideScreenshot(
                data_url=f"data:{artifact.content_type};base64,{encoded}",
                caption=screenshot.caption,
                alt_text=screenshot.alt_text,
            )
    return result


def slide_screenshot(
    slide: VideoPresentationSlide,
    screenshots: dict[str, PreparedSlideScreenshot],
) -> PreparedSlideScreenshot | None:
    if not slide.screenshot_artifact_names:
        return None
    artifact_name = slide.screenshot_artifact_names[0]
    screenshot = screenshots.get(artifact_name)
    if screenshot is None:
        raise ValueError(
            f"Video slide screenshot is outside the publication allowlist: {artifact_name}"
        )
    return screenshot


def render_slide_html(
    slide: VideoPresentationSlide,
    report: PublicationReport,
    screenshot: PreparedSlideScreenshot | None,
    slide_count: int,
) -> str:
    visual_class = "with-visual" if screenshot is not None else "text-only"
    image = ""
    if screenshot is not None:
        image = (
            '<figure class="visual">'
            f'<img src="{screenshot.data_url}" alt="{html.escape(screenshot.alt_text)}">'
            f"<figcaption>{html.escape(screenshot.caption)}</figcaption>"
            "</figure>"
        )
    progress = "".join(
        f'<span class="tick{(" active" if position == slide.position else "")}"></span>'
        for position in range(1, slide_count + 1)
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><style>
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; width: {SLIDE_WIDTH}px; height: {SLIDE_HEIGHT}px; overflow: hidden; }}
body {{ background: #f4f7f6; color: #10273d; font-family: Inter, "Segoe UI", Arial, sans-serif; }}
.slide {{ width: 100%; height: 100%; padding: 54px 66px 46px; display: grid; grid-template-rows: auto 1fr auto; gap: 34px; }}
.masthead {{ display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid #cbd9d6; padding-bottom: 18px; }}
.product {{ font-size: 17px; font-weight: 750; letter-spacing: .02em; }}
.date {{ color: #537083; font: 14px ui-monospace, SFMono-Regular, Menlo, monospace; text-transform: uppercase; letter-spacing: .08em; }}
.story {{ display: grid; align-items: center; gap: 52px; min-height: 0; }}
.story.with-visual {{ grid-template-columns: minmax(0, 1fr) minmax(420px, .92fr); }}
.story.text-only {{ grid-template-columns: minmax(0, 900px); align-content: center; }}
.copy {{ max-width: 760px; }}
.eyebrow {{ color: #087f77; font: 700 14px ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .12em; text-transform: uppercase; margin: 0 0 19px; }}
h1 {{ font-size: 54px; line-height: 1.04; letter-spacing: -.035em; margin: 0 0 24px; text-wrap: balance; }}
.body {{ color: #405e70; font-size: 25px; line-height: 1.43; margin: 0; text-wrap: pretty; }}
.visual {{ margin: 0; background: #fff; border: 1px solid #c6d5d2; padding: 12px; box-shadow: 0 18px 45px rgba(16,39,61,.10); }}
.visual img {{ display: block; width: 100%; height: 360px; object-fit: contain; background: #eef2f1; }}
.visual figcaption {{ color: #537083; font-size: 14px; line-height: 1.35; margin: 10px 4px 1px; }}
.footer {{ display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: 20px; }}
.counter {{ color: #087f77; font: 700 14px ui-monospace, SFMono-Regular, Menlo, monospace; }}
.rail {{ display: flex; gap: 7px; }}
.tick {{ background: #cedbd8; height: 3px; flex: 1; }} .tick.active {{ background: #087f77; }}
.claim {{ color: #6a8290; font: 12px ui-monospace, SFMono-Regular, Menlo, monospace; }}
</style></head><body><main class="slide" data-video-slide>
<header class="masthead"><div class="product">{html.escape(report.product_name)}</div><div class="date">{report.release_date.strftime("%d %B %Y")}</div></header>
<section class="story {visual_class}"><div class="copy"><p class="eyebrow">Release notes</p><h1>{html.escape(slide.headline)}</h1><p class="body">{html.escape(slide.body)}</p></div>{image}</section>
<footer class="footer"><span class="counter">{slide.position:02d} / {slide_count:02d}</span><div class="rail">{progress}</div><span class="claim">{html.escape(slide.claim_id)}</span></footer>
</main></body></html>"""


def slide_artifact_name(position: int) -> str:
    return f"video-slide-{position:02d}.png"


def validate_slide_png(path: Path) -> VideoSlideArtifact:
    body = path.read_bytes()
    if len(body) < 1_024 or not body.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError(f"Rendered slide is blank or not a PNG: {path.name}")
    width, height = struct.unpack(">II", body[16:24])
    if (width, height) != (SLIDE_WIDTH, SLIDE_HEIGHT):
        raise ValueError(f"Rendered slide has unexpected dimensions {width}x{height}: {path.name}")
    position = int(path.stem.rsplit("-", 1)[-1])
    return VideoSlideArtifact(
        slide_id=f"slide-{position:02d}",
        artifact_name=path.name,
        sha256=hashlib.sha256(body).hexdigest(),
    )
