"""Build the optional frontend and serve the API together with static pages."""

from __future__ import annotations

import subprocess
from pathlib import Path

import uvicorn
from fastapi.staticfiles import StaticFiles

from src.api import app

ROOT = Path(__file__).resolve().parent


def build_frontend() -> Path | None:
    frontend = ROOT / "frontend"
    if not frontend.exists():
        print("frontend directory not found; skipping static mount")
        return None
    if (frontend / "package.json").exists():
        if not (frontend / "node_modules").exists():
            subprocess.run(
                ["npm", "install", "--no-audit", "--no-fund"],
                cwd=frontend,
                check=True,
            )
        subprocess.run(["npm", "run", "build"], cwd=frontend, check=True)
    dist = frontend / "dist"
    if not dist.exists():
        print("frontend build output not found; skipping static mount")
        return None
    return dist


def main() -> None:
    dist = build_frontend()
    if dist is not None:
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="static")
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
