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


class BarrierClock:
    """Holds the first `parties` sleeps until all of them have arrived."""

    def __init__(self, parties: int) -> None:
        self.t = 0
        self.parties = parties
        self.arrived = 0
        self.gate = asyncio.Event()
        self.all_arrived = asyncio.Event()

    def now(self) -> int:
        return self.t

    async def sleep(self, ms: float) -> None:
        self.arrived += 1
        if self.arrived >= self.parties:
            self.all_arrived.set()
        await self.gate.wait()
        self.t += ms


class DeterministicRng:
    """Returns a fixed point inside randint() and a fixed draw in random()."""

    def __init__(self, mode: str = "middle") -> None:
        self.mode = mode

    def randint(self, a: int, b: int) -> int:
        if self.mode == "max":
            return b
        if self.mode == "min":
            return a
        return (a + b) // 2

    def random(self) -> float:
        return 0.5


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
