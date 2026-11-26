"""Shared test support: injectable clocks and plan factories."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.models import Plan, StepSpec, ToolConfig  # noqa: E402


class FakeClock:
    """Virtual milliseconds. sleep() advances time and yields once."""

    def __init__(self, start: int = 0) -> None:
        self.t = start

    def now(self) -> int:
        return self.t

    async def sleep(self, ms: float) -> None:
        self.t += ms
        await asyncio.sleep(0)


class GatedClock:
    """Blocks sleeps until release, so cancellation is deterministic."""

    def __init__(self) -> None:
        self.t = 0
        self.gate = asyncio.Event()

    def now(self) -> int:
        return self.t

    async def sleep(self, ms: float) -> None:
        await self.gate.wait()
        self.t += ms


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def make_step(step_id: str, tool: str = "search", **kwargs) -> StepSpec:
    return StepSpec(id=step_id, tool=tool, **kwargs)


def make_plan(steps: list[StepSpec]) -> Plan:
    return Plan(steps=steps)


def make_tools(latency_ms: int = 20, failure_rate: float = 0.0) -> dict[str, ToolConfig]:
    return {
        name: ToolConfig(latency_ms=latency_ms, failure_rate=failure_rate)
        for name in ("search", "summarize", "generate_image")
    }
