from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import create_engine, insert, select, update

from guidesync_agent.models import (
    llm_conversation_events_table,
    llm_conversations_table,
)
from guidesync_agent.schemas import (
    LLMConversationTranscript,
    LLMTranscriptEvent,
    LLMTranscriptSummary,
)

from .serialization import (
    llm_conversation_event_from_row,
    llm_conversation_event_values,
    llm_conversation_from_row,
    llm_conversation_values,
    llm_transcript_summary_from_row,
)


class DatabaseLLMTranscriptStore:
    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(database_url, pool_pre_ping=True)

    def initialize(self) -> None:
        return None

    def save(self, transcript: LLMConversationTranscript) -> LLMConversationTranscript:
        self.initialize()
        with self.engine.begin() as connection:
            existing = connection.execute(
                select(llm_conversations_table.c.id).where(
                    llm_conversations_table.c.id == transcript.id
                )
            ).one_or_none()
            values = llm_conversation_values(transcript)
            if existing is None:
                connection.execute(insert(llm_conversations_table).values(**values))
            else:
                connection.execute(
                    update(llm_conversations_table)
                    .where(llm_conversations_table.c.id == transcript.id)
                    .values(**values)
                )
        return transcript

    def save_event(self, event: LLMTranscriptEvent) -> LLMTranscriptEvent:
        self.save_events([event])
        return event

    def save_events(self, events: Sequence[LLMTranscriptEvent]) -> list[LLMTranscriptEvent]:
        self.initialize()
        with self.engine.begin() as connection:
            for event in events:
                existing = connection.execute(
                    select(llm_conversation_events_table.c.id).where(
                        llm_conversation_events_table.c.id == event.id
                    )
                ).one_or_none()
                values = llm_conversation_event_values(event)
                if existing is None:
                    connection.execute(insert(llm_conversation_events_table).values(**values))
                else:
                    connection.execute(
                        update(llm_conversation_events_table)
                        .where(llm_conversation_events_table.c.id == event.id)
                        .values(**values)
                    )
        return list(events)

    def get(self, transcript_id: str) -> LLMConversationTranscript | None:
        self.initialize()
        with self.engine.begin() as connection:
            row = connection.execute(
                select(llm_conversations_table).where(
                    llm_conversations_table.c.id == transcript_id
                )
            ).one_or_none()
        if row is None:
            return None
        transcript = llm_conversation_from_row(row)
        return transcript.model_copy(update={"events": self.list_events(transcript_id)})

    def list_events(self, transcript_id: str) -> list[LLMTranscriptEvent]:
        self.initialize()
        with self.engine.begin() as connection:
            rows = connection.execute(
                select(llm_conversation_events_table)
                .where(llm_conversation_events_table.c.conversation_id == transcript_id)
                .order_by(
                    llm_conversation_events_table.c.sequence,
                    llm_conversation_events_table.c.created_at,
                    llm_conversation_events_table.c.id,
                )
            ).all()
        return [llm_conversation_event_from_row(row) for row in rows]


    def list_for_run(self, run_id: str) -> list[LLMTranscriptSummary]:
        self.initialize()
        with self.engine.begin() as connection:
            rows = connection.execute(
                select(llm_conversations_table)
                .where(llm_conversations_table.c.run_id == run_id)
                .order_by(llm_conversations_table.c.started_at, llm_conversations_table.c.id)
            ).all()
        return [llm_transcript_summary_from_row(row) for row in rows]

    def list_for_workflow_task(self, workflow_task_id: str) -> list[LLMTranscriptSummary]:
        self.initialize()
        with self.engine.begin() as connection:
            rows = connection.execute(
                select(llm_conversations_table)
                .where(llm_conversations_table.c.workflow_task_id == workflow_task_id)
                .order_by(llm_conversations_table.c.started_at, llm_conversations_table.c.id)
            ).all()
        return [llm_transcript_summary_from_row(row) for row in rows]
