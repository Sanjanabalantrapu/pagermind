"""Memory layer.

`HindsightMemory` is the real implementation and the one PagerMind is built around.
`LocalMemory` is a tiny keyword-matching stand-in used only by the test-suite and by
`MEMORY_BACKEND=local` for offline development. It has none of Hindsight's fact
extraction, entity graph, temporal search, or observation consolidation.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger("pagermind.memory")

BANK_MISSION = (
    "I am PagerMind, the on-call memory for an e-commerce SRE team. I remember every "
    "production incident: symptoms, exact log signatures, root causes, which remediation "
    "steps worked, which ones failed or made things worse, who fixed it and how fast. "
    "I also remember team runbooks, owners, policies and each engineer's preferences. "
    "I use this to brief the on-call engineer in seconds and to stop the team repeating "
    "mistakes."
)

RETAIN_MISSION = (
    "Extract service names, log signatures and error strings verbatim, root causes, and "
    "every remediation step together with whether it WORKED or FAILED. Keep exact commands. "
    "Keep people's names and their role in the incident."
)

OBSERVATIONS_MISSION = (
    "Consolidate recurring failure patterns per service (e.g. the same root cause seen "
    "several times), remediation steps that repeatedly work or repeatedly fail, and "
    "stable team preferences."
)


@dataclass
class Memory:
    text: str
    type: str = "world"  # world | experience | observation
    tags: list[str] = field(default_factory=list)
    document_id: str | None = None
    when: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MemoryStore(Protocol):
    def ensure_bank(self) -> None: ...

    def retain(
        self,
        content: str,
        *,
        context: str,
        tags: list[str],
        timestamp: datetime | None = None,
        document_id: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> None: ...

    def recall(
        self,
        query: str,
        *,
        tags: list[str] | None = None,
        types: list[str] | None = None,
        max_tokens: int = 2048,
        budget: str = "mid",
    ) -> list[Memory]: ...

    def reflect(self, query: str, *, tags: list[str] | None = None, context: str | None = None) -> str: ...

    def count(self) -> int: ...


# --------------------------------------------------------------------------------------
# Hindsight (production)
# --------------------------------------------------------------------------------------


class HindsightMemory:
    """Thin, typed wrapper around the official `hindsight-client`."""

    def __init__(self, bank_id: str, base_url: str, api_key: str | None = None, client: Any = None):
        if client is None:
            from hindsight_client import Hindsight  # imported lazily so tests don't need a server

            client = Hindsight(base_url=base_url, api_key=api_key, timeout=120.0)
        self.client = client
        self.bank_id = bank_id

    def ensure_bank(self) -> None:
        try:
            self.client.create_bank(
                bank_id=self.bank_id,
                name="PagerMind on-call memory",
                mission=BANK_MISSION,
                retain_mission=RETAIN_MISSION,
                observations_mission=OBSERVATIONS_MISSION,
                enable_observations=True,
                # Incident response wants a skeptical, literal reader: don't assume a
                # fix worked unless the record says so.
                disposition_skepticism=4,
                disposition_literalism=4,
                disposition_empathy=2,
            )
        except Exception as exc:  # bank already exists, or server rejects an optional field
            log.info("create_bank skipped (%s); continuing with existing bank", exc)

    def retain(self, content, *, context, tags, timestamp=None, document_id=None, metadata=None) -> None:
        self.client.retain(
            bank_id=self.bank_id,
            content=content,
            context=context,
            tags=tags,
            timestamp=timestamp,
            document_id=document_id,
            metadata=metadata,
        )

    def recall(self, query, *, tags=None, types=None, max_tokens=2048, budget="mid") -> list[Memory]:
        resp = self.client.recall(
            bank_id=self.bank_id,
            query=query[:1500],  # Hindsight rejects queries over 500 tokens
            tags=tags,
            tags_match="any",  # service-scoped memories + untagged global ones
            types=types,
            max_tokens=max_tokens,
            budget=budget,
            prefer_observations=True,
        )
        out: list[Memory] = []
        for r in resp.results or []:
            out.append(
                Memory(
                    text=r.text,
                    type=getattr(r, "type", None) or "world",
                    tags=list(getattr(r, "tags", None) or []),
                    document_id=getattr(r, "document_id", None),
                    when=str(getattr(r, "occurred_start", None) or getattr(r, "mentioned_at", None) or "") or None,
                )
            )
        return out

    def reflect(self, query, *, tags=None, context=None) -> str:
        resp = self.client.reflect(
            bank_id=self.bank_id, query=query, tags=tags, tags_match="any", context=context, budget="mid"
        )
        return resp.text

    def count(self) -> int:
        try:
            resp = self.client.list_memories(bank_id=self.bank_id, limit=1)
            return int(getattr(resp, "total", 0) or 0)
        except Exception:
            return -1


# --------------------------------------------------------------------------------------
# Local stand-in (tests / offline only)
# --------------------------------------------------------------------------------------

_WORD = re.compile(r"[a-z0-9_.\-]+")
_STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "was", "with", "at", "by", "it", "from"}


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 2}


class LocalMemory:
    """Keyword-overlap memory persisted to a JSON file. Not a Hindsight replacement."""

    def __init__(self, path: Path | None = None):
        self.path = path
        self.items: list[dict[str, Any]] = []
        if path and path.exists():
            self.items = json.loads(path.read_text())

    def ensure_bank(self) -> None:
        return None

    def _save(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.items, indent=1))

    def retain(self, content, *, context, tags, timestamp=None, document_id=None, metadata=None) -> None:
        kind = "experience" if context in {"triage feedback", "agent triage"} else "world"
        when = (timestamp or datetime.now(timezone.utc)).isoformat()
        self.items.append(
            {"text": content, "type": kind, "tags": tags, "document_id": document_id, "when": when}
        )
        self._save()

    def recall(self, query, *, tags=None, types=None, max_tokens=2048, budget="mid") -> list[Memory]:
        q = _tokens(query)
        scored = []
        for it in self.items:
            if types and it["type"] not in types:
                continue
            if tags and it["tags"] and not set(tags) & set(it["tags"]):
                continue
            score = len(q & _tokens(it["text"]))
            if score:
                scored.append((score, it["when"], it))
        scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
        out, used = [], 0
        for _, _, it in scored:
            cost = len(it["text"]) // 4
            if used + cost > max_tokens and out:
                break
            used += cost
            out.append(Memory(**{k: it[k] for k in ("text", "type", "tags", "document_id", "when")}))
        return out

    def reflect(self, query, *, tags=None, context=None) -> str:
        hits = self.recall(query, tags=tags, max_tokens=1200)
        if not hits:
            return "I have no memories relevant to that yet."
        return "Based on what I remember:\n" + "\n".join(f"- {m.text}" for m in hits[:6])

    def count(self) -> int:
        return len(self.items)


def build_memory(settings) -> MemoryStore:
    if settings.memory_backend == "local":
        return LocalMemory(Path(settings.bank_id + ".local.json"))
    return HindsightMemory(settings.bank_id, settings.hindsight_url, settings.hindsight_api_key)
