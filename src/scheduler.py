"""Bounded-concurrency DAG executor with retries, failure policies and cancellation."""

from __future__ import annotations

import asyncio
import hashlib
import random
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Any

from .events import Clock, Event, EventLog, RealClock
from .models import RunRequest, RunStatus, StepSpec, StepState
from .tools import SimulatedTools, ToolError
from .validation import validate, validate_request

TERMINAL = {"SUCCEEDED", "FAILED", "SKIPPED", "CANCELLED"}
BAD_STATES = {"FAILED", "SKIPPED"}
NON_TERMINAL = {"PENDING", "RUNNING"}


class PlanRejected(Exception):
    def __init__(self, errors: list[dict[str, Any]]) -> None:
        super().__init__("plan rejected")
        self.errors = errors


@dataclass
class RunResult:
    run_id: str
    status: RunStatus
    n: int
    final_text: str | None
    states: dict[str, StepState]
    attempts: dict[str, int]
    next_attempt_at: dict[str, int | None]
    events: list[Event]

    @property
    def last_seq(self) -> int:
        return self.events[-1].seq if self.events else 0

    def snapshot(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "n": self.n,
            "steps": [
                {
                    "id": step_id,
                    "state": self.states[step_id],
                    "attempts": self.attempts[step_id],
                    "next_attempt_at": self.next_attempt_at[step_id],
                }
                for step_id in self.states
            ],
            "final_text": self.final_text if self.final_text else None,
            "last_seq": self.last_seq,
        }


def _satisfied(step: StepSpec, states: dict[str, StepState]) -> bool:
    dep_states = [states[dep] for dep in step.depends_on]
    if not dep_states:
        return True
    succeeded = sum(1 for state in dep_states if state == "SUCCEEDED")
    policy = step.deps_policy
    if policy == "all":
        return succeeded == len(dep_states)
    if policy == "any":
        return succeeded >= 1
    return succeeded >= int(policy.split(":", 1)[1])


def _final_text(
    steps: dict[str, StepSpec], states: dict[str, StepState], status: RunStatus
) -> str | None:
    if status == "SUCCEEDED":
        return "已完成三家竞品对比。"
    bad = [step_id for step_id in steps if states[step_id] in BAD_STATES]
    if status == "PARTIAL":
        labels: list[str] = []
        for step_id in bad:
            step = steps[step_id]
            query = step.args.get("q")
            labels.append(f"竞品 {query}" if step.tool == "search" and query else step_id)
        succeeded = [
            str(steps[step_id].args.get("q"))
            for step_id in steps
            if states[step_id] == "SUCCEEDED"
            and steps[step_id].tool == "search"
            and steps[step_id].args.get("q")
        ]
        tail = f"以下对比仅含 {'、'.join(succeeded)}" if succeeded else "以下对比仅含其余结果"
        return f"{'、'.join(labels)} 的资料未查到，{tail}。"
    first = bad[0] if bad else "unknown"
    return f"关键步骤 {steps[first].tool if first in steps else first} 未能完成，本次未生成海报。"


class Run:
    """A single execution. Call cancel() from another task or callback."""

    def __init__(
        self,
        request: RunRequest,
        *,
        clock: Clock | None = None,
        seed: int | None = None,
    ) -> None:
        self.request = request
        self.clock = clock or RealClock()
        self.rng = random.Random(seed)
        self.run_id = uuid.uuid4().hex[:12]
        self.log = EventLog(self.run_id, self.clock)
        self._cancel_requested = False
        self._active_tasks: set[asyncio.Task] = set()

    def cancel(self) -> None:
        self._cancel_requested = True
        for task in list(self._active_tasks):
            if not task.done():
                task.cancel()

    async def execute(self) -> RunResult:
        errors = validate_request(self.request) + validate(self.request.plan)
        if errors:
            raise PlanRejected(errors)

        steps = {step.id: step for step in self.request.plan.steps}
        states: dict[str, StepState] = {step_id: "PENDING" for step_id in steps}
        attempts = {step_id: 0 for step_id in steps}
        next_attempt_at: dict[str, int | None] = {step_id: None for step_id in steps}
        waiting_retry: set[str] = set()
        enqueued: set[str] = set()
        ready: deque[str] = deque()
        tools = SimulatedTools(
            self.request.tools, self.request.time_scale, self.clock, self.rng
        )
        self.probe = tools.probe
        semaphore = asyncio.Semaphore(self.request.n)
        self.log.append("run_started", payload={"n": self.request.n})

        def enqueue(step_id: str) -> None:
            ready.append(step_id)
            enqueued.add(step_id)
            self.log.append("step_queued", step_id=step_id, payload={})

        def refresh() -> None:
            changed = True
            while changed:
                changed = False
                for step in steps.values():
                    step_id = step.id
                    if (
                        states[step_id] != "PENDING"
                        or step_id in waiting_retry
                        or step_id in enqueued
                    ):
                        continue
                    dep_states = [states[dep] for dep in step.depends_on]
                    if any(state not in TERMINAL for state in dep_states):
                        continue
                    if _satisfied(step, states):
                        enqueue(step_id)
                    else:
                        states[step_id] = "SKIPPED"
                        self.log.append(
                            "step_skipped",
                            step_id=step_id,
                            payload={"reason": f"deps_policy={step.deps_policy} not satisfied"},
                        )
                        changed = True

        async def attempt(step_id: str) -> tuple[str, float]:
            step = steps[step_id]
            error: str | None = None
            started_at = self.clock.now()
            await semaphore.acquire()
            try:
                attempts[step_id] += 1
                current = attempts[step_id]
                states[step_id] = "RUNNING"
                self.log.append(
                    "step_started", step_id=step_id, attempt=current,
                    payload={"attempt": current},
                )
                try:
                    result = await tools.call(step.tool, step.args, step.timeout_ms)
                except ToolError as exc:
                    error = str(exc)
                except asyncio.CancelledError:
                    raise
            finally:
                semaphore.release()

            if self._cancel_requested:
                return "CANCELLED", 0.0
            if error is None:
                states[step_id] = "SUCCEEDED"
                digest = hashlib.sha256(repr(result).encode()).hexdigest()[:12]
                self.log.append(
                    "step_succeeded",
                    step_id=step_id,
                    attempt=attempts[step_id],
                    payload={
                        "duration_ms": self.clock.now() - started_at,
                        "result_digest": digest,
                    },
                )
                return "SUCCEEDED", 0.0
            if attempts[step_id] >= step.max_attempts:
                states[step_id] = "FAILED"
                self.log.append(
                    "step_failed",
                    step_id=step_id,
                    attempt=attempts[step_id],
                    payload={"attempts": attempts[step_id], "error": error},
                )
                return "FAILED", 0.0

            base = min(1000, 100 * 2 ** (attempts[step_id] - 1))
            delay_ms = self.rng.randint(0, base) * self.request.time_scale
            states[step_id] = "PENDING"
            next_attempt_at[step_id] = int(self.clock.now() + delay_ms)
            self.log.append(
                "step_retry_scheduled",
                step_id=step_id,
                attempt=attempts[step_id],
                payload={
                    "attempt": attempts[step_id],
                    "retry_after_ms": delay_ms,
                    "next_attempt": attempts[step_id] + 1,
                },
            )
            return "RETRY", delay_ms

        refresh()
        running: dict[asyncio.Task, str] = {}
        timers: dict[asyncio.Task, str] = {}

        while True:
            if self._cancel_requested:
                break
            while ready and len(running) < self.request.n:
                step_id = ready.popleft()
                task = asyncio.create_task(attempt(step_id))
                running[task] = step_id
                self._active_tasks.add(task)

            if not running and not timers:
                break

            done, _ = await asyncio.wait(
                set(running) | set(timers), return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                self._active_tasks.discard(task)
                if task in timers:
                    step_id = timers.pop(task)
                    if not self._cancel_requested:
                        waiting_retry.discard(step_id)
                        next_attempt_at[step_id] = None
                        enqueue(step_id)
                    continue

                step_id = running.pop(task)
                try:
                    outcome, delay_ms = task.result()
                except asyncio.CancelledError:
                    continue
                if outcome == "RETRY":
                    waiting_retry.add(step_id)

                    async def wait_retry(
                        delay: float = delay_ms, target: str = step_id
                    ) -> str:
                        await self.clock.sleep(delay)
                        return target

                    timer = asyncio.create_task(wait_retry())
                    timers[timer] = step_id
                    self._active_tasks.add(timer)
                else:
                    enqueued.discard(step_id)
                refresh()

        for task in list(self._active_tasks):
            if not task.done():
                task.cancel()
        if self._active_tasks:
            await asyncio.gather(*self._active_tasks, return_exceptions=True)

        if self._cancel_requested:
            for step_id, state in states.items():
                if state in NON_TERMINAL:
                    self.log.append(
                        "step_cancelled",
                        step_id=step_id,
                        payload={"reason": "run_cancelled"},
                    )
                    states[step_id] = "CANCELLED"
            status: RunStatus = "CANCELLED"
        elif any(
            steps[step_id].required and states[step_id] in BAD_STATES for step_id in steps
        ):
            status = "FAILED"
        elif any(states[step_id] in BAD_STATES for step_id in steps):
            status = "PARTIAL"
        else:
            status = "SUCCEEDED"

        final_text = _final_text(steps, states, status)
        self.log.append(
            "run_finished", payload={"status": status, "final_text": final_text}
        )
        return RunResult(
            run_id=self.run_id,
            status=status,
            n=self.request.n,
            final_text=final_text,
            states=states,
            attempts=attempts,
            next_attempt_at=next_attempt_at,
            events=self.log.all(),
        )


async def run(request: RunRequest, **kwargs: Any) -> RunResult:
    """Convenience wrapper for callers that do not need a cancellation handle."""
    return await Run(request, **kwargs).execute()
