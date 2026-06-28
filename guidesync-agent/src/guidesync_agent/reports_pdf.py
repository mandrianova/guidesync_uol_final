from __future__ import annotations

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer

from guidesync_agent.reports import render_markdown
from guidesync_agent.schemas import GuideSyncRunResult
from guidesync_agent.services.markdown_document import (
    markdown_render_blocks,
    render_reportlab_inline,
)


def render_pdf(result: GuideSyncRunResult) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=result.request.report.title,
    )
    styles = pdf_styles()
    doc.build(markdown_flowables(render_markdown(result), styles))
    return buffer.getvalue()


def pdf_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "h1": ParagraphStyle(
            "GuideSyncHeading1",
            parent=base["Heading1"],
            fontSize=20,
            leading=24,
            spaceAfter=10,
            textColor=colors.HexColor("#142033"),
        ),
        "h2": ParagraphStyle(
            "GuideSyncHeading2",
            parent=base["Heading2"],
            fontSize=14,
            leading=18,
            spaceBefore=10,
            spaceAfter=6,
            textColor=colors.HexColor("#0f766e"),
        ),
        "h3": ParagraphStyle(
            "GuideSyncHeading3",
            parent=base["Heading3"],
            fontSize=11,
            leading=14,
            spaceBefore=8,
            spaceAfter=4,
            textColor=colors.HexColor("#142033"),
        ),
        "body": ParagraphStyle(
            "GuideSyncBody",
            parent=base["BodyText"],
            fontSize=9.5,
            leading=13,
            spaceAfter=5,
            textColor=colors.HexColor("#142033"),
        ),
        "bullet": ParagraphStyle(
            "GuideSyncBullet",
            parent=base["BodyText"],
            fontSize=9,
            leading=12,
            leftIndent=6,
            textColor=colors.HexColor("#142033"),
        ),
    }


def markdown_flowables(markdown: str, styles: dict[str, ParagraphStyle]) -> list[object]:
    flowables: list[object] = []
    bullet_lines: list[str] = []

    def flush_bullets() -> None:
        if bullet_lines:
            flowables.append(
                ListFlowable(
                    [
                        ListItem(Paragraph(inline_markdown(item), styles["bullet"]))
                        for item in bullet_lines
                    ],
                    bulletType="bullet",
                    start="bulletchar",
                    bulletFontName="Helvetica",
                    bulletFontSize=8,
                    leftIndent=12,
                )
            )
            flowables.append(Spacer(1, 2 * mm))
            bullet_lines.clear()

    for block in markdown_render_blocks(markdown):
        if block.kind == "heading":
            flush_bullets()
            flowables.append(Paragraph(block.reportlab_markup, styles[f"h{block.level}"]))
            continue
        if block.kind == "bullet":
            bullet_lines.append(block.reportlab_markup)
            continue
        flush_bullets()
        flowables.append(Paragraph(block.reportlab_markup, styles["body"]))
        flowables.append(Spacer(1, 2 * mm))

    flush_bullets()
    return flowables


def inline_markdown(value: str) -> str:
    return render_reportlab_inline(value)
