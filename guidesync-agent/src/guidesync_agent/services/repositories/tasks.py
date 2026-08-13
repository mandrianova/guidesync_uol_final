from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import ValidationError

from guidesync_agent.schemas import ProjectProfileTask, RepositorySyncTask
from guidesync_agent.settings import get_settings

logger = logging.getLogger(__name__)


class SqsClient(Protocol):
    def get_queue_url(self, *, QueueName: str) -> Mapping[str, Any]: ...  # noqa: N803

    def send_message(
        self,
        *,
        QueueUrl: str,  # noqa: N803
        MessageBody: str,  # noqa: N803
    ) -> Mapping[str, Any]: ...

    def receive_message(
        self,
        *,
        QueueUrl: str,  # noqa: N803
        MaxNumberOfMessages: int,  # noqa: N803
        WaitTimeSeconds: int,  # noqa: N803
        VisibilityTimeout: int,  # noqa: N803
    ) -> Mapping[str, Any]: ...

    def delete_message(
        self,
        *,
        QueueUrl: str,  # noqa: N803
        ReceiptHandle: str,  # noqa: N803
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class RepositoryTaskMessage:
    task: RepositorySyncTask | ProjectProfileTask
    receipt_handle: str


class RepositoryTaskQueue:
    def __init__(
        self,
        *,
        queue_url: str | None = None,
        queue_name: str | None = None,
        endpoint_url: str | None = None,
        client: SqsClient | None = None,
    ) -> None:
        self._queue_url = queue_url if queue_url is not None else queue_url_from_settings()
        self._queue_name = queue_name if queue_name is not None else queue_name_from_settings()
        self._endpoint_url = (
            endpoint_url if endpoint_url is not None else endpoint_url_from_settings()
        )
        self._client = client

    @property
    def enabled(self) -> bool:
        return bool(self._queue_url or self._queue_name)

    def send_repository_sync(self, task: RepositorySyncTask) -> bool:
        return self.send_task(task)

    def send_project_profile(self, task: ProjectProfileTask) -> bool:
        return self.send_task(task)

    def send_task(self, task: RepositorySyncTask | ProjectProfileTask) -> bool:
        queue_url = self.queue_url()
        if queue_url is None:
            return False
        self.client().send_message(
            QueueUrl=queue_url,
            MessageBody=task.model_dump_json(),
        )
        return True

    def receive_tasks(
        self,
        *,
        max_messages: int = 1,
        wait_time_seconds: int = 0,
        visibility_timeout: int = 900,
    ) -> list[RepositoryTaskMessage]:
        return self._receive_messages(
            max_messages=max_messages,
            wait_time_seconds=wait_time_seconds,
            visibility_timeout=visibility_timeout,
        )

    def receive_repository_sync_tasks(
        self,
        *,
        max_messages: int = 1,
        wait_time_seconds: int = 0,
        visibility_timeout: int = 900,
    ) -> list[RepositoryTaskMessage]:
        return [
            message
            for message in self._receive_messages(
                max_messages=max_messages,
                wait_time_seconds=wait_time_seconds,
                visibility_timeout=visibility_timeout,
            )
            if isinstance(message.task, RepositorySyncTask)
        ]

    def _receive_messages(
        self,
        *,
        max_messages: int,
        wait_time_seconds: int,
        visibility_timeout: int,
    ) -> list[RepositoryTaskMessage]:
        queue_url = self.queue_url()
        if queue_url is None:
            return []
        try:
            response = self.client().receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=max_messages,
                WaitTimeSeconds=wait_time_seconds,
                VisibilityTimeout=visibility_timeout,
            )
        except (BotoCoreError, ClientError) as exc:
            logger.warning("Could not receive repository sync tasks: %s", exc)
            return []
        messages: list[RepositoryTaskMessage] = []
        for message in response.get("Messages", []):
            if not isinstance(message, Mapping):
                continue
            receipt_handle = message.get("ReceiptHandle")
            body = message.get("Body")
            if not isinstance(receipt_handle, str) or not isinstance(body, str):
                continue
            try:
                task = background_task_from_payload(json.loads(body))
            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                logger.warning("Ignoring invalid background task: %s", exc)
                self.delete_message(receipt_handle)
                continue
            messages.append(RepositoryTaskMessage(task=task, receipt_handle=receipt_handle))
        return messages

    def delete_message(self, receipt_handle: str) -> None:
        queue_url = self.queue_url()
        if queue_url is None:
            return
        try:
            self.client().delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
        except (BotoCoreError, ClientError) as exc:
            logger.warning("Could not delete repository sync task message: %s", exc)

    def queue_url(self) -> str | None:
        if self._queue_url:
            return self._queue_url
        if not self._queue_name:
            return None
        try:
            response = self.client().get_queue_url(QueueName=self._queue_name)
        except (BotoCoreError, ClientError) as exc:
            logger.warning("Repository sync queue is unavailable: %s", exc)
            return None
        queue_url = response.get("QueueUrl")
        self._queue_url = queue_url if isinstance(queue_url, str) else None
        return self._queue_url

    def client(self) -> SqsClient:
        if self._client is None:
            self._client = boto3.client("sqs", endpoint_url=self._endpoint_url)
        return self._client


def queue_url_from_settings() -> str | None:
    return get_settings().queue.repository_sync_url


def queue_name_from_settings() -> str | None:
    return get_settings().queue.repository_sync_name


def endpoint_url_from_settings() -> str | None:
    return get_settings().queue.sqs_endpoint_url


def background_task_from_payload(
    payload: object,
) -> RepositorySyncTask | ProjectProfileTask:
    if not isinstance(payload, Mapping):
        raise ValueError("Background task payload must be an object.")
    task_type = payload.get("task_type")
    if task_type == "repository_sync":
        return RepositorySyncTask.model_validate(payload)
    if task_type == "project_profile":
        return ProjectProfileTask.model_validate(payload)
    raise ValueError(f"Unsupported background task type: {task_type}")
