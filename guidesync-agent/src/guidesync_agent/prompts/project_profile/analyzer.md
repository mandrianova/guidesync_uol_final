# Project Profile Analyzer v2

Create a baseline project profile from saved project settings and repository files. This is an
agentic repository-profiling task: first use the file listing to decide which files and searches
are worth inspecting, then create the profile only from the selected repository evidence. Do not
rely only on the configured documentation directory.

The profile must be concise and evidence-first. It should include:

- summary;
- architecture;
- workflows;
- key terms;
- controlled taxonomy, generated from this repository rather than from a template:
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

Do not invent product behavior that is not visible in the project settings or repository files.
Do not start from generic SaaS/product categories. A category, component, workflow, documentation
area, domain term, alias, or audience term is valid only when repository evidence supports it. If
source material is missing or weak, record an uncertainty note instead.

The profile agent may inspect bounded snippets from source files, config, package metadata, routes,
components, README files, docs, scripts, and project metadata. The final profile must reference
evidence refs returned by the repository tools. Do not persist full source code in the knowledge
database; store paths, symbols, headings, selected taxonomy values, evidence refs, prompt metadata,
tool trace refs, validation findings, and uncertainty notes instead.
