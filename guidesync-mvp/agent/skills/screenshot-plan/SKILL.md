# Screenshot Plan Skill

Use this skill after drafting release notes.

## Purpose

Create an ordered plan for browser navigation and screenshot capture.

## Inputs

- incoming task JSON;
- release notes;
- changed UI routes/files;
- existing or stale guide;
- auth mode and role.

## Outputs

Write `outputs/<run>/screenshot-plan.json` with:

- run id;
- UI URL;
- auth mode;
- target role;
- workflow goal;
- ordered steps;
- route hints;
- selectors when known;
- screenshot filename for each capture;
- expected UI text for validation;
- fallback/manual instructions.

Preferred command:

```bash
project/guidesync-mvp/scripts/create_screenshot_plan_stub.sh \
  project/guidesync-mvp/inputs/example-task-domains.json
```

Despite the historical script name, this now calls `guidesync-plan` and creates a reusable plan from `workflow.capture_steps` in the task JSON. If `capture_steps` is omitted, it falls back to a minimal plan from `ui.url` and `workflow.route_hint`.

## Step Shape

Each planned step should include:

```json
{
  "id": "step-01",
  "action": "navigate",
  "target": "http://localhost:3000",
  "expected": "Login page or authenticated app shell",
  "screenshot": "01-open-app.png",
  "notes": "Manual auth may be needed."
}
```

## Rules

- Prefer short workflows with 3-8 screenshots.
- Prefer stable selectors, `data-testid`, accessible roles/names, labels or route hints when available.
- Mark any step that requires manual auth or human input.
- Do not assume production data exists locally.
- Put task-specific navigation in the task JSON, not in scripts.
- Use `expected_text` for every page that can be validated without live data.
