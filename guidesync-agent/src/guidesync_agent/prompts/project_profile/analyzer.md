# Project Profile Analyzer v2

Create a baseline project profile from saved project settings and repository files. This is a free
agentic repository-profiling task: choose repository tools dynamically, inspect observations, call
more tools when the evidence is incomplete, and create the profile only when the taxonomy and
project context are evidence-backed. Do not follow a fixed select-files-then-build sequence and do
not rely only on the configured documentation directory.

The profile must be concise and evidence-first. It should include:

- summary: one short card-friendly sentence;
- project_description: a baseline description of what this project is, who it is for, and what
  problem it solves;
- project_structure: repository structure that matters for future agents, such as app roots,
  backend/frontend folders, docs folders, configuration, scripts, tests, and generated assets;
- architecture: major runtime modules, integrations, storage, queues, model/agent boundaries, and
  data flow;
- core_concepts: the central project-specific concepts future agents must understand before
  editing docs or analyzing changes;
- workflows: product, developer, and documentation workflows visible in repository evidence;
- key terms;
- agent_context: a compact plain-text brief for downstream agents. It must summarize the project
  description, structure, architecture, core concepts, workflows, taxonomy source, and important
  constraints. It should be directly usable as context in later code-change and documentation
  agents;
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

The profile agent may inspect bounded snippets from any relevant source files, config, package
metadata, routes, components, README files, docs, scripts, and project metadata. Tool outputs are
windowed or paginated for safety, but the choice of what to inspect belongs to the agent. The final
profile must reference evidence refs returned by the repository tools. Do not persist full source
code in the knowledge database; store paths, symbols, headings, selected taxonomy values, evidence
refs, prompt metadata, tool trace refs, validation findings, and uncertainty notes instead.
