from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.engine import Connection, Row

from guidesync_agent.models import (
    knowledge_chunks_table,
    knowledge_nodes_table,
)
from guidesync_agent.schemas import (
    KnowledgeAnnotationEdge,
    KnowledgeChunk,
    KnowledgeDocumentRef,
    KnowledgeDocumentRefs,
    KnowledgeEdge,
    KnowledgeIndexRequest,
    KnowledgeIndexRun,
    KnowledgeIndexStatus,
    KnowledgeIndexSummary,
    KnowledgeNode,
    KnowledgeNodeKind,
    KnowledgeSearchRequest,
    KnowledgeSectionRef,
    KnowledgeTag,
    KnowledgeTagCategory,
)


def knowledge_index_run_from_row(row: Row) -> KnowledgeIndexRun:
    mapping = row._mapping
    return KnowledgeIndexRun(
        id=mapping["id"],
        project_id=mapping["project_id"],
        status=KnowledgeIndexStatus(mapping["status"]),
        source_ref=mapping["source_ref"],
        started_at=mapping["started_at"],
        completed_at=mapping["completed_at"],
        error_message=mapping["error_message"],
        request=KnowledgeIndexRequest.model_validate(mapping["request_snapshot"]),
        summary=KnowledgeIndexSummary.model_validate(mapping["summary"]),
    )

def knowledge_node_from_row(row: Row) -> KnowledgeNode:
    mapping = row._mapping
    return KnowledgeNode(
        id=mapping["id"],
        project_id=mapping["project_id"],
        repo=mapping["repo"],
        kind=mapping["kind"],
        name=mapping["name"],
        qualified_name=mapping["qualified_name"],
        path=mapping["path"],
        start_line=mapping["start_line"],
        end_line=mapping["end_line"],
        summary=mapping["summary"],
        content_hash=mapping["content_hash"],
        metadata=mapping["metadata"],
        created_at=mapping["created_at"],
    )

def knowledge_edge_from_row(row: Row) -> KnowledgeEdge:
    mapping = row._mapping
    return KnowledgeEdge(
        id=mapping["id"],
        project_id=mapping["project_id"],
        source_node_id=mapping["source_node_id"],
        target_node_id=mapping["target_node_id"],
        edge_type=mapping["edge_type"],
        confidence=mapping["confidence"],
        evidence_ref=mapping["evidence_ref"],
        metadata=mapping["metadata"],
        created_at=mapping["created_at"],
    )

def knowledge_annotation_edge_from_row(row: Row) -> KnowledgeAnnotationEdge:
    return KnowledgeAnnotationEdge.model_validate(dict(row._mapping))

def knowledge_chunk_from_row(row: Row) -> KnowledgeChunk:
    mapping = row._mapping
    return KnowledgeChunk(
        id=mapping["id"],
        project_id=mapping["project_id"],
        node_id=mapping["node_id"],
        repo=mapping["repo"],
        path=mapping["path"],
        heading=mapping["heading"],
        text=mapping["text"],
        token_count=mapping["token_count"],
        metadata=mapping["metadata"],
        created_at=mapping["created_at"],
    )

def postgres_full_text_ranks(
    connection: Connection,
    request: KnowledgeSearchRequest,
) -> tuple[dict[str, float], dict[str, float]]:
    if connection.dialect.name != "postgresql" or not request.query.strip():
        return {}, {}

    ts_query = func.websearch_to_tsquery("simple", request.query)
    node_vector = func.to_tsvector(
        "simple",
        func.concat_ws(
            " ",
            knowledge_nodes_table.c.name,
            knowledge_nodes_table.c.qualified_name,
            knowledge_nodes_table.c.path,
            knowledge_nodes_table.c.summary,
        ),
    )
    chunk_vector = func.to_tsvector(
        "simple",
        func.concat_ws(
            " ",
            knowledge_chunks_table.c.heading,
            knowledge_chunks_table.c.path,
            knowledge_chunks_table.c.text,
        ),
    )
    node_rank = func.ts_rank_cd(node_vector, ts_query)
    chunk_rank = func.ts_rank_cd(chunk_vector, ts_query)
    node_query = select(knowledge_nodes_table.c.id, node_rank.label("rank")).where(
        node_vector.op("@@")(ts_query)
    )
    chunk_query = select(knowledge_chunks_table.c.id, chunk_rank.label("rank")).where(
        chunk_vector.op("@@")(ts_query)
    )
    if request.project_id is not None:
        node_query = node_query.where(knowledge_nodes_table.c.project_id == request.project_id)
        chunk_query = chunk_query.where(knowledge_chunks_table.c.project_id == request.project_id)

    node_rows = connection.execute(node_query).all()
    chunk_rows = connection.execute(chunk_query).all()
    return row_ranks(node_rows), row_ranks(chunk_rows)

def row_ranks(rows: Sequence[Row]) -> dict[str, float]:
    ranks: dict[str, float] = {}
    for row in rows:
        mapping = row._mapping
        rank = mapping["rank"]
        if isinstance(rank, (int, float)):
            ranks[str(mapping["id"])] = max(float(rank), 0.0)
    return ranks

def apply_text_ranks_to_nodes(
    nodes: list[KnowledgeNode],
    ranks: dict[str, float],
) -> list[KnowledgeNode]:
    if not ranks:
        return nodes
    return [
        node.model_copy(
            update={
                "metadata": {
                    **node.metadata,
                    "postgres_full_text_score": ranks[node.id],
                }
            }
        )
        if node.id in ranks
        else node
        for node in nodes
    ]

def apply_text_ranks_to_chunks(
    chunks: list[KnowledgeChunk],
    ranks: dict[str, float],
) -> list[KnowledgeChunk]:
    if not ranks:
        return chunks
    return [
        chunk.model_copy(
            update={
                "metadata": {
                    **chunk.metadata,
                    "postgres_full_text_score": ranks[chunk.id],
                }
            }
        )
        if chunk.id in ranks
        else chunk
        for chunk in chunks
    ]

def knowledge_document_refs(
    nodes: list[KnowledgeNode],
    chunks: list[KnowledgeChunk],
    *,
    project_id: str | None = None,
) -> KnowledgeDocumentRefs:
    scoped_nodes = [node for node in nodes if project_id is None or node.project_id == project_id]
    docs = [node for node in scoped_nodes if node.kind == KnowledgeNodeKind.DOC_PAGE and node.path]
    sections = [
        node for node in scoped_nodes if node.kind == KnowledgeNodeKind.DOC_SECTION and node.path
    ]
    chunks_by_node = {chunk.node_id: chunk for chunk in chunks}
    document_id_by_path = {doc.path: doc.id for doc in docs if doc.path}
    section_counts = Counter(section.path for section in sections if section.path)
    document_refs = [
        KnowledgeDocumentRef(
            id=doc.id,
            project_id=doc.project_id,
            repo=doc.repo,
            path=doc.path or "",
            title=doc.name,
            summary=doc.summary,
            content_hash=doc.content_hash,
            source_commit=string_metadata(doc.metadata, "commit_sha"),
            tags=list_metadata(doc.metadata, "tags"),
            categories=list_metadata(doc.metadata, "categories"),
            keyphrases=list_metadata(doc.metadata, "keyphrases"),
            extracted_names=list_metadata(doc.metadata, "extracted_names"),
            concepts=list_metadata(doc.metadata, "concepts"),
            search_terms=list_metadata(doc.metadata, "search_terms"),
            section_count=section_counts.get(doc.path, 0),
        )
        for doc in sorted(docs, key=lambda item: (item.path or "", item.name))
    ]
    section_refs = []
    for section in sorted(
        sections,
        key=lambda item: (item.path or "", item.start_line or 0, item.name),
    ):
        if section.path is None:
            continue
        document_id = document_id_by_path.get(section.path)
        if document_id is None:
            continue
        chunk = chunks_by_node.get(section.id)
        metadata = {**section.metadata, **(chunk.metadata if chunk else {})}
        section_refs.append(
            KnowledgeSectionRef(
                id=section.id,
                project_id=section.project_id,
                document_id=document_id,
                repo=section.repo,
                path=section.path,
                heading=section.name,
                start_line=section.start_line,
                end_line=section.end_line,
                summary=section.summary,
                content_hash=section.content_hash,
                source_commit=string_metadata(metadata, "commit_sha"),
                tags=list_metadata(metadata, "tags"),
                categories=list_metadata(metadata, "categories"),
                keyphrases=list_metadata(metadata, "keyphrases"),
                extracted_names=list_metadata(metadata, "extracted_names"),
                concepts=list_metadata(metadata, "concepts"),
                search_terms=list_metadata(metadata, "search_terms"),
            )
        )
    return KnowledgeDocumentRefs(documents=document_refs, sections=section_refs)

def knowledge_tag_cloud(
    nodes: list[KnowledgeNode],
    *,
    project_id: str | None = None,
) -> list[KnowledgeTag]:
    tags: Counter[str] = Counter()
    categories: Counter[str] = Counter()
    keyphrases: Counter[str] = Counter()
    extracted_names: Counter[str] = Counter()
    concepts: Counter[str] = Counter()
    for node in nodes:
        if project_id is not None and node.project_id != project_id:
            continue
        tags.update(list_metadata(node.metadata, "tags"))
        categories.update(list_metadata(node.metadata, "categories"))
        keyphrases.update(list_metadata(node.metadata, "keyphrases"))
        extracted_names.update(list_metadata(node.metadata, "extracted_names"))
        concepts.update(list_metadata(node.metadata, "concepts"))
    values = [
        KnowledgeTag(value=value, count=count, category=KnowledgeTagCategory.TAG)
        for value, count in tags.items()
    ]
    values.extend(
        KnowledgeTag(value=value, count=count, category=KnowledgeTagCategory.CATEGORY)
        for value, count in categories.items()
    )
    values.extend(
        KnowledgeTag(value=value, count=count, category=KnowledgeTagCategory.KEYPHRASE)
        for value, count in keyphrases.items()
    )
    values.extend(
        KnowledgeTag(value=value, count=count, category=KnowledgeTagCategory.EXTRACTED_NAME)
        for value, count in extracted_names.items()
    )
    values.extend(
        KnowledgeTag(value=value, count=count, category=KnowledgeTagCategory.CONCEPT)
        for value, count in concepts.items()
    )
    return sorted(values, key=lambda item: (item.count, item.value), reverse=True)

def list_metadata(metadata: dict[str, object], key: str) -> list[str]:
    value = metadata.get(key)
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []

def string_metadata(metadata: dict[str, object], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) else None
