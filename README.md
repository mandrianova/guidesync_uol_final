# GuideSync Agent

An AI-orchestrated release communication assistant for web products, developed by
Margarita Andrianova for the University of London CM3070 final project.

GuideSync analyses repository changes, combines them with project context and
existing documentation, and prepares release notes for human review. The checked
report supports screenshots, PDF printing, and optional video with a transcript.
External publication remains a human decision.

## Start here

- [Application and setup](guidesync-agent/README.md)
- [Architecture](docs/architecture.md)
- [Final report](docs/report/index.html) — download the repository and open the HTML locally;
  GitHub's file viewer displays source, not a rendered page.
- [Questionnaire, rating matrices and aggregate results](docs/survey-results.md)
- [Example outputs](docs/examples/README.md)

## Structure

```text
guidesync-agent/   Final application: API, worker, React frontend, tests and migrations
guidesync-mvp/     Archived first prototype, retained to show development history
docs/             Architecture, evaluation, final report and PDF examples
```

The runtime uses FastAPI, Pydantic AI, React/Mantine, PostgreSQL, MinIO and
LocalStack SQS through Docker Compose. Pre-trained components include Gemma,
Nomic, spaCy and Kokoro. Sol was evaluated as an alternative LLM. Model weights,
private evaluation repositories, participant identities and videos are not bundled.

The report presents technical testing, observational model comparisons and
feedback from nine stakeholders. All nine rated report clarity and role usefulness
at 4–5/5 after demonstrations. These are perceived-value ratings, not measured
review-time savings or long-term adoption.
