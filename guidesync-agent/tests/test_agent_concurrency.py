from __future__ import annotations

import asyncio

import pytest

from guidesync_agent.agent_runtime.concurrency import AgentConcurrencyLimiter
from guidesync_agent.schemas import ProviderConfig


def test_agent_concurrency_limiter_serializes_profile_at_one() -> None:
    async def scenario() -> int:
        limiter = AgentConcurrencyLimiter()
        config = ProviderConfig(
            max_concurrent_agents=1,
            metadata={"model_profile_id": "local-gemma"},
        )
        active = 0
        maximum_active = 0

        async def run_agent() -> None:
            nonlocal active, maximum_active
            async with limiter.slot(config):
                active += 1
                maximum_active = max(maximum_active, active)
                await asyncio.sleep(0.02)
                active -= 1

        await asyncio.gather(*(run_agent() for _ in range(3)))
        return maximum_active

    assert asyncio.run(scenario()) == 1


def test_agent_concurrency_limiter_honours_higher_profile_limit() -> None:
    async def scenario() -> int:
        limiter = AgentConcurrencyLimiter()
        config = ProviderConfig(
            max_concurrent_agents=2,
            metadata={"model_profile_id": "hosted-model"},
        )
        active = 0
        maximum_active = 0

        async def run_agent() -> None:
            nonlocal active, maximum_active
            async with limiter.slot(config):
                active += 1
                maximum_active = max(maximum_active, active)
                await asyncio.sleep(0.02)
                active -= 1

        await asyncio.gather(*(run_agent() for _ in range(4)))
        return maximum_active

    assert asyncio.run(scenario()) == 2


def test_agent_concurrency_limiter_releases_failed_agent_slot() -> None:
    async def scenario() -> None:
        limiter = AgentConcurrencyLimiter()
        config = ProviderConfig(
            max_concurrent_agents=1,
            metadata={"model_profile_id": "local-gemma"},
        )
        with pytest.raises(RuntimeError, match="provider failed"):
            async with limiter.slot(config):
                raise RuntimeError("provider failed")
        async with asyncio.timeout(1):
            async with limiter.slot(config):
                return

    asyncio.run(scenario())
