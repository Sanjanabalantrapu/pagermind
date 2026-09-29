"""Load the incident history and team knowledge into the memory bank."""

from __future__ import annotations

import json
from pathlib import Path

from .knowledge import incident_to_memory
from .memory import MemoryStore

DATA = Path(__file__).resolve().parent.parent / "data"


def load_json(name: str):
    return json.loads((DATA / name).read_text())


def seed(memory: MemoryStore, *, verbose: bool = True) -> int:
    """Idempotent: each incident uses its INC-ID as document_id, so re-seeding
    replaces documents instead of duplicating them."""
    memory.ensure_bank()
    n = 0
    for inc in load_json("incidents.json"):
        memory.retain(**incident_to_memory(inc))
        n += 1
        if verbose:
            print(f"  retained {inc['id']:<9} {inc['service']:<22} {inc['title']}")
    for i, k in enumerate(load_json("team_knowledge.json")):
        memory.retain(content=k["content"], context="team knowledge", tags=k["tags"], document_id=f"team-{i}")
        n += 1
        if verbose:
            print(f"  retained team-{i:<5}  {k['content'][:70]}...")
    return n
