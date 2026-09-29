"""The 60-second story, in the terminal.

    python -m scripts.demo            # uses Hindsight + Groq from your .env
    MEMORY_BACKEND=local python -m scripts.demo   # offline dry run

Act 1  the same alert, triaged without memory and with memory
Act 2  the engineer reports what worked; PagerMind retains it
Act 3  a reflect() question over the whole history
"""

import json
import sys
import textwrap

from pagermind.agent import IncidentAgent
from pagermind.config import settings
from pagermind.llm import build_llm
from pagermind.memory import build_memory
from pagermind.seed import load_json, seed


def box(title: str, body: str) -> None:
    bar = "=" * 78
    print(f"\n{bar}\n{title}\n{bar}")
    for para in body.splitlines():
        print(textwrap.fill(para, 100, subsequent_indent="   ") if para.strip() else "")


def main() -> int:
    mem = build_memory(settings)
    agent = IncidentAgent(mem, build_llm(settings))
    if "--no-seed" not in sys.argv:
        print(f"Seeding '{settings.bank_id}' ({type(mem).__name__}) ...")
        seed(mem, verbose=False)

    alert = load_json("demo_alerts.json")[0]
    box("INCOMING ALERT", json.dumps(alert, indent=2))

    before = agent.triage(alert, use_memory=False)
    box("ACT 1a  WITHOUT MEMORY (stateless LLM)", before.answer)

    after = agent.triage(alert, use_memory=True)
    box(f"ACT 1b  WITH HINDSIGHT MEMORY ({len(after.memories)} memories recalled, {after.seconds}s)", after.answer)
    print("\nRecalled memories:")
    for m in after.memories[:8]:
        print(f"  [{m['type']:<11}] {m['text'][:110]}")

    item = agent.record_feedback(
        alert,
        step="kubectl argo rollouts abort checkout-api -n shop && kubectl argo rollouts undo checkout-api -n shop",
        worked=True,
        engineer="Rohan Das",
        note="Recovered in 6 minutes. v2.41.0 analytics engine opened a third pool per pod.",
    )
    box("ACT 2  FEEDBACK RETAINED", item["content"])

    answer = agent.ask("What keeps breaking checkout-api, and what should we fix permanently?")
    box("ACT 3  REFLECT: what keeps breaking checkout-api?", answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
