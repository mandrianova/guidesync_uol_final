from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from guidesync_agent.controllers import evaluations as controller
from guidesync_agent.schemas import (
    AblationComparisonReport,
    EvaluationComparisonPage,
    EvaluationComparisonRecord,
    EvaluationExperimentCreate,
    EvaluationExperimentPage,
    EvaluationExperimentRecord,
    EvaluationExperimentRun,
    EvaluationRunPage,
    EvaluationRunRecord,
    EvaluationRunStatus,
)

router = APIRouter(tags=["Evaluations"])


@router.post(
    "/projects/{project_id}/evaluations/experiments",
    status_code=status.HTTP_201_CREATED,
)
async def create_experiment(
    project_id: str,
    request: EvaluationExperimentCreate,
) -> EvaluationExperimentRecord:
    try:
        record = controller.create_experiment(project_id, request.manifest)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    return record


@router.get("/projects/{project_id}/evaluations/experiments")
async def list_project_experiments(
    project_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> EvaluationExperimentPage:
    page = controller.list_project_experiments(project_id, limit=limit, offset=offset)
    if page is None:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    return page


@router.get("/evaluations/experiments/{experiment_id}")
async def get_experiment(experiment_id: str) -> EvaluationExperimentRecord:
    record = controller.get_experiment(experiment_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"Evaluation experiment not found: {experiment_id}",
        )
    return record


@router.put("/evaluations/experiments/{experiment_id}/runs/{run_id}")
async def save_run(
    experiment_id: str,
    run_id: str,
    run: EvaluationExperimentRun,
) -> EvaluationRunRecord:
    if run.manifest.id != run_id:
        raise HTTPException(status_code=409, detail="run id does not match the request path")
    try:
        return controller.save_run(experiment_id, run)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/evaluations/experiments/{experiment_id}/runs")
async def list_runs(
    experiment_id: str,
    case_id: str | None = Query(default=None),
    condition_id: str | None = Query(default=None),
    run_status: Annotated[
        EvaluationRunStatus | None,
        Query(alias="status"),
    ] = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> EvaluationRunPage:
    try:
        return controller.list_runs(
            experiment_id,
            case_id=case_id,
            condition_id=condition_id,
            status=run_status,
            limit=limit,
            offset=offset,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put(
    "/evaluations/experiments/{experiment_id}/comparisons/{ablation_condition_id}"
)
async def save_comparison(
    experiment_id: str,
    ablation_condition_id: str,
    report: AblationComparisonReport,
) -> EvaluationComparisonRecord:
    if report.ablation_condition_id != ablation_condition_id:
        raise HTTPException(
            status_code=409,
            detail="ablation condition does not match the request path",
        )
    try:
        return controller.save_comparison(experiment_id, report)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/evaluations/experiments/{experiment_id}/comparisons")
async def list_comparisons(
    experiment_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> EvaluationComparisonPage:
    try:
        return controller.list_comparisons(
            experiment_id,
            limit=limit,
            offset=offset,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
