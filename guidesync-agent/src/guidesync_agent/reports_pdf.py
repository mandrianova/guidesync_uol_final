from __future__ import annotations

import html
import re
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer

from guidesync_agent.reports import render_markdown
from guidesync_agent.schemas import GuideSyncRunResult


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
    paragraph_lines: list[str] = []
    bullet_lines: list[str] = []

    def flush_paragraph() -> None:
        if paragraph_lines:
            flowables.append(Paragraph(inline_markdown(" ".join(paragraph_lines)), styles["body"]))
            flowables.append(Spacer(1, 2 * mm))
            paragraph_lines.clear()

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

    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            flush_paragraph()
            flush_bullets()
            continue
        if line.startswith("#"):
            flush_paragraph()
            flush_bullets()
            level = min(len(line) - len(line.lstrip("#")), 3)
            text = line[level:].strip()
            flowables.append(Paragraph(inline_markdown(text), styles[f"h{level}"]))
            continue
        if line.startswith("- ") or line.startswith("  - "):
            flush_paragraph()
            bullet_lines.append(line.removeprefix("- ").removeprefix("  - ").strip())
            continue
        flush_bullets()
        paragraph_lines.append(line)

    flush_paragraph()
    flush_bullets()
    return flowables


def inline_markdown(value: str) -> str:
    escaped = html.escape(value)
    escaped = re.sub(r"`([^`]+)`", r'<font name="Courier">\1</font>', escaped)
    return re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", escaped)
