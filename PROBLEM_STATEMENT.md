# Problem statement: PagerMind

**Track:** Engineering & DevOps: Incident Response Agent
**Required technology:** Hindsight (agent memory by Vectorize) · LLM: Groq (`openai/gpt-oss-120b`, fallback `qwen/qwen3-32b`)

## The problem
Production incidents repeat. In our reference system (a mid-size e-commerce platform), checkout-api went down three times in five months with the same root cause: pgbouncer connection exhaustion after a deploy that added a DB pool. Each time, the on-call engineer:

- spent 10–20 minutes re-reading old postmortems, Slack threads and runbooks, if they found them at all;
- tried the "obvious" fix (restart the pods), which had already made the outage worse twice;
- didn't know which DBA to page or that the SRE lead wants the rollback command before any diagnosis.

Postmortems are written and then forgotten. The knowledge lives in people's heads, and those people aren't on call tonight. Generic AI assistants don't help, because they're stateless. They answer every alert as if it were the first one ever seen.

**Who pays for this:** every company that runs on-call rotations. MTTR is money. For an e-commerce checkout, one SEV1 minute during a sale can cost more than a year of tooling. A team would pay $50/engineer/month for an agent that cuts repeat-incident MTTR in half.

## The challenge
Build an incident-response agent that:
1. **Remembers** every incident: symptoms, exact log signatures, root cause, each remediation step and whether it worked, who fixed it, and how long it took.
2. **Recalls** the relevant history within seconds of a new alert, including matches on exact error strings, related services, and time ("the deploy last week").
3. **Warns** the engineer away from steps that failed before, not just towards ones that worked.
4. **Learns** from every new incident. The engineer's feedback (WORKED / DID NOT WORK) becomes memory, so the next similar alert is handled better.
5. **Adapts** to the team's owners, runbooks, change freezes and personal preferences.
6. Makes the value obvious with a **before/after**: the same alert, same model, same prompt, memory off vs on.

## Success criteria
- On the demo alert (`checkout-api 5xx 18%` after rollout v2.41.0), the memory-enabled agent names the matching past incidents, leads with the rollback command, warns against restarting pods, and names the DBA to page. The stateless agent does none of these.
- Feedback retained during one triage changes the output of the next one.
- `reflect()` answers "what keeps breaking checkout-api and what should we fix permanently?" from the accumulated history.
- The agent survives LLM tool-calling errors and memory-backend outages without crashing.

## Our solution
PagerMind: FastAPI + Hindsight + Groq. See [README.md](README.md) and [HINDSIGHT_MEMORY.md](HINDSIGHT_MEMORY.md).
