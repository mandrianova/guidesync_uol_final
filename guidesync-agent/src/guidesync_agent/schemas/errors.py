from __future__ import annotations

from pydantic import BaseModel


class OperationError(BaseModel):
    code: str
    message: str
    retryable: bool = False
