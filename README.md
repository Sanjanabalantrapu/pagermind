# PagerMind: the on-call copilot that remembers every outage

> An incident-response agent built on **[Hindsight](https://github.com/vectorize-io/hindsight)** agent memory.
> It triages a live alert using everything your team has learned from past incidents: which fixes worked, which ones made things worse, who to page, and what the SRE lead wants to see first. Every incident it touches makes the next one faster.

![PagerMind console: the same alert without memory vs with Hindsight memory](docs/console.png)

## The problem

At 2am the on-call engineer gets `checkout-api 5xx rate 18%`. The team has seen this exact failure three times in five months. The answers are buried in three postmortems nobody re-reads under pressure.

A stateless LLM does what a tired engineer does: *"check logs, restart the pods, scale up."* In this system, **restarting the pods is the one move that made it worse twice before**, because every restarting pod opens a fresh DB pool and causes a reconnect storm against pgbouncer.

| | Without memory | With PagerMind + Hindsight |
|---|---|---|
| Likely cause | "unknown, maybe a bad deploy" | "Matches INC-2291, INC-2417, INC-2602: pgbouncer `max_client_conn` exhaustion after a deploy that adds a DB pool" |
| First action | Check logs, restart pods | The exact rollback command (the SRE lead's stated preference) |
| Warnings | none | **Do NOT restart pods**: reconnect storm, 5xx peaked at 31% in INC-2291 |
| Who to page | "the service owner" | Arjun Mehta (DBA), `#payments-oncall` |
| Next time | same generic answer | also knows what *this* engineer reported worked tonight |

## How it works

![Architecture](docs/architecture.png)

1. **Recall.** `IncidentAgent.gather_context()` runs four targeted Hindsight recalls, scoped by tags (`service:checkout-api`, plus dependencies it infers, such as `service:payments-db` when the logs mention pgbouncer):
   similar incidents, remediation outcomes (world, experience and observation memories), runbooks/owners/policies, and team-wide preferences.
2. **Reason.** A Groq-hosted LLM (`openai/gpt-oss-120b`, fallback `qwen/qwen3-32b`) writes a triage brief. It can call two memory tools, `search_incident_memory` (recall) and `ask_team_memory` (reflect), for up to 3 rounds.
3. **Retain.** The brief is retained as an *experience* memory ("PagerMind recommended X for alert Y").
4. **Learn.** When the engineer reports what they applied and whether it **WORKED** or **DID NOT WORK**, that feedback is retained. The next similar alert recalls it and ranks it.
5. **Consolidate.** Hindsight turns repeated facts into *observations* in the background ("pgbouncer exhaustion is the recurring cause of checkout-api 5xx after deploys"). Recall uses `prefer_observations=True`, so consolidated beliefs replace the raw facts they came from.

See **[HINDSIGHT_MEMORY.md](HINDSIGHT_MEMORY.md)** for the full explanation of how memory is used.

## Quick start

### 1. Run Hindsight

**Option A: Hindsight Cloud.** Sign up at <https://ui.hindsight.vectorize.io>, create an API key, and set `HINDSIGHT_URL` and `HINDSIGHT_API_KEY`.

**Option B: local Docker.**
```bash
cp .env.example .env              # add your GROQ_API_KEY
docker compose up --build         # Hindsight :8888 (UI :9999) + PagerMind :8000
```

### 2. Run PagerMind without Docker
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env              # GROQ_API_KEY, HINDSIGHT_URL (+ HINDSIGHT_API_KEY for Cloud)
python -m scripts.seed_memory     # retain 12 incident postmortems + 6 team-knowledge notes
uvicorn pagermind.server:create_app --factory --port 8000
```
Open <http://localhost:8000>, pick the `checkout-api` preset, and click **Triage: without vs with memory**.

### 3. Terminal demo (the 60-second story)
```bash
python -m scripts.demo            # Act 1 before/after · Act 2 feedback retained · Act 3 reflect
```

### Offline mode (no keys, no network)
`MEMORY_BACKEND=local` swaps in a small keyword-matching store, and with no `GROQ_API_KEY` a template responder is used. This mode exists for tests and for trying the UI on a plane. It has none of Hindsight's fact extraction, entity graph, temporal search or consolidation. The screenshot above was taken in this mode.

## API

| Method | Path | Body | What it does |
|---|---|---|---|
| `POST` | `/api/triage` | `{alert, use_memory}` | recall → LLM (+tools) → retain triage |
| `POST` | `/api/feedback` | `{alert, step, worked, engineer, note}` | retain a WORKED / DID NOT WORK outcome |
| `POST` | `/api/ask` | `{question}` | `reflect()` over the whole bank |
| `POST` | `/api/seed` | – | retain the incident history (idempotent via `document_id`) |
| `GET` | `/api/status` | – | backend, bank id, memory count, model |

## Project layout
```
pagermind/
  agent.py       IncidentAgent: gather_context → tool loop → retain; record_feedback; ask
  memory.py      HindsightMemory (create_bank / retain / recall / reflect) + LocalMemory stand-in
  knowledge.py   incident / feedback / triage → memory text, tags, timestamps, document ids
  llm.py         Groq client with tool-call failure handling, OfflineLLM
  server.py      FastAPI API + static console
  static/        single-page on-call console
data/            12 realistic incident postmortems, team knowledge, demo alerts
scripts/         seed_memory.py, demo.py
tests/           15 tests (Hindsight client autospec, before/after, tool-loop failures, API)
content/         article, LinkedIn post, video script, titles, thumbnail prompt
```

## Engineering notes

- **Tool-call failures are expected, not exceptional.** Groq returns HTTP 400 `tool_use_failed` when an open model emits a malformed tool call. `LLMClient.complete()` retries at temperature 0, switches to the fallback model, then answers without tools and flags the reply `degraded`. Bad JSON arguments and unknown tool names go back to the model as tool errors instead of crashing the loop. The tool loop is capped at 3 rounds.
- **Memory outages don't take triage down silently.** API errors surface as HTTP 502 with the upstream reason, and failing to retain a triage is logged but non-fatal.
- **Document ids are deliberate.** Postmortems use their `INC-ID`, so re-seeding replaces them instead of duplicating. Feedback and triage records get unique ids, because re-using a `document_id` replaces the earlier document and would erase history.
- **Bank configuration matters.** The bank's `retain_mission` tells Hindsight to keep error strings, commands and WORKED/FAILED verdicts verbatim. The disposition is set to skeptical and literal so `reflect()` doesn't assume a fix worked.

## Tests
```bash
pytest -q        # 15 passed
```
`create_autospec(Hindsight)` makes sure every call matches the real `hindsight-client` signatures.

## Links
- Hindsight: <https://github.com/vectorize-io/hindsight> · Docs: <https://hindsight.vectorize.io/> · What is agent memory: <https://vectorize.io/what-is-agent-memory>

MIT License.
