from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from threading import Lock

from guidesync_agent.schemas import ProviderConfig

AGENT_CONCURRENCY_POLL_SECONDS = 0.01


@dataclass
class _AgentConcurrencyState:
    active: int = 0


class AgentConcurrencyLimiter:
    def __init__(self) -> None:
        self._lock = Lock()
        self._states: dict[str, _AgentConcurrencyState] = {}

    @asynccontextmanager
    async def slot(self, config: ProviderConfig) -> AsyncIterator[None]:
        key = agent_concurrency_key(config)
        limit = config.max_concurrent_agents
        await self._acquire(key, limit)
        try:
            yield
        finally:
            self._release(key)

    async def _acquire(self, key: str, limit: int) -> None:
        while True:
            with self._lock:
                state = self._states.setdefault(key, _AgentConcurrencyState())
                if state.active < limit:
                    state.active += 1
                    return
            await asyncio.sleep(AGENT_CONCURRENCY_POLL_SECONDS)

    def _release(self, key: str) -> None:
        with self._lock:
            state = self._states[key]
            state.active -= 1
            if state.active == 0:
                self._states.pop(key, None)


def agent_concurrency_key(config: ProviderConfig) -> str:
    profile_id = config.metadata.get("model_profile_id")
    if isinstance(profile_id, str) and profile_id.strip():
        return f"profile:{profile_id.strip()}"
    return "|".join(
        [
            "model",
            config.provider.value,
            config.base_url or "",
            config.model,
        ]
    )


agent_concurrency_limiter = AgentConcurrencyLimiter()
