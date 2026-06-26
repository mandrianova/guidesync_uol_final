# Project Profile Analyzer v2

Create a baseline project profile from saved project settings and locally cached repository
project files. Use bounded repository tools to inspect documentation, source paths, configuration,
and other relevant project files before deciding the taxonomy. Do not rely only on the configured
documentation directory.

The profile must be concise and evidence-first. It should include:

- summary;
- architecture;
- workflows;
- key terms;
- controlled taxonomy:
  - categories;
  - components/modules;
  - workflows/user journeys;
  - documentation areas;
  - domain terms;
  - aliases;
  - audience terminology;
  - bootstrap hints considered as selected, rejected, or candidates with reasons;
  - candidate terms that need later review;
- profile evidence refs for taxonomy decisions;
- repository map;
- source refs;
- warnings;
- uncertainty notes.

Do not invent product behavior that is not visible in the project settings or repository
files. Generic categories such as billing, auth, user-management, workspace, settings, api,
ui-workflow, release-notes, and docs are bootstrap hints only. Promote one into the controlled
taxonomy only when profile evidence supports it. If source material is missing, record an
uncertainty note instead.
