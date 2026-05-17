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

The dispatcher routes release tasks to `scripts/run_release_agent.sh`, which collects diffs, captures screenshots with Python Playwright, ranks announcement features, renders the Jinja HTML, writes localized outputs, and writes `agent-report.md`.

After the run, inspect the generated HTML, JSON payload, screenshot coverage and agent report. If the output is dry, technical, visually weak, missing screenshots, using wrong UI labels, or prioritizing features poorly, fix the inputs/templates/rules and rerun the relevant part. Do not report success solely because the script completed.

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

## Rules

- Do not expose secrets or private customer data.
- Do not expose code paths, commit hashes, internal feature names, or implementation details in the user-facing HTML.
- Use UI labels and product concepts instead of internal names. For example, prefer visible screen/button names over backend or filesystem terms.
- Match the guide language to the UI language. Use explicit input language first, then captured UI language signals.
- Write as a user release mailing: what changed, why it helps, where to find it, and a practical example.
- Separate confirmed facts from inferred impact.
- Keep release notes concise enough to guide screenshot planning.
- If a change is not user-visible, say so and recommend a different candidate.
