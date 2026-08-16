from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, Field

from .repository import RepositoryInput


class ReportRepositoryScope(BaseModel):
    name: str
    since: str | None = None
    until: str | None = None
    branches: list[str] = Field(default_factory=list)


class ReportChangeScope(BaseModel):
    repositories: list[ReportRepositoryScope] = Field(default_factory=list)

    @classmethod
    def from_repositories(
        cls,
        repositories: Iterable[RepositoryInput],
    ) -> ReportChangeScope:
        grouped: dict[str, ReportRepositoryScope] = {}
        for index, repository in enumerate(repositories):
            name = repository_scope_name(repository)
            key = repository.repository_id or f"{index}:{name}"
            existing = grouped.get(key)
            if existing is None:
                grouped[key] = ReportRepositoryScope(
                    name=name,
                    since=repository.since,
                    until=repository.until,
                    branches=list(dict.fromkeys(repository.branches)),
                )
                continue
            existing.branches = list(
                dict.fromkeys([*existing.branches, *repository.branches])
            )
        return cls(repositories=list(grouped.values()))


def repository_scope_name(repository: RepositoryInput) -> str:
    if len(repository.branches) != 1:
        return repository.name
    suffix = f" [{repository.branches[0]}]"
    return repository.name.removesuffix(suffix)
