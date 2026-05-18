# Release Notes Skill

Use this skill after selecting a product diff.

## Purpose

Convert technical Git changes into concise release-note style content that ordinary users can read as a product update.

## Inputs

- incoming task JSON;
- selected repository/commit or time-window commit list;
- changed file list;
- relevant code snippets, if needed;
- optional task/issue context.
- UI language signal from input or captured Playwright evidence.

## Execution

For a complete release task, do not run stage scripts manually. From the CM3070 project root, use:

```bash
project/guidesync-mvp/scripts/run_task.sh project/guidesync-mvp/inputs/projects/<project-id>/release-task.json
```

The dispatcher routes release tasks to `scripts/run_release_agent.sh`, which collects commit/diff evidence, captures screenshots with Python Playwright, ranks announcement candidates, renders the Jinja HTML for publishable copy, writes localized outputs, writes `change-evidence.json`, and writes `agent-report.md`.

After the run, inspect `change-evidence.json`, the generated HTML, JSON payload, screenshot coverage and agent report. Treat the script as an evidence collector. If a change is marked `agent_required`, write the release copy from the evidence yourself or drop the candidate; do not publish a templated fallback card. If the output is dry, technical, visually weak, missing screenshots, using wrong UI labels, or prioritizing features poorly, fix the inputs/templates/rules and rerun the relevant part. Do not report success solely because the script completed.

## Outputs

Write `outputs/<run>/release-notes.md` or HTML release notes with:

- title;
- user-facing release summary in the same language as the product UI;
- affected product area;
- affected roles;
- affected workflows;
- practical examples of how ordinary users can try or apply the change;
- documentation impact hypothesis;
- uncertainty or missing context.

The script-produced evidence packet should preserve:

- commit subject and body;
- changed files and file stats;
- readable diff hints such as UI labels, button text, placeholders and product copy;
- inferred routes and product areas;
- capture status and screenshots when available.

## Rules

- Do not expose secrets or private customer data.
- Do not expose code paths, commit hashes, internal feature names, or implementation details in the user-facing HTML.
- Use UI labels and product concepts instead of internal names. For example, prefer visible screen/button names over backend or filesystem terms.
- Match the guide language to the UI language. Use explicit input language first, then captured UI language signals.
- Write as a user release mailing: what changed, why it helps, where to find it, and a practical example.
- Separate confirmed facts from inferred impact.
- Use commit and diff evidence as source material, but rewrite issue IDs, PR titles and implementation labels into product language.
- Keep release notes concise enough to guide screenshot planning.
- If a change is not user-visible, say so and recommend a different candidate.
