# GuideSync Persistence Notes

Persistence is intentionally deferred until after the first end-to-end MVP run.

For the first run, store artifacts as files:

- incoming task JSON;
- release notes markdown;
- screenshot plan JSON;
- screenshots;
- browser capture JSON;
- guide update markdown;
- change report markdown;
- evaluation notes.

SQLite can be added after the first run once the useful data shape is clearer.

## Candidate Data To Store Later

- incoming tasks;
- agent runs;
- scoped repositories;
- selected commits/diffs;
- release-note summaries;
- screenshot plans;
- screenshot metadata;
- browser capture evidence;
- documentation targets;
- generated guide updates;
- human-review decisions;
- evaluation scores.

## Deferred Questions

- Is the database only a local run index, or part of the agent product?
- Should screenshots be stored as files with DB metadata, or as blobs?
- Should generated docs be versioned through Git rather than SQLite?
- Which fields are useful for evaluation and reproducibility?
