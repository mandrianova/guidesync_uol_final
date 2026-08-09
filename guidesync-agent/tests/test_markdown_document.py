from __future__ import annotations

from guidesync_agent.knowledge import markdown_sections
from guidesync_agent.services.documentation_editing_sections import replace_markdown_section
from guidesync_agent.services.knowledge_annotation import preprocess_markdown
from guidesync_agent.services.markdown_document import (
    render_markdown_html,
    split_markdown_sections,
)


def test_markdown_sections_ignore_headings_inside_fenced_code() -> None:
    markdown = "\n".join(
        [
            "# Overview",
            "Intro.",
            "",
            "```md",
            "# Not a real heading",
            "```",
            "",
            "## Details",
            "Use [domain settings](/domains) and ![Settings screenshot](settings.png).",
            "",
            "# Overview",
            "Second top section.",
        ]
    )

    sections = split_markdown_sections(markdown)

    assert [(section.title, section.start_line, section.end_line) for section in sections] == [
        ("Overview", 1, 7),
        ("Details", 8, 10),
        ("Overview", 11, 12),
    ]
    assert "# Not a real heading" in sections[0].text
    assert [section[0] for section in markdown_sections(markdown)] == [
        "Overview",
        "Details",
        "Overview",
    ]


def test_section_replacement_removes_duplicate_headings_without_matching_code_fences() -> None:
    markdown = (
        "# Guide\n\n"
        "```md\n## Highlights\n```\n\n"
        "## Highlights\n\n"
        "Old workflow notes.\n\n"
        "## Details\n\n"
        "Keep this section.\n\n"
        "## Highlights\n\n"
        "Duplicate generated notes.\n"
    )

    updated = replace_markdown_section(markdown, "Highlights", "## Highlights\n\nNew notes.")

    assert "```md\n## Highlights\n```" in updated
    assert "Keep this section." in updated
    assert "New notes." in updated
    assert "Old workflow notes." not in updated
    assert "Duplicate generated notes." not in updated


def test_markdown_preprocessing_uses_parser_signals() -> None:
    processed = preprocess_markdown(
        "# Billing settings\n\n"
        "```tsx\n# not a heading\nconst noisyImplementationDetail = true\n```\n\n"
        "Open [custom `domain`](/settings/domains) with ![Domain screen](domain.png).\n\n"
        "Use `ModelSettingsPage` for the model profile.\n"
    )

    assert processed.headings == ["Billing settings"]
    assert "not a heading" not in processed.headings
    assert "custom domain" in processed.link_labels
    assert "Domain screen" in processed.image_alt_texts
    assert "ModelSettingsPage" in processed.inline_code_terms
    assert "noisy implementation detail" in processed.code_identifier_terms
    assert "noisyImplementationDetail" not in processed.analysis_text


def test_report_markdown_renderer_handles_tables_code_and_raw_html() -> None:
    rendered = render_markdown_html(
        "# Report\n\n"
        "<script>alert(1)</script>\n\n"
        "```text\n# Not a heading\n```\n\n"
        "| Field | Value |\n"
        "| --- | --- |\n"
        "| Status | `ok` |\n"
    )

    assert "<h1>Report</h1>" in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    assert "# Not a heading" in rendered
    assert rendered.count("<h1>") == 1
    assert "<table>" in rendered
    assert "<code>ok</code>" in rendered
