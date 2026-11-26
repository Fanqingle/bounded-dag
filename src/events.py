"""Append-only event log with an injectable clock."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Protocol


class Clock(Protocol):
    def now(self) -> int:
        """Return a millisecond timestamp."""

    async def sleep(self, ms: float) -> None:
        """Sleep for milliseconds; must be cancellable."""


class RealClock:
    def now(self) -> int:
        return time.time_ns() // 1_000_000

    async def sleep(self, ms: float) -> None:
        await asyncio.sleep(max(0.0, ms) / 1000.0)


@dataclass(frozen=True)
class Event:
    seq: int
    ts: int
    type: str
    run_id: str
    step_id: str | None = None
    attempt: int | None = None
    payload: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "ts": self.ts,
            "type": self.type,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "attempt": self.attempt,
            "payload": self.payload or {},
        }


class EventLog:
    def __init__(self, run_id: str, clock: Clock) -> None:
        self.run_id = run_id
        self._clock = clock
        self._events: list[Event] = []
        self._seq = 0

    def append(
        self,
        event_type: str,
        *,
        step_id: str | None = None,
        attempt: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Event:
        self._seq += 1
        event = Event(
            seq=self._seq,
            ts=self._clock.now(),
            type=event_type,
            run_id=self.run_id,
            step_id=step_id,
            attempt=attempt,
            payload=payload or {},
        )
        self._events.append(event)
        return event

    @property
    def last_seq(self) -> int:
        return self._seq

    def all(self) -> list[Event]:
        return list(self._events)

    def from_seq(self, after_seq: int) -> list[Event]:
        start = min(after_seq, self._seq)
        return [event for event in self._events if event.seq > start]
