from __future__ import annotations

from sqlalchemy import create_engine, delete, insert, or_, select
from sqlalchemy.engine import Connection

from guidesync_agent.models import (
    knowledge_annotation_edges_table,
    knowledge_annotation_runs_table,
    knowledge_annotations_table,
    knowledge_chunks_table,
    knowledge_concepts_table,
    knowledge_edges_table,
    knowledge_index_runs_table,
    knowledge_nodes_table,
)
from guidesync_agent.schemas import (
    KnowledgeDocumentRefs,
    KnowledgeEdge,
    KnowledgeGraphSnapshot,
    KnowledgeIndexRun,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
    KnowledgeTag,
)

from .retrieval import score_knowledge_search
from .serialization import (
    apply_text_ranks_to_chunks,
    apply_text_ranks_to_nodes,
    knowledge_annotation_edge_from_row,
    knowledge_chunk_from_row,
    knowledge_document_refs,
    knowledge_edge_from_row,
    knowledge_index_run_from_row,
    knowledge_node_from_row,
    knowledge_tag_cloud,
    postgres_full_text_ranks,
)


class DatabaseKnowledgeStore:
    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(database_url, pool_pre_ping=True)

    def initialize(self) -> None:
        return None

    def save_snapshot(self, snapshot: KnowledgeGraphSnapshot) -> None:
        self.initialize()
        project_id = snapshot.run.project_id
        with self.engine.begin() as connection:
            connection.execute(
                delete(knowledge_index_runs_table).where(
                    knowledge_index_runs_table.c.id == snapshot.run.id
                )
            )
            connection.execute(
                insert(knowledge_index_runs_table).values(
                    id=snapshot.run.id,
                    project_id=snapshot.run.project_id,
                    status=snapshot.run.status.value,
                    source_ref=snapshot.run.source_ref,
                    started_at=snapshot.run.started_at,
                    completed_at=snapshot.run.completed_at,
                    error_message=snapshot.run.error_message,
                    request_snapshot=snapshot.run.request.model_dump(mode="json"),
                    summary=snapshot.run.summary.model_dump(mode="json"),
                )
            )
            self._replace_graph(connection, project_id, snapshot)

    def save_changed_docs_snapshot(
        self,
        snapshot: KnowledgeGraphSnapshot,
        changed_paths: set[str],
    ) -> None:
        self.initialize()
        project_id = snapshot.run.project_id
        with self.engine.begin() as connection:
            connection.execute(
                delete(knowledge_index_runs_table).where(
                    knowledge_index_runs_table.c.id == snapshot.run.id
                )
            )
            connection.execute(
                insert(knowledge_index_runs_table).values(
                    id=snapshot.run.id,
                    project_id=snapshot.run.project_id,
                    status=snapshot.run.status.value,
                    source_ref=snapshot.run.source_ref,
                    started_at=snapshot.run.started_at,
                    completed_at=snapshot.run.completed_at,
                    error_message=snapshot.run.error_message,
                    request_snapshot=snapshot.run.request.model_dump(mode="json"),
                    summary=snapshot.run.summary.model_dump(mode="json"),
                )
            )
            self._merge_changed_docs(connection, project_id, snapshot, changed_paths)

    def get_index_run(self, run_id: str) -> KnowledgeIndexRun | None:
        self.initialize()
        with self.engine.begin() as connection:
            row = connection.execute(
                select(knowledge_index_runs_table).where(knowledge_index_runs_table.c.id == run_id)
            ).one_or_none()
        return knowledge_index_run_from_row(row) if row else None

    def list_index_runs(self, project_id: str | None = None) -> list[KnowledgeIndexRun]:
        self.initialize()
        query = select(knowledge_index_runs_table).order_by(
            knowledge_index_runs_table.c.completed_at.desc(),
            knowledge_index_runs_table.c.started_at.desc(),
        )
        if project_id:
            query = query.where(knowledge_index_runs_table.c.project_id == project_id)
        with self.engine.begin() as connection:
            rows = connection.execute(query).all()
        return [knowledge_index_run_from_row(row) for row in rows]

    def search(self, request: KnowledgeSearchRequest) -> list[KnowledgeSearchResult]:
        self.initialize()
        nodes_query = select(knowledge_nodes_table)
        chunks_query = select(knowledge_chunks_table)
        edges_query = select(knowledge_edges_table)
        annotation_edges_query = select(knowledge_annotation_edges_table)
        if request.project_id is not None:
            nodes_query = nodes_query.where(
                knowledge_nodes_table.c.project_id == request.project_id
            )
            chunks_query = chunks_query.where(
                knowledge_chunks_table.c.project_id == request.project_id
            )
            edges_query = edges_query.where(
                knowledge_edges_table.c.project_id == request.project_id
            )
            annotation_edges_query = annotation_edges_query.where(
                knowledge_annotation_edges_table.c.project_id == request.project_id
            )
        with self.engine.begin() as connection:
            node_rows = connection.execute(nodes_query).all()
            chunk_rows = connection.execute(chunks_query).all()
            edge_rows = connection.execute(edges_query).all()
            annotation_edge_rows = connection.execute(annotation_edges_query).all()
            node_text_ranks, chunk_text_ranks = postgres_full_text_ranks(connection, request)
        nodes = [knowledge_node_from_row(row) for row in node_rows]
        chunks = [knowledge_chunk_from_row(row) for row in chunk_rows]
        nodes = apply_text_ranks_to_nodes(nodes, node_text_ranks)
        chunks = apply_text_ranks_to_chunks(chunks, chunk_text_ranks)
        edges = [knowledge_edge_from_row(row) for row in edge_rows]
        annotation_edges = [knowledge_annotation_edge_from_row(row) for row in annotation_edge_rows]
        return score_knowledge_search(request, nodes, chunks, edges, annotation_edges)

    def document_refs(self, project_id: str | None = None) -> KnowledgeDocumentRefs:
        self.initialize()
        nodes_query = select(knowledge_nodes_table)
        chunks_query = select(knowledge_chunks_table)
        if project_id is not None:
            nodes_query = nodes_query.where(knowledge_nodes_table.c.project_id == project_id)
            chunks_query = chunks_query.where(knowledge_chunks_table.c.project_id == project_id)
        with self.engine.begin() as connection:
            node_rows = connection.execute(nodes_query).all()
            chunk_rows = connection.execute(chunks_query).all()
        nodes = [knowledge_node_from_row(row) for row in node_rows]
        chunks = [knowledge_chunk_from_row(row) for row in chunk_rows]
        return knowledge_document_refs(nodes, chunks, project_id=project_id)

    def tag_cloud(self, project_id: str | None = None) -> list[KnowledgeTag]:
        self.initialize()
        query = select(knowledge_nodes_table)
        if project_id is not None:
            query = query.where(knowledge_nodes_table.c.project_id == project_id)
        with self.engine.begin() as connection:
            rows = connection.execute(query).all()
        nodes = [knowledge_node_from_row(row) for row in rows]
        return knowledge_tag_cloud(nodes, project_id=project_id)

    def related_edges(
        self,
        node_ids: set[str],
        project_id: str | None = None,
    ) -> list[KnowledgeEdge]:
        self.initialize()
        if not node_ids:
            return []
        query = select(knowledge_edges_table).where(
            knowledge_edges_table.c.source_node_id.in_(node_ids)
            | knowledge_edges_table.c.target_node_id.in_(node_ids)
        )
        if project_id is not None:
            query = query.where(knowledge_edges_table.c.project_id == project_id)
        with self.engine.begin() as connection:
            rows = connection.execute(query).all()
        return [knowledge_edge_from_row(row) for row in rows]

    def _replace_graph(
        self,
        connection: Connection,
        project_id: str | None,
        snapshot: KnowledgeGraphSnapshot,
    ) -> None:
        node_scope = knowledge_nodes_table.c.project_id.is_(None)
        edge_scope = knowledge_edges_table.c.project_id.is_(None)
        chunk_scope = knowledge_chunks_table.c.project_id.is_(None)
        if project_id is not None:
            node_scope = knowledge_nodes_table.c.project_id == project_id
            edge_scope = knowledge_edges_table.c.project_id == project_id
            chunk_scope = knowledge_chunks_table.c.project_id == project_id
        annotation_run_scope = knowledge_annotation_runs_table.c.project_id.is_(None)
        annotation_scope = knowledge_annotations_table.c.project_id.is_(None)
        concept_scope = knowledge_concepts_table.c.project_id.is_(None)
        annotation_edge_scope = knowledge_annotation_edges_table.c.project_id.is_(None)
        if project_id is not None:
            annotation_run_scope = knowledge_annotation_runs_table.c.project_id == project_id
            annotation_scope = knowledge_annotations_table.c.project_id == project_id
            concept_scope = knowledge_concepts_table.c.project_id == project_id
            annotation_edge_scope = knowledge_annotation_edges_table.c.project_id == project_id
        connection.execute(delete(knowledge_annotation_edges_table).where(annotation_edge_scope))
        connection.execute(delete(knowledge_annotations_table).where(annotation_scope))
        connection.execute(delete(knowledge_concepts_table).where(concept_scope))
        connection.execute(delete(knowledge_annotation_runs_table).where(annotation_run_scope))
        connection.execute(delete(knowledge_chunks_table).where(chunk_scope))
        connection.execute(delete(knowledge_edges_table).where(edge_scope))
        connection.execute(delete(knowledge_nodes_table).where(node_scope))
        for node in snapshot.nodes:
            connection.execute(
                insert(knowledge_nodes_table).values(**node.model_dump(mode="python"))
            )
        for edge in snapshot.edges:
            connection.execute(
                insert(knowledge_edges_table).values(**edge.model_dump(mode="python"))
            )
        for chunk in snapshot.chunks:
            connection.execute(
                insert(knowledge_chunks_table).values(**chunk.model_dump(mode="python"))
            )
        self._insert_annotations(connection, snapshot)

    def _merge_changed_docs(
        self,
        connection: Connection,
        project_id: str | None,
        snapshot: KnowledgeGraphSnapshot,
        changed_paths: set[str],
    ) -> None:
        if not changed_paths:
            return

        node_scope = knowledge_nodes_table.c.project_id.is_(None)
        edge_scope = knowledge_edges_table.c.project_id.is_(None)
        chunk_scope = knowledge_chunks_table.c.project_id.is_(None)
        if project_id is not None:
            node_scope = knowledge_nodes_table.c.project_id == project_id
            edge_scope = knowledge_edges_table.c.project_id == project_id
            chunk_scope = knowledge_chunks_table.c.project_id == project_id
        annotation_run_scope = knowledge_annotation_runs_table.c.project_id.is_(None)
        annotation_scope = knowledge_annotations_table.c.project_id.is_(None)
        concept_scope = knowledge_concepts_table.c.project_id.is_(None)
        annotation_edge_scope = knowledge_annotation_edges_table.c.project_id.is_(None)
        if project_id is not None:
            annotation_run_scope = knowledge_annotation_runs_table.c.project_id == project_id
            annotation_scope = knowledge_annotations_table.c.project_id == project_id
            concept_scope = knowledge_concepts_table.c.project_id == project_id
            annotation_edge_scope = knowledge_annotation_edges_table.c.project_id == project_id

        changed_path_list = sorted(changed_paths)
        removed_node_rows = connection.execute(
            select(knowledge_nodes_table.c.id).where(
                node_scope,
                knowledge_nodes_table.c.path.in_(changed_path_list),
            )
        ).all()
        removed_node_ids = {row.id for row in removed_node_rows}
        incoming_edge_ids = {edge.id for edge in snapshot.edges}
        incoming_chunk_ids = {chunk.id for chunk in snapshot.chunks}
        incoming_annotation_run_ids = {run.id for run in snapshot.annotation_runs}
        incoming_concept_ids = {concept.id for concept in snapshot.concepts}

        connection.execute(
            delete(knowledge_chunks_table).where(
                chunk_scope,
                or_(
                    knowledge_chunks_table.c.path.in_(changed_path_list),
                    knowledge_chunks_table.c.id.in_(incoming_chunk_ids),
                ),
            )
        )
        connection.execute(
            delete(knowledge_annotation_edges_table).where(
                annotation_edge_scope,
                or_(
                    knowledge_annotation_edges_table.c.source_path.in_(changed_path_list),
                    knowledge_annotation_edges_table.c.annotation_run_id.in_(
                        incoming_annotation_run_ids
                    ),
                ),
            )
        )
        connection.execute(
            delete(knowledge_annotations_table).where(
                annotation_scope,
                or_(
                    knowledge_annotations_table.c.source_path.in_(changed_path_list),
                    knowledge_annotations_table.c.run_id.in_(incoming_annotation_run_ids),
                ),
            )
        )
        connection.execute(
            delete(knowledge_concepts_table).where(
                concept_scope,
                knowledge_concepts_table.c.id.in_(incoming_concept_ids),
            )
        )
        connection.execute(
            delete(knowledge_annotation_runs_table).where(
                annotation_run_scope,
                knowledge_annotation_runs_table.c.id.in_(incoming_annotation_run_ids),
            )
        )
        connection.execute(
            delete(knowledge_edges_table).where(
                edge_scope,
                or_(
                    knowledge_edges_table.c.id.in_(incoming_edge_ids),
                    knowledge_edges_table.c.source_node_id.in_(removed_node_ids),
                    knowledge_edges_table.c.target_node_id.in_(removed_node_ids),
                ),
            )
        )
        connection.execute(
            delete(knowledge_nodes_table).where(
                node_scope,
                knowledge_nodes_table.c.path.in_(changed_path_list),
            )
        )

        existing_node_ids = {
            row.id for row in connection.execute(select(knowledge_nodes_table.c.id)).all()
        }
        for node in snapshot.nodes:
            if node.path not in changed_paths and node.id in existing_node_ids:
                continue
            connection.execute(
                insert(knowledge_nodes_table).values(**node.model_dump(mode="python"))
            )
        for edge in snapshot.edges:
            connection.execute(
                insert(knowledge_edges_table).values(**edge.model_dump(mode="python"))
            )
        for chunk in snapshot.chunks:
            connection.execute(
                insert(knowledge_chunks_table).values(**chunk.model_dump(mode="python"))
            )
        self._insert_annotations(connection, snapshot)

    def _insert_annotations(
        self,
        connection: Connection,
        snapshot: KnowledgeGraphSnapshot,
    ) -> None:
        for run in snapshot.annotation_runs:
            connection.execute(
                insert(knowledge_annotation_runs_table).values(**run.model_dump(mode="python"))
            )
        for concept in snapshot.concepts:
            connection.execute(
                insert(knowledge_concepts_table).values(**concept.model_dump(mode="python"))
            )
        for annotation in snapshot.annotations:
            connection.execute(
                insert(knowledge_annotations_table).values(**annotation.model_dump(mode="python"))
            )
        for edge in snapshot.annotation_edges:
            connection.execute(
                insert(knowledge_annotation_edges_table).values(**edge.model_dump(mode="python"))
            )
