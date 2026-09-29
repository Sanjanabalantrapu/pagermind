"""Turns structured incident records and feedback into memory-friendly narrative text.

Hindsight extracts facts with an LLM, so we give it clear prose with explicit
"WORKED" / "DID NOT WORK" markers rather than raw JSON. That's what lets later
recalls answer "what failed last time?" precisely.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

DEPENDENCY_HINTS = {
    "pgbouncer": "payments-db",
    "payments-db": "payments-db",
    "kafka": "kafka",
    "coredns": "coredns",
    "redis": "redis",
    "elasticsearch": "elasticsearch",
    "cert-manager": "cert-manager",
}


def _stamp(when: datetime | None) -> str:
    # Unique per event: re-using a document_id in Hindsight replaces the earlier document,
    # and we want every piece of feedback kept as its own memory.
    return (when or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%S%f")


def service_tags(service: str, *texts: str) -> list[str]:
    tags = {f"service:{service}"}
    blob = " ".join(texts).lower()
    for needle, dep in DEPENDENCY_HINTS.items():
        if needle in blob:
            tags.add(f"service:{dep}")
    return sorted(tags)


def incident_to_memory(inc: dict[str, Any]) -> dict[str, Any]:
    steps = []
    for a in inc.get("attempted", []):
        verdict = "WORKED" if a["worked"] else "DID NOT WORK"
        steps.append(f"- {a['action']}: {verdict}. {a.get('note', '')}".strip())
    content = (
        f"Incident {inc['id']} ({inc['severity']}) on {inc['service']}: {inc['title']}.\n"
        f"Date: {inc['date']}.\n"
        f"Symptoms: {inc['symptoms']}\n"
        f"Root cause: {inc['root_cause']}\n"
        f"Remediation attempts:\n" + "\n".join(steps) + "\n"
        f"Resolved by {inc['resolved_by']} in {inc['mttr_minutes']} minutes.\n"
        f"Postmortem lesson: {inc['postmortem']}"
    )
    tags = service_tags(inc["service"], inc["symptoms"], inc["root_cause"]) + [
        "kind:incident",
        f"severity:{inc['severity'].lower()}",
    ]
    return {
        "content": content,
        "context": "incident postmortem",
        "tags": tags,
        "timestamp": datetime.fromisoformat(inc["date"]),
        "document_id": inc["id"],
        "metadata": {"incident_id": inc["id"], "service": inc["service"], "severity": inc["severity"]},
    }


def feedback_to_memory(
    *, alert: dict[str, Any], step: str, worked: bool, engineer: str, note: str = "", when: datetime | None = None
) -> dict[str, Any]:
    verdict = "WORKED" if worked else "DID NOT WORK"
    content = (
        f"During alert '{alert['title']}' on {alert['service']}, PagerMind recommended: \"{step}\". "
        f"{engineer} applied it and reports it {verdict}."
        + (f" Note from {engineer}: {note}" if note else "")
    )
    return {
        "content": content,
        "context": "triage feedback",
        "tags": service_tags(alert["service"], alert.get("details", ""), step) + ["kind:feedback"],
        "timestamp": when,
        "document_id": f"feedback-{alert.get('id', 'adhoc')}-{_stamp(when)}",
        "metadata": {"alert_id": str(alert.get("id", "adhoc")), "verdict": verdict},
    }


def triage_to_memory(*, alert: dict[str, Any], summary: str, when: datetime | None = None) -> dict[str, Any]:
    content = (
        f"PagerMind triaged alert '{alert['title']}' on {alert['service']} ({alert.get('severity', 'SEV?')}). "
        f"Alert details: {alert.get('details', '')}\nPagerMind's recommendation: {summary[:1200]}"
    )
    return {
        "content": content,
        "context": "agent triage",
        "tags": service_tags(alert["service"], alert.get("details", "")) + ["kind:triage"],
        "timestamp": when,
        "document_id": f"triage-{alert.get('id', 'adhoc')}-{_stamp(when)}",
        "metadata": {"alert_id": str(alert.get("id", "adhoc"))},
    }
