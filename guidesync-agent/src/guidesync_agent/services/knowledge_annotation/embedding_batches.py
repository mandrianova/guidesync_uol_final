from __future__ import annotations

from collections.abc import Sequence

from .models import SemanticRankingRequest

EMBEDDING_ENDPOINT_MAX_BATCH_INPUTS = 256


def embedding_request_batches(
    requests: Sequence[tuple[int, SemanticRankingRequest]],
) -> list[list[tuple[int, SemanticRankingRequest]]]:
    batches: list[list[tuple[int, SemanticRankingRequest]]] = []
    current: list[tuple[int, SemanticRankingRequest]] = []
    current_inputs: set[str] = set()
    current_context: tuple[str | None, str | None, str | None] | None = None
    for request_index, request in requests:
        request_context = (
            request.project_id,
            request.run_id,
            request.workflow_task_id,
        )
        request_inputs = {request.text, *request.candidates}
        exceeds_limit = len(current_inputs | request_inputs) > EMBEDDING_ENDPOINT_MAX_BATCH_INPUTS
        context_changed = current_context is not None and request_context != current_context
        if current and (exceeds_limit or context_changed):
            batches.append(current)
            current = []
            current_inputs = set()
        current.append((request_index, request))
        current_inputs.update(request_inputs)
        current_context = request_context
    if current:
        batches.append(current)
    return batches


def split_embedding_requests(
    requests: Sequence[SemanticRankingRequest],
) -> list[tuple[int, SemanticRankingRequest]]:
    work_items: list[tuple[int, SemanticRankingRequest]] = []
    max_candidates = EMBEDDING_ENDPOINT_MAX_BATCH_INPUTS - 1
    for request_index, request in enumerate(requests):
        for start in range(0, len(request.candidates), max_candidates):
            work_items.append(
                (
                    request_index,
                    request.model_copy(
                        update={
                            "candidates": request.candidates[
                                start : start + max_candidates
                            ]
                        }
                    ),
                )
            )
    return work_items
