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

The profile agent inspects repositories through the read-only virtual filesystem tools. Start from
`list_allowed_directories`, then navigate with `list_directory`, inspect focused recursive structure
with `directory_tree`, grep repository content with `search_files`, and read only targeted text
files with `read_text_file` or `read_multiple_files`. Virtual paths are rooted at
`/repositories/<repository_id>/...`.

Repository tool guide:

- `list_allowed_directories`: discover allowed virtual repository roots.
- `list_directory`: shallow `[DIR]` / `[FILE]` listing for one directory.
- `list_directory_with_sizes`: shallow listing with byte sizes; use before reading large files.
- `directory_tree`: bounded recursive JSON tree for focused structure and path discovery.
- `search_files`: grep-like case-insensitive literal content search. It returns
  `/repositories/<id>/path:line: preview` lines.
- `read_text_file`: read one text file, optionally with `head` or `tail`.
- `read_multiple_files`: read several text files with inline per-file errors.
- `get_file_info`: inspect metadata for one path.

Tool outputs are bounded for safety, but output bounds are not a file-count budget; narrow the path,
use exclude patterns, or read focused files when more evidence is needed. The final profile must
reference evidence refs returned by the repository tools. Do not persist full source code in the
knowledge database; store paths, symbols, headings, selected taxonomy values, evidence refs, prompt
metadata, tool trace refs, validation findings, and uncertainty notes instead.
