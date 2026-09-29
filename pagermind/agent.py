"""The PagerMind incident-response agent.

Flow for every alert:
  1. RECALL  - pull similar past incidents, what worked / failed, and team context
               from Hindsight (three targeted recalls, service-scoped with tags).
  2. REASON  - the LLM writes a triage brief; it may call memory tools for more.
  3. RETAIN  - the brief itself is retained as an experience memory.
Later, when the engineer reports which step worked, that feedback is retained too,
so the next similar alert ranks proven fixes first and warns about failed ones.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from .knowledge import feedback_to_memory, service_tags, triage_to_memory
from .llm import LLMReply
from .memory import Memory, MemoryStore

log = logging.getLogger("pagermind.agent")

SYSTEM_PROMPT = """You are PagerMind, an incident-response copilot for an on-call SRE.
You get a live alert and, when available, memories from the team's incident history.

Write a triage brief in Markdown with these sections, in this order:
**Likely cause** - one or two sentences. If a past incident matches, say which (cite INC-IDs).
**Do first** - numbered, concrete commands or actions. Prefer steps that WORKED before.
**Do NOT do** - steps that failed or made things worse in past incidents, with the INC-ID. Omit the section if none.
**Page / notify** - owners or channels, only if memory names them.
**Why I think this** - one line per memory you relied on.

Rules:
- Never invent incident IDs, people, commands or history. If memory has nothing relevant, say so and give generic advice.
- Respect team preferences and policies found in memory (e.g. what to put first, change freezes).
- Be brief. The reader is under pressure at 2am.
- You may call the memory tools if the provided memories are not enough; at most two calls."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_incident_memory",
            "description": "Search the team's incident memory (past incidents, fixes that worked or failed, feedback).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to look for, e.g. an error string or symptom."},
                    "service": {"type": "string", "description": "Optional service name to scope the search."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_team_memory",
            "description": "Ask a reasoning question over the whole memory bank, e.g. 'what keeps breaking checkout-api?'",
            "parameters": {
                "type": "object",
                "properties": {"question": {"type": "string"}},
                "required": ["question"],
            },
        },
    },
]

MAX_TOOL_ROUNDS = 3


@dataclass
class TriageResult:
    alert: dict[str, Any]
    memory_enabled: bool
    answer: str
    memories: list[dict[str, Any]] = field(default_factory=list)
    tool_trace: list[dict[str, Any]] = field(default_factory=list)
    model: str = ""
    degraded: bool = False
    seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _format_memories(mems: list[Memory]) -> str:
    lines = []
    for m in mems:
        meta = [m.type]
        if m.document_id:
            meta.append(m.document_id)
        if m.when:
            meta.append(m.when[:10])
        lines.append(f"- [{' | '.join(meta)}] {m.text}")
    return "\n".join(lines)


def _dedupe(mems: list[Memory]) -> list[Memory]:
    seen, out = set(), []
    for m in mems:
        key = m.text.strip().lower()
        if key not in seen:
            seen.add(key)
            out.append(m)
    return out


class IncidentAgent:
    def __init__(self, memory: MemoryStore, llm: Any):
        self.memory = memory
        self.llm = llm

    # ---------------------------------------------------------------- recall
    def gather_context(self, alert: dict[str, Any]) -> list[Memory]:
        svc = alert["service"]
        tags = service_tags(svc, alert.get("details", ""))
        signal = f"{alert['title']}. {alert.get('details', '')}"
        similar = self.memory.recall(signal, tags=tags, max_tokens=1800, budget="mid")
        outcomes = self.memory.recall(
            f"Which remediation steps worked and which did not work or made things worse for {svc}: {alert['title']}",
            tags=tags,
            types=["experience", "observation", "world"],
            max_tokens=900,
        )
        team = self.memory.recall(
            f"Runbook commands, owners to page, policies and on-call preferences for {svc}",
            tags=tags,
            max_tokens=600,
            budget="low",
        )
        # Team-wide preferences are untagged-by-service; fetch them explicitly.
        prefs = self.memory.recall(
            "How does the SRE lead want triage briefs structured?", tags=["kind:preference"], max_tokens=300, budget="low"
        )
        return _dedupe(similar + outcomes + team + prefs)

    # ---------------------------------------------------------------- tools
    def _run_tool(self, name: str, args: dict[str, Any]) -> str:
        if name == "search_incident_memory":
            q = str(args.get("query") or "").strip()
            if not q:
                return "error: 'query' is required"
            svc = args.get("service")
            tags = [f"service:{svc}"] if svc else None
            hits = self.memory.recall(q, tags=tags, max_tokens=900)
            return _format_memories(hits) or "no matching memories"
        if name == "ask_team_memory":
            q = str(args.get("question") or "").strip()
            if not q:
                return "error: 'question' is required"
            return self.memory.reflect(q)
        return f"error: unknown tool '{name}'. Available: search_incident_memory, ask_team_memory"

    # ---------------------------------------------------------------- triage
    def triage(self, alert: dict[str, Any], *, use_memory: bool = True, remember: bool = True) -> TriageResult:
        t0 = time.time()
        mems = self.gather_context(alert) if use_memory else []
        mem_block = _format_memories(mems) if mems else (
            "(no memories: memory is disabled)" if not use_memory else "(no memories found)"
        )
        user = (
            f"## Alert\nService: {alert['service']}\nSeverity: {alert.get('severity', 'unknown')}\n"
            f"Title: {alert['title']}\nDetails: {alert.get('details', '')}\n"
            f"Time: {datetime.now(timezone.utc).isoformat(timespec='minutes')}\n\n## Memory\n{mem_block}"
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]
        tools = TOOLS if use_memory else None
        trace: list[dict[str, Any]] = []
        reply: LLMReply | None = None
        degraded = False

        for _round in range(MAX_TOOL_ROUNDS + 1):
            allow_tools = tools if _round < MAX_TOOL_ROUNDS else None
            reply = self.llm.complete(messages, allow_tools)
            degraded = degraded or reply.degraded
            if not reply.tool_calls:
                break
            messages.append(
                {
                    "role": "assistant",
                    "content": reply.content or "",
                    "tool_calls": [
                        {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.raw_arguments or json.dumps(c.arguments)}}
                        for c in reply.tool_calls
                    ],
                }
            )
            for call in reply.tool_calls:
                if call.parse_error:
                    result = f"error: {call.parse_error}. Send arguments as a JSON object."
                else:
                    try:
                        result = self._run_tool(call.name, call.arguments)
                    except Exception as exc:  # memory backend hiccup must not kill triage
                        log.exception("tool %s failed", call.name)
                        result = f"error: tool failed ({type(exc).__name__}). Continue with what you have."
                trace.append({"tool": call.name, "args": call.arguments, "result_preview": result[:300]})
                messages.append({"role": "tool", "tool_call_id": call.id, "content": result[:6000]})

        answer = (reply.content if reply else "") or "PagerMind could not produce a brief. Fall back to the runbook."
        if use_memory and remember:
            try:
                self.memory.retain(**triage_to_memory(alert=alert, summary=answer))
            except Exception:
                log.exception("retaining triage failed (non-fatal)")

        return TriageResult(
            alert=alert,
            memory_enabled=use_memory,
            answer=answer,
            memories=[m.to_dict() for m in mems],
            tool_trace=trace,
            model=getattr(reply, "model", "") or getattr(self.llm, "name", ""),
            degraded=degraded,
            seconds=round(time.time() - t0, 2),
        )

    # ---------------------------------------------------------------- learn
    def record_feedback(self, alert: dict[str, Any], *, step: str, worked: bool, engineer: str, note: str = "") -> dict[str, Any]:
        if not step.strip():
            raise ValueError("step is required")
        item = feedback_to_memory(alert=alert, step=step.strip(), worked=worked, engineer=engineer.strip() or "on-call", note=note.strip())
        self.memory.retain(**item)
        return item

    def ask(self, question: str) -> str:
        if not question.strip():
            raise ValueError("question is required")
        return self.memory.reflect(question.strip())
