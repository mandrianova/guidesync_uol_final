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
  - taxonomy evidence refs for selected categories, components, workflows, documentation areas,
    domain terms, aliases, and bootstrap hints;
  - taxonomy confidence from 0.0 to 1.0;
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

The profile agent may inspect bounded snippets from source files, config, package metadata, routes,
components, README files, and docs. Do not persist full source code in the knowledge database; store
paths, symbols, headings, selected taxonomy values, evidence refs, prompt metadata, and uncertainty
notes instead.
