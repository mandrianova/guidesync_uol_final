# GuideSync MVP Requirements and Constraints

## Goal

GuideSync should generate user-facing product documentation from product changes, browser evidence and screenshots. The output should be useful to ordinary users, not only to developers reviewing repository diffs.

## Functional Requirements

- Accept an incoming documentation task with run id, time window, repository list, target branch, UI URL and auth mode.
- Collect relevant product changes from the scoped repositories.
- Convert technical changes into user-facing release notes.
- Create a screenshot plan based on the user workflow affected by the change.
- Run the target UI in a browser automation session.
- Capture screenshots for the workflow steps.
- Generate a browsable guide artifact, not only a Markdown draft.
- Include step-by-step instructions, expected results and troubleshooting notes.
- Highlight the important UI fields, buttons and statuses in screenshots.
- Keep internal evidence, commit hashes and source file paths separate from the user guide.
- Store run outputs in a predictable folder structure so the result can be reviewed and regenerated.

## User Guide Requirements

- The primary user artifact should be HTML or another visual format that can be opened directly in a browser.
- The guide should have clear steps and short task-oriented copy.
- The guide must explain how to reach the target page from the UI, not only by route URL.
- Screenshots should be embedded close to the relevant step.
- Important controls should be visually called out with labels or highlight boxes.
- Private data in screenshots must be cropped, masked or replaced before publication.
- Missing screenshots must be clearly marked as pending instead of invented.
- The guide should include requirements, limitations and prerequisites.

## MVP Constraints

- The first iteration can use local filesystem outputs instead of a database.
- Browser capture can depend on a locally running UI.
- Auth tokens may be provided through environment variables only and must not be written to plans, logs or generated docs.
- The first version may generate static HTML rather than a fully interactive documentation portal.
- End-to-end service and artifact binding screenshots require safe test data and may remain pending until a test domain is available.

## Known Limitations

- Repository diffs do not always reveal the exact user journey, so browser validation is required.
- Existing chat history or workspace data can appear in screenshots unless masked or captured in a clean test account.
- UI routes may require role-specific access, which the agent must detect and report.
- DNS-related workflows cannot be fully validated without a domain that can safely be modified.
