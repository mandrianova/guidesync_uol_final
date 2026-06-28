from __future__ import annotations

from sqlalchemy.engine import Row

from guidesync_agent.schemas import (
    ProjectProfileEvidenceRef,
    ProjectProfileRepositoryMapItem,
    ProjectProfileSnapshot,
    ProjectProfileSourceRef,
    ProjectProfileStatus,
    ProjectTaxonomy,
    ValidationFinding,
)


def project_profile_from_row(row: Row) -> ProjectProfileSnapshot:
    mapping = row._mapping
    return ProjectProfileSnapshot(
        id=mapping["id"],
        project_id=mapping["project_id"],
        status=ProjectProfileStatus(mapping["status"]),
        version=mapping["version"],
        prompt_version=mapping["prompt_version"],
        summary=mapping["summary"],
        project_description=mapping.get("project_description") or "",
        project_structure=list(mapping.get("project_structure") or []),
        architecture=list(mapping["architecture"]),
        core_concepts=list(mapping.get("core_concepts") or []),
        workflows=list(mapping["workflows"]),
        key_terms=list(mapping["key_terms"]),
        agent_context=mapping.get("agent_context") or "",
        taxonomy=ProjectTaxonomy.model_validate(mapping["taxonomy"]),
        profile_evidence=[
            ProjectProfileEvidenceRef.model_validate(item) for item in mapping["profile_evidence"]
        ],
        repository_map=[
            ProjectProfileRepositoryMapItem.model_validate(item)
            for item in mapping["repository_map"]
        ],
        source_refs=[
            ProjectProfileSourceRef.model_validate(item) for item in mapping["source_refs"]
        ],
        warnings=list(mapping["warnings"]),
        uncertainty_notes=list(mapping["uncertainty_notes"]),
        artifact_uris=dict(mapping["artifact_uris"]),
        model_metadata=dict(mapping.get("model_metadata") or {}),
        tool_trace_refs=list(mapping.get("tool_trace_refs") or []),
        validation_findings=[
            ValidationFinding.model_validate(item)
            for item in (mapping.get("validation_findings") or [])
        ],
        created_at=mapping["created_at"],
        completed_at=mapping["completed_at"],
        error_message=mapping["error_message"],
    )
