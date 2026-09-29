# How PagerMind uses Hindsight memory

Memory isn't a feature bolted onto PagerMind. It *is* the product. With memory switched off (`use_memory=false`), the same agent, prompt and model give generic advice that includes the one action known to make this outage worse.

## 1. One memory bank per team
```python
client.create_bank(
    bank_id="pagermind-shopfast-sre",
    mission=BANK_MISSION,                 # "I am the on-call memory for an e-commerce SRE team..."
    retain_mission=RETAIN_MISSION,        # keep error strings, commands, WORKED/FAILED verbatim
    observations_mission=OBSERVATIONS_MISSION,  # consolidate recurring failure patterns per service
    enable_observations=True,
    disposition_skepticism=4, disposition_literalism=4, disposition_empathy=2,
)
```
`pagermind/memory.py → HindsightMemory.ensure_bank()`

## 2. What gets retained (`retain`)

| Memory | When | Hindsight type | Tags | Timestamp / document_id |
|---|---|---|---|---|
| Incident postmortem | seeding / after an incident | world | `service:*` (+ inferred deps), `kind:incident`, `severity:*` | real incident date / `INC-xxxx` |
| Runbooks, owners, policies, preferences | seeding | world | `service:*`, `kind:runbook\|ownership\|policy\|preference` | now / `team-n` |
| PagerMind's own triage brief | every triage with memory on | experience | `service:*`, `kind:triage` | now / unique |
| Engineer feedback: step + WORKED / DID NOT WORK | "Close the loop" in the UI or `POST /api/feedback` | experience | `service:*`, `kind:feedback` | now / unique |

Postmortems are written as prose with explicit `WORKED` / `DID NOT WORK` markers (`knowledge.py`), so Hindsight's LLM fact extraction keeps the verdict attached to each remediation step. Historical `timestamp`s let temporal recall answer questions like "what broke checkout last month?".

## 3. What gets recalled (`recall`)
For every alert, `IncidentAgent.gather_context()` runs four recalls with `tags_match="any"`, meaning service-scoped memories plus untagged global ones, and `prefer_observations=True`:

1. **Similar incidents:** the alert title and log lines as the query. Hindsight's semantic, BM25, graph and temporal search matches exact error strings like `pgbouncer: no more connections allowed (max_client_conn)` even when the wording differs.
2. **Outcomes:** "which remediation steps worked and which made things worse", across `world`, `experience` and `observation` memories.
3. **Team context:** runbook commands, owners to page, policies.
4. **Preferences:** how the SRE lead wants briefs structured.

The LLM can also call `search_incident_memory` (recall) and `ask_team_memory` (reflect) during reasoning.

## 4. Reasoning over the whole history (`reflect`)
`POST /api/ask` → `client.reflect(...)`. For example, *"What keeps breaking checkout-api, and what should we fix permanently?"* Reflect checks mental models, then observations, then raw facts, guided by the bank's mission and skeptical disposition.

## 5. How it improves over time
- **Interaction 1** (empty bank): generic advice, the same as a stateless LLM.
- **After seeding 12 postmortems:** it cites INC-IDs, warns against restarts, and gives the exact rollback command and the DBA to page.
- **After feedback:** the fix an engineer confirmed tonight is recalled next time, and a fix reported as **DID NOT WORK** appears under "Do NOT do" (see `tests/test_pagermind.py::test_feedback_is_recalled_on_next_similar_alert`).
- **Over weeks:** Hindsight consolidates repeated facts into observations such as "pgbouncer exhaustion after deploys is the recurring cause of checkout-api 5xx". These rank above the individual facts.

## 6. Where this lives in the code
| File | Hindsight calls |
|---|---|
| `pagermind/memory.py` | `create_bank`, `retain`, `recall`, `reflect`, `list_memories` |
| `pagermind/agent.py` | `gather_context` (4× recall), tool loop (recall/reflect), retain triage, retain feedback |
| `pagermind/knowledge.py` | memory text, tags, timestamps, document ids |
| `pagermind/seed.py` | bulk retain of history |
