"""FastAPI endpoints for run submission, snapshots and SSE replay."""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .models import RunRequest
from .scheduler import Run
from .validation import validate, validate_request

app = FastAPI()

_runs: dict[str, Run] = {}
_tasks: dict[str, asyncio.Task] = {}


def _structured_errors(request: RunRequest) -> list[dict[str, Any]]:
    return validate_request(request) + validate(request.plan)


def _not_found() -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": "run_not_found"})


@app.post("/api/runs")
async def create_run(request: RunRequest) -> JSONResponse:
    errors = _structured_errors(request)
    if errors:
        return JSONResponse(status_code=422, content={"errors": errors})
    handle = Run(request)
    _runs[handle.run_id] = handle
    _tasks[handle.run_id] = asyncio.create_task(handle.execute())
    return JSONResponse(status_code=202, content={"run_id": handle.run_id})


@app.get("/api/runs/{run_id}/events")
async def stream_events(run_id: str, request: Request) -> StreamingResponse:
    handle = _runs.get(run_id)
    if handle is None:
        return _not_found()

    raw = request.headers.get("last-event-id")
    try:
        last_event_id = int(raw) if raw is not None else 0
    except ValueError:
        last_event_id = 0

    async def generator() -> AsyncIterator[str]:
        cursor = last_event_id
        while True:
            for event in handle.log.from_seq(cursor):
                cursor = event.seq
                yield (
                    f"id: {event.sse_id}\n"
                    f"data: {json.dumps(event.as_dict(), ensure_ascii=False)}\n\n"
                )
            task = _tasks.get(run_id)
            if task is not None and task.done() and cursor >= handle.log.last_seq:
                break
            await asyncio.sleep(0.02)

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(
        generator(), media_type="text/event-stream", headers=headers
    )


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str) -> JSONResponse:
    handle = _runs.get(run_id)
    if handle is None:
        return _not_found()
    return JSONResponse(content=handle.snapshot())


@app.post("/api/runs/{run_id}/cancel")
async def cancel_run(run_id: str) -> JSONResponse:
    handle = _runs.get(run_id)
    if handle is None:
        return _not_found()
    handle.cancel()
    return JSONResponse(content={"run_id": run_id, "status": "CANCELLED"})


@app.get("/api/example")
async def example() -> JSONResponse:
    request = RunRequest(
        plan={
            "steps": [
                {"id": "s1", "tool": "search", "args": {"q": "A"}},
                {"id": "s2", "tool": "search", "args": {"q": "B"}},
                {
                    "id": "s3",
                    "tool": "search",
                    "args": {"q": "C"},
                    "required": False,
                },
                {
                    "id": "sum",
                    "tool": "summarize",
                    "args": {"items": ["A", "B", "C"]},
                    "depends_on": ["s1", "s2", "s3"],
                    "deps_policy": "any",
                },
                {
                    "id": "img",
                    "tool": "generate_image",
                    "args": {"prompt": "comparison poster"},
                    "depends_on": ["sum"],
                },
            ]
        },
        n=2,
        tools={
            "search": {"latency_ms": 400, "failure_rate": 0.0},
            "summarize": {"latency_ms": 300, "failure_rate": 0.0},
            "generate_image": {"latency_ms": 900, "failure_rate": 0.0},
        },
        time_scale=1.0,
    )
    return JSONResponse(content=request.model_dump(mode="json"))
