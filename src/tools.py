"""Simulated tools; no model or network call is made."""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass

from .events import Clock
from .models import ToolConfig


class ToolError(Exception):
    """Raised when a simulated tool fails."""


class ToolTimeout(ToolError):
    """Raised when a simulated tool exceeds its timeout."""


@dataclass
class ConcurrencyProbe:
    current: int = 0
    peak: int = 0

    def enter(self) -> None:
        self.current += 1
        self.peak = max(self.peak, self.current)

    def leave(self) -> None:
        self.current -= 1


class SimulatedTools:
    def __init__(
        self,
        configs: dict[str, ToolConfig],
        time_scale: float,
        clock: Clock,
        rng: random.Random | None = None,
    ) -> None:
        self.configs = configs
        self.time_scale = time_scale
        self.clock = clock
        self.rng = rng or random.Random()
        self.probe = ConcurrencyProbe()

    async def call(self, name: str, args: dict, timeout_ms: int) -> dict:
        config = self.configs.get(name) or ToolConfig()
        latency_ms = config.latency_ms * self.time_scale
        budget_s = max(0.0, timeout_ms * self.time_scale / 1000.0)

        self.probe.enter()
        try:
            try:
                await asyncio.wait_for(self.clock.sleep(latency_ms), timeout=budget_s)
            except asyncio.TimeoutError as exc:
                raise ToolTimeout(f"{name} timed out after {budget_s:.3f}s") from exc

            if self.rng.random() < config.failure_rate:
                raise ToolError(f"{name} failed")

            if name == "search":
                return {"query": args.get("q", ""), "hits": 3}
            if name == "summarize":
                return {"summary": f"summary of {len(args.get('items', []))} items"}
            return {"image": "placeholder"}
        finally:
            self.probe.leave()
