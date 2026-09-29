"""FastAPI app: JSON API + a single-page on-call console."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .agent import IncidentAgent
from .config import settings
from .llm import build_llm
from .memory import build_memory
from .seed import load_json, seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("pagermind.server")

STATIC = Path(__file__).resolve().parent / "static"


class Alert(BaseModel):
    id: str | None = None
    service: str = Field(min_length=1, max_length=80)
    severity: str = "SEV2"
    title: str = Field(min_length=3, max_length=300)
    details: str = Field(default="", max_length=4000)


class TriageRequest(BaseModel):
    alert: Alert
    use_memory: bool = True


class FeedbackRequest(BaseModel):
    alert: Alert
    step: str = Field(min_length=3, max_length=500)
    worked: bool
    engineer: str = Field(default="on-call", max_length=80)
    note: str = Field(default="", max_length=1000)


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)


def create_app(agent: IncidentAgent | None = None) -> FastAPI:
    if agent is None:
        memory = build_memory(settings)
        memory.ensure_bank()
        agent = IncidentAgent(memory, build_llm(settings))
    app = FastAPI(title="PagerMind", version="1.0.0")
    app.state.agent = agent

    def _guard(fn, *args, **kwargs) -> Any:
        try:
            return fn(*args, **kwargs)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            log.exception("request failed")
            raise HTTPException(502, f"Upstream error ({type(exc).__name__}): {exc}") from exc

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/status")
    def status():
        mem = app.state.agent.memory
        return {
            "memory_backend": type(mem).__name__,
            "bank_id": getattr(mem, "bank_id", "local"),
            "memory_count": mem.count(),
            "llm": getattr(app.state.agent.llm, "name", "?"),
        }

    @app.get("/api/alerts")
    def alerts():
        return load_json("demo_alerts.json")

    @app.post("/api/seed")
    def do_seed():
        n = _guard(seed, app.state.agent.memory, verbose=False)
        return {"retained": n}

    @app.post("/api/triage")
    def triage(req: TriageRequest):
        res = _guard(app.state.agent.triage, req.alert.model_dump(), use_memory=req.use_memory)
        return res.to_dict()

    @app.post("/api/feedback")
    def feedback(req: FeedbackRequest):
        item = _guard(
            app.state.agent.record_feedback,
            req.alert.model_dump(),
            step=req.step,
            worked=req.worked,
            engineer=req.engineer,
            note=req.note,
        )
        return {"retained": item["content"], "tags": item["tags"]}

    @app.post("/api/ask")
    def ask(req: AskRequest):
        return {"answer": _guard(app.state.agent.ask, req.question)}

    return app


