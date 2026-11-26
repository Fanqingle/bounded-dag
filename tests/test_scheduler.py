"""Ordering, bounded concurrency, retry budget, cancellation and propagation."""

from __future__ import annotations

import asyncio

import pytest

from conftest import GatedClock, FakeClock, make_plan, make_step, make_tools
from src.events import Event
from src.models import RunRequest, ToolConfig
from src.scheduler import Run, run


def _events(result) -> list[Event]:
    return result.events


def _seq(result, event_type: str, step_id: str, attempt: int | None = None) -> int:
    matches = [
        event.seq
        for event in result.events
        if event.type == event_type
        and event.step_id == step_id
        and (attempt is None or event.attempt == attempt)
    ]
    assert len(matches) == 1
    return matches[0]


def test_dependency_order(clock: FakeClock) -> None:
    plan = make_plan(
        [
            make_step("s1", args={"q": "A"}),
            make_step("s2", args={"q": "B"}),
            make_step("s3", args={"q": "C"}),
            make_step(
                "sum",
                "summarize",
                depends_on=["s1", "s2", "s3"],
                args={"items": ["A", "B", "C"]},
            ),
            make_step("img", "generate_image", depends_on=["sum"]),
        ]
    )
    result = asyncio.run(
        run(RunRequest(plan=plan, n=3, tools=make_tools()), clock=clock, seed=1)
    )
    assert result.status == "SUCCEEDED"
    sum_started = _seq(result, "step_started", "sum")
    for step_id in ("s1", "s2", "s3"):
        assert _seq(result, "step_succeeded", step_id) < sum_started
    assert _seq(result, "step_succeeded", "sum") < _seq(result, "step_started", "img")


@pytest.mark.parametrize("n", [1, 2, 3])
def test_concurrency_bound(n: int, clock: FakeClock) -> None:
    plan = make_plan([make_step(f"s{i}") for i in range(6)])
    handle = Run(
        RunRequest(plan=plan, n=n, tools=make_tools(latency_ms=10)), clock=clock, seed=1
    )
    result = asyncio.run(handle.execute())
    assert result.status == "SUCCEEDED"
    assert handle.probe.peak <= n
    assert handle.probe.peak == n
    assert handle.probe.current == 0


def test_retry_budget(clock: FakeClock) -> None:
    plan = make_plan([make_step("s1")])
    result = asyncio.run(
        run(
            RunRequest(
                plan=plan, n=1, tools=make_tools(latency_ms=10, failure_rate=1.0)
            ),
            clock=clock,
            seed=1,
        )
    )
    assert result.attempts["s1"] == 3
    retries = [event for event in result.events if event.type == "step_retry_scheduled"]
    assert len(retries) == 2
    assert [event.payload["next_attempt"] for event in retries] == [2, 3]
    starts = [event for event in result.events if event.type == "step_started"]
    assert [event.attempt for event in starts] == [1, 2, 3]
    assert result.status == "FAILED"


def test_cancel_stops_new_starts() -> None:
    async def scenario():
        clock = GatedClock()
        plan = make_plan([make_step(f"s{i}") for i in range(6)])
        handle = Run(
            RunRequest(plan=plan, n=2, tools=make_tools(latency_ms=100)),
            clock=clock,
            seed=5,
        )
        task = asyncio.create_task(handle.execute())
        for _ in range(1000):
            started = [
                event for event in handle.log.all() if event.type == "step_started"
            ]
            if len(started) >= 2:
                break
            await asyncio.sleep(0)
        count_at_cancel = len(started)
        handle.cancel()
        clock.gate.set()
        result = await task
        return handle, result, count_at_cancel

    handle, result, count_at_cancel = asyncio.run(scenario())
    assert count_at_cancel == 2
    assert len([e for e in _events(result) if e.type == "step_started"]) == count_at_cancel
    assert result.status == "CANCELLED"
    assert set(result.states.values()) == {"CANCELLED"}
    assert all(task.done() for task in handle._active_tasks)


def test_backoff_releases_slot(clock: FakeClock) -> None:
    plan = make_plan(
        [
            make_step("a", args={"q": "A"}, max_attempts=2),
            make_step("b", "summarize", args={"items": ["B"]}),
        ]
    )
    tools = {
        "search": ToolConfig(latency_ms=10, failure_rate=1.0),
        "summarize": ToolConfig(latency_ms=10, failure_rate=0.0),
    }
    result = asyncio.run(
        run(RunRequest(plan=plan, n=1, tools=tools), clock=clock, seed=7)
    )
    kinds = [(event.type, event.step_id, event.attempt) for event in result.events]
    retry_at = next(
        i for i, (kind, step_id, _) in enumerate(kinds)
        if kind == "step_retry_scheduled" and step_id == "a"
    )
    peer_at = next(
        i for i, (kind, step_id, _) in enumerate(kinds)
        if kind == "step_started" and step_id == "b"
    )
    retry_at_second = next(
        i for i, (kind, step_id, attempt) in enumerate(kinds)
        if kind == "step_started" and step_id == "a" and attempt == 2
    )
    assert retry_at < peer_at < retry_at_second
    assert result.events[retry_at].payload["retry_after_ms"] > 0
    assert result.events[retry_at].payload["next_attempt"] == 2


def test_skip_propagation(clock: FakeClock) -> None:
    plan = make_plan(
        [
            make_step("s1", args={"q": "A"}),
            make_step("s2", args={"q": "B"}),
            make_step("sum", "summarize", depends_on=["s1", "s2"], max_attempts=1),
            make_step("img", "generate_image", depends_on=["sum"]),
        ]
    )
    tools = {
        "search": ToolConfig(latency_ms=10, failure_rate=1.0),
        "summarize": ToolConfig(latency_ms=10),
        "generate_image": ToolConfig(latency_ms=10),
    }
    result = asyncio.run(
        run(RunRequest(plan=plan, n=2, tools=tools), clock=clock, seed=3)
    )
    assert result.states["s1"] == "FAILED"
    assert result.states["s2"] == "FAILED"
    assert result.states["sum"] == "SKIPPED"
    assert result.states["img"] == "SKIPPED"
    assert result.status == "FAILED"
    skipped = {
        event.step_id: event.payload["reason"]
        for event in result.events
        if event.type == "step_skipped"
    }
    assert "sum" in skipped and "img" in skipped


def test_timeout_retry(clock: FakeClock) -> None:
    plan = make_plan(
        [make_step("s1", args={"q": "A"}, timeout_ms=5, max_attempts=2)]
    )
    tools = {"search": ToolConfig(latency_ms=10, failure_rate=0.0)}
    result = asyncio.run(
        run(RunRequest(plan=plan, n=1, tools=tools), clock=clock, seed=1)
    )
    assert result.attempts["s1"] == 2
    failed = [event for event in result.events if event.type == "step_failed"]
    assert len(failed) == 1
    assert "timed out" in failed[0].payload["error"]
    assert result.status == "FAILED"


def test_queue_event_present(clock: FakeClock) -> None:
    plan = make_plan(
        [
            make_step("s1", args={"q": "A"}),
            make_step("s2", "summarize", args={"items": ["A"]}, depends_on=["s1"]),
        ]
    )
    result = asyncio.run(
        run(RunRequest(plan=plan, n=1, tools=make_tools()), clock=clock, seed=1)
    )
    for step_id in ("s1", "s2"):
        queued_at = _seq(result, "step_queued", step_id)
        started_at = _seq(result, "step_started", step_id)
        assert queued_at < started_at


def test_snapshot_roundtrip(clock: FakeClock) -> None:
    plan = make_plan([make_step("s1", args={"q": "A"})])
    result = asyncio.run(
        run(RunRequest(plan=plan, n=1, tools=make_tools()), clock=clock, seed=1)
    )
    snapshot = result.snapshot()
    assert set(snapshot) == {
        "run_id", "status", "n", "steps", "final_text", "last_seq"
    }
    assert snapshot["run_id"] == result.run_id
    assert snapshot["status"] == result.status
    assert snapshot["n"] == 1
    assert snapshot["last_seq"] == result.last_seq == result.events[-1].seq
    assert snapshot["final_text"] == result.final_text == "已完成三家竞品对比。"
    assert snapshot["steps"] == [
        {"id": "s1", "state": "SUCCEEDED", "attempts": 1, "next_attempt_at": None}
    ]


def test_partial_text(clock: FakeClock) -> None:
    plan = make_plan(
        [
            make_step("s1", args={"q": "A"}),
            make_step("s2", args={"q": "B"}),
            make_step(
                "s3",
                args={"q": "C"},
                required=False,
                max_attempts=1,
                timeout_ms=1,
            ),
            make_step(
                "sum",
                "summarize",
                args={"items": ["A", "B", "C"]},
                depends_on=["s1", "s2", "s3"],
                deps_policy="quorum:2",
            ),
            make_step(
                "img",
                "generate_image",
                args={"prompt": "poster"},
                depends_on=["sum"],
            ),
        ]
    )
    result = asyncio.run(
        run(RunRequest(plan=plan, n=3, tools=make_tools(latency_ms=10)),
            clock=clock, seed=1)
    )
    assert result.status == "PARTIAL"
    assert result.states["s3"] == "FAILED"
    assert "竞品 C" in result.final_text
    assert "A、B" in result.final_text
    assert "，" in result.final_text
