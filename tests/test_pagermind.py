from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import create_autospec

import httpx
import openai
import pytest
from fastapi.testclient import TestClient
from hindsight_client import Hindsight

from pagermind.agent import IncidentAgent
from pagermind.knowledge import feedback_to_memory, incident_to_memory
from pagermind.llm import LLMClient, LLMReply, OfflineLLM, ToolCall, parse_tool_arguments
from pagermind.memory import HindsightMemory, LocalMemory
from pagermind.seed import load_json, seed
from pagermind.server import create_app

ALERT = load_json("demo_alerts.json")[0]


@pytest.fixture
def seeded():
    mem = LocalMemory()
    seed(mem, verbose=False)
    return mem


# ------------------------------------------------------------------ knowledge formatting
def test_incident_memory_marks_outcomes_and_dependencies():
    inc = load_json("incidents.json")[0]
    item = incident_to_memory(inc)
    assert "DID NOT WORK" in item["content"] and "WORKED" in item["content"]
    assert "service:checkout-api" in item["tags"]
    assert "service:payments-db" in item["tags"]  # inferred from 'pgbouncer'
    assert item["document_id"] == "INC-2291"
    assert item["timestamp"].year == 2026


def test_feedback_document_ids_are_unique():
    a = feedback_to_memory(alert=ALERT, step="x", worked=True, engineer="A")
    b = feedback_to_memory(alert=ALERT, step="x", worked=True, engineer="A")
    assert a["document_id"] != b["document_id"]


# ------------------------------------------------------------------ Hindsight wrapper
def test_hindsight_wrapper_uses_real_client_signatures():
    client = create_autospec(Hindsight, instance=True)  # autospec rejects wrong kwargs
    client.recall.return_value = SimpleNamespace(
        results=[SimpleNamespace(text="INC-2291 restart made it worse", type="world", tags=["service:checkout-api"],
                                 document_id="INC-2291", occurred_start="2026-03-14T14:12:00Z", mentioned_at=None)]
    )
    client.reflect.return_value = SimpleNamespace(text="pgbouncer exhaustion")
    mem = HindsightMemory("pagermind-test", "http://x", client=client)

    mem.ensure_bank()
    mem.retain(**incident_to_memory(load_json("incidents.json")[0]))
    hits = mem.recall("checkout 5xx", tags=["service:checkout-api"], types=["world"])
    assert hits[0].document_id == "INC-2291" and hits[0].when.startswith("2026-03-14")
    assert mem.reflect("what breaks?") == "pgbouncer exhaustion"

    kwargs = client.recall.call_args.kwargs
    assert kwargs["tags_match"] == "any" and kwargs["prefer_observations"] is True
    assert client.retain.call_args.kwargs["document_id"] == "INC-2291"


def test_create_bank_failure_is_not_fatal():
    client = create_autospec(Hindsight, instance=True)
    client.create_bank.side_effect = RuntimeError("409 exists")
    HindsightMemory("b", "http://x", client=client).ensure_bank()


# ------------------------------------------------------------------ before / after
def test_without_memory_is_generic_and_suggests_restart(seeded):
    res = IncidentAgent(seeded, OfflineLLM()).triage(ALERT, use_memory=False)
    assert res.memories == []
    assert "Restart" in res.answer and "INC-" not in res.answer


def test_with_memory_cites_history_and_warns_against_restart(seeded):
    res = IncidentAgent(seeded, OfflineLLM()).triage(ALERT, use_memory=True)
    assert {"INC-2291", "INC-2417", "INC-2602"} & set(m["document_id"] for m in res.memories)
    assert "INC-2291" in res.answer or "INC-2417" in res.answer
    assert "Do NOT do" in res.answer and "Restart" in res.answer.split("Do NOT do")[1]


def test_triage_is_retained_as_experience(seeded):
    before = seeded.count()
    IncidentAgent(seeded, OfflineLLM()).triage(ALERT)
    assert seeded.count() == before + 1
    assert seeded.items[-1]["type"] == "experience"


def test_feedback_is_recalled_on_next_similar_alert(seeded):
    agent = IncidentAgent(seeded, OfflineLLM())
    agent.record_feedback(ALERT, step="Set ANALYTICS_DB_POOL=0 via configmap", worked=False, engineer="Rohan Das",
                          note="analytics engine ignores the env var")
    res = agent.triage(ALERT, remember=False)
    assert any("ANALYTICS_DB_POOL" in m["text"] for m in res.memories)
    assert "ANALYTICS_DB_POOL" in res.answer.split("Do NOT do")[1]


# ------------------------------------------------------------------ tool loop robustness
class ScriptedLLM:
    name = "scripted"

    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = []

    def complete(self, messages, tools=None):
        self.seen.append((list(messages), tools))
        return self.replies.pop(0)


def test_agent_recovers_from_bad_tool_arguments_and_unknown_tools(seeded):
    llm = ScriptedLLM([
        LLMReply(tool_calls=[ToolCall("1", "search_incident_memory", {}, "{oops", "invalid JSON arguments")]),
        LLMReply(tool_calls=[ToolCall("2", "delete_everything", {}, "{}")]),
        LLMReply(tool_calls=[ToolCall("3", "search_incident_memory", {"query": "pgbouncer max_client_conn"}, "{}")]),
        LLMReply(content="**Likely cause** pgbouncer exhaustion (INC-2602)"),
    ])
    res = IncidentAgent(seeded, llm).triage(ALERT)
    assert "INC-2602" in res.answer
    tool_msgs = [m for m in llm.seen[-1][0] if m["role"] == "tool"]
    assert tool_msgs[0]["content"].startswith("error: invalid JSON")
    assert "unknown tool" in tool_msgs[1]["content"]
    assert "pgbouncer" in tool_msgs[2]["content"]


def test_agent_stops_offering_tools_after_max_rounds(seeded):
    loop = LLMReply(tool_calls=[ToolCall("x", "ask_team_memory", {"question": "?"}, "{}")])
    llm = ScriptedLLM([loop, loop, loop, LLMReply(content="done")])
    res = IncidentAgent(seeded, llm).triage(ALERT)
    assert res.answer == "done" and llm.seen[-1][1] is None


def test_parse_tool_arguments_tolerates_fences():
    assert parse_tool_arguments('```json\n{"query": "x"}\n```') == ({"query": "x"}, None)
    assert parse_tool_arguments("nope")[1] is not None


def _bad_request(msg):
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    return openai.BadRequestError(msg, response=httpx.Response(400, request=req), body={"error": {"code": "tool_use_failed"}})


def _ok(content="ok"):
    msg = SimpleNamespace(content=content, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def test_llm_client_falls_back_model_then_drops_tools():
    calls = []

    def create(**kw):
        calls.append((kw["model"], "tools" in kw))
        if "tools" in kw:
            raise _bad_request("Error code: 400 - tool_use_failed: Failed to call a function")
        return _ok("no-tool answer")

    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    llm = LLMClient("k", "u", "openai/gpt-oss-120b", "qwen/qwen3-32b", client=fake)
    reply = llm.complete([{"role": "user", "content": "hi"}], tools=[{"type": "function"}])
    assert reply.content == "no-tool answer" and reply.degraded
    assert calls == [("openai/gpt-oss-120b", True), ("openai/gpt-oss-120b", True), ("qwen/qwen3-32b", True), ("openai/gpt-oss-120b", False)]


def test_llm_client_strips_think_tags():
    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: _ok("<think>hmm</think>Answer"))))
    assert LLMClient("k", "u", "m", client=fake).complete([{"role": "user", "content": "x"}]).content == "Answer"


# ------------------------------------------------------------------ API
def test_api_end_to_end(seeded):
    client = TestClient(create_app(IncidentAgent(seeded, OfflineLLM())))
    assert client.get("/api/status").json()["memory_backend"] == "LocalMemory"
    r = client.post("/api/triage", json={"alert": ALERT, "use_memory": True})
    assert r.status_code == 200 and r.json()["memories"]
    r = client.post("/api/feedback", json={"alert": ALERT, "step": "abort rollout", "worked": True, "engineer": "Rohan"})
    assert "WORKED" in r.json()["retained"]
    assert client.post("/api/feedback", json={"alert": ALERT, "step": "", "worked": True}).status_code == 422
    assert client.post("/api/ask", json={"question": "what breaks checkout-api?"}).status_code == 200
    assert client.get("/").status_code == 200


def test_api_returns_502_when_memory_backend_down():
    client_mock = create_autospec(Hindsight, instance=True)
    client_mock.recall.side_effect = ConnectionError("hindsight unreachable")
    agent = IncidentAgent(HindsightMemory("b", "http://x", client=client_mock), OfflineLLM())
    r = TestClient(create_app(agent)).post("/api/triage", json={"alert": ALERT})
    assert r.status_code == 502 and "unreachable" in r.json()["detail"]
