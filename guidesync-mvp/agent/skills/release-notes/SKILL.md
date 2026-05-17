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
