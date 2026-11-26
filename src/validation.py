"""Structured, order-stable validation for plans and run requests."""

from __future__ import annotations

import re
from typing import Any

from .models import Plan, RunRequest

VALID_TOOLS = {"search", "summarize", "generate_image"}
_POLICY_PATTERN = re.compile(r"^(all|any|quorum:([1-9][0-9]*))$")


def validate_request(request: RunRequest) -> list[dict[str, Any]]:
    """Validate request-level limits that the plan validator does not own."""
    errors: list[dict[str, Any]] = []
    if request.n < 1:
        errors.append({"error": "invalid_concurrency", "value": request.n})
    if not 0 < request.time_scale <= 10:
        errors.append({"error": "invalid_time_scale", "value": request.time_scale})
    return errors


def validate(plan: Plan) -> list[dict[str, Any]]:
    """Validate in a fixed stage order; stop at the first failing stage.

    Short-circuiting keeps later stages from reasoning about invalid ids.
    """
    steps = plan.steps
    ids = [step.id for step in steps]

    duplicates = sorted({step_id for step_id in ids if ids.count(step_id) > 1})
    if duplicates:
        return [
            {"error": "duplicate_step_id", "step_id": step_id}
            for step_id in duplicates
        ]

    errors: list[dict[str, Any]] = []
    for step in steps:
        for dep in step.depends_on:
            if dep == step.id:
                errors.append({"error": "self_dependency", "step_id": step.id})
                break
    if errors:
        return errors

    known = set(ids)
    for step in steps:
        for dep in step.depends_on:
            if dep not in known:
                errors.append(
                    {"error": "missing_dependency", "step_id": step.id, "missing": dep}
                )
    if errors:
        return errors

    for step in steps:
        if step.tool not in VALID_TOOLS:
            errors.append(
                {"error": "unknown_tool", "step_id": step.id, "tool": step.tool}
            )
    if errors:
        return errors

    for step in steps:
        match = _POLICY_PATTERN.match(step.deps_policy)
        if match is None:
            errors.append(
                {
                    "error": "invalid_deps_policy",
                    "step_id": step.id,
                    "value": step.deps_policy,
                }
            )
            continue
        if match.group(2) is not None:
            k = int(match.group(2))
            if k > len(step.depends_on):
                errors.append(
                    {"error": "invalid_quorum", "step_id": step.id, "k": k}
                )
    if errors:
        return errors

    path = _find_cycle_path(ids, {step.id: list(step.depends_on) for step in steps})
    if path is not None:
        return [{"error": "cycle_detected", "step_id": path[0], "path": path}]
    return []


def _find_cycle_path(ids: list[str], deps: dict[str, list[str]]) -> list[str] | None:
    """Return one cycle as [start, ..., start] with the smallest id first."""
    remaining = set(ids)
    indegree = {step_id: len(deps[step_id]) for step_id in ids}
    followers: dict[str, list[str]] = {step_id: [] for step_id in ids}
    for step_id in ids:
        for dep in deps[step_id]:
            followers[dep].append(step_id)

    queue = [step_id for step_id in ids if indegree[step_id] == 0]
    while queue:
        node = queue.pop()
        for follower in followers[node]:
            indegree[follower] -= 1
            if indegree[follower] == 0:
                queue.append(follower)

    remaining = {step_id for step_id in ids if indegree[step_id] > 0}
    if not remaining:
        return None

    best: list[str] | None = None
    for start in sorted(remaining):
        path: list[str] = []
        on_path: set[str] = set()

        def visit(node: str) -> None:
            nonlocal best
            path.append(node)
            on_path.add(node)
            for dep in sorted(deps[node]):
                if dep not in remaining:
                    continue
                if dep in on_path:
                    cycle = path[path.index(dep) :]
                    pivot = cycle.index(min(cycle))
                    rotated = cycle[pivot:] + cycle[:pivot]
                    candidate = rotated + [rotated[0]]
                    if best is None or candidate < best:
                        best = candidate
                else:
                    visit(dep)
            path.pop()
            on_path.remove(node)

        visit(start)
    return best
