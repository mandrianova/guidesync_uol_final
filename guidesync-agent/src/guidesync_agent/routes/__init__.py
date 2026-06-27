from __future__ import annotations

from fastapi import APIRouter

from guidesync_agent.routes.base import router as base_router
from guidesync_agent.routes.github import router as github_router
from guidesync_agent.routes.knowledge import router as knowledge_router
from guidesync_agent.routes.llm_transcripts import (
    router as llm_transcripts_router,
)
from guidesync_agent.routes.llm_transcripts import (
    run_router as run_llm_transcripts_router,
)
from guidesync_agent.routes.llm_transcripts import (
    workflow_task_router as workflow_task_llm_transcripts_router,
)
from guidesync_agent.routes.model_settings import router as model_settings_router
from guidesync_agent.routes.model_usage import (
    router as model_usage_router,
)
from guidesync_agent.routes.model_usage import (
    workflow_task_router as workflow_task_model_usage_router,
)
from guidesync_agent.routes.projects import router as projects_router
from guidesync_agent.routes.repositories import router as repositories_router
from guidesync_agent.routes.runs import router as runs_router
from guidesync_agent.routes.workflow import router as workflow_router

router = APIRouter()
router.include_router(base_router)
router.include_router(model_settings_router)
router.include_router(projects_router)
router.include_router(repositories_router)
router.include_router(github_router)
router.include_router(runs_router)
router.include_router(model_usage_router)
router.include_router(workflow_task_model_usage_router)
router.include_router(run_llm_transcripts_router)
router.include_router(workflow_task_llm_transcripts_router)
router.include_router(llm_transcripts_router)
router.include_router(knowledge_router)
router.include_router(workflow_router)
