"""Plan rejection must be structured and order-stable."""

from __future__ import annotations

import asyncio

import pytest

from conftest import make_plan, make_step
from src.models import RunRequest
from src.scheduler import PlanRejected, run


def test_cycle_rejected() -> None:
    plan = make_plan(
        [
            make_step("s1", depends_on=["s2"]),
            make_step("s2", depends_on=["s3"]),
            make_step("s3", depends_on=["s1"]),
        ]
    )
    with pytest.raises(PlanRejected) as caught:
        asyncio.run(run(RunRequest(plan=plan)))
    assert caught.value.errors == [
        {"error": "cycle_detected", "step_id": "s1", "path": ["s1", "s2", "s3", "s1"]}
    ]


def test_missing_dependency_rejected() -> None:
    plan = make_plan([make_step("s1", depends_on=["s9"])])
    with pytest.raises(PlanRejected) as caught:
        asyncio.run(run(RunRequest(plan=plan)))
    assert caught.value.errors == [
        {"error": "missing_dependency", "step_id": "s1", "missing": "s9"}
    ]
