# Planned Implementation Structure

This directory documents the future software prototype. The source code itself should live under `src/` once implementation starts.

## Intended Package

```text
src/
├── pixel_to_patch/
│   ├── inputs/
│   ├── models/
│   ├── retrieval/
│   ├── grounding/
│   ├── orchestration/
│   ├── patches/
│   └── ui/
└── tests/
```

## Component Plan

| Component | Responsibility |
|---|---|
| `inputs/` | Load screenshots, text prompts and optional audio |
| `models/` | Wrap OCR, vision, embedding, reranker and LLM models |
| `retrieval/` | Index and search target repositories |
| `grounding/` | Add LSP/tree-sitter/code symbol evidence |
| `orchestration/` | Coordinate the end-to-end workflow |
| `patches/` | Generate, format and validate candidate patches |
| `ui/` | CLI/API/web interface |
| `tests/` | Unit and integration tests |

## First Prototype Target

The first prototype should support:

1. one screenshot input;
2. OCR extraction;
3. vision summary;
4. code retrieval over a small repository;
5. LLM explanation;
6. candidate fix or investigation path;
7. saved trace of intermediate outputs.

## Development Notes

- Start with a narrow target language and repository.
- Keep model wrappers replaceable.
- Save intermediate outputs for evaluation.
- Prefer deterministic evaluation scripts where possible.
- Treat generated patches as review suggestions, not automatic truth.
