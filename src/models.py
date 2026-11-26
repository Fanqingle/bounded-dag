"""Request and plan models for the DAG executor."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

StepState = Literal[
    "PENDING",
    "RUNNING",
    "SUCCEEDED",
    "FAILED",
    "SKIPPED",
    "CANCELLED",
]
RunStatus = Literal["SUCCEEDED", "FAILED", "PARTIAL", "CANCELLED"]


class StepSpec(BaseModel):
    """One node in the execution graph.

    ``tool`` stays a plain string on purpose: structured ``unknown_tool`` errors
    are produced by validation.py instead of by pydantic's generic parser.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    deps_policy: str = "all"
    required: bool = True
    max_attempts: int = 3
    timeout_ms: int = 2000


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    steps: list[StepSpec]


class ToolConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latency_ms: int = 400
    failure_rate: float = 0.0


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: Plan
    n: int = 2
    tools: dict[str, ToolConfig] = Field(default_factory=dict)
    time_scale: float = 1.0
