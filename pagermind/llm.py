"""LLM access with defensive tool-calling.

Groq-hosted open models (gpt-oss-120b, qwen3-32b) occasionally emit malformed tool
calls; Groq surfaces those as HTTP 400 `tool_use_failed`. We treat that as a normal
event, not an exception: retry, then switch model, then continue without tools.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("pagermind.llm")

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str = ""
    parse_error: str | None = None


@dataclass
class LLMReply:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    model: str = ""
    degraded: bool = False  # True when we had to drop tools to get an answer


def parse_tool_arguments(raw: str | None) -> tuple[dict[str, Any], str | None]:
    """Parse tool-call JSON, tolerating the usual model mistakes."""
    if not raw:
        return {}, None
    try:
        val = json.loads(raw)
        return (val if isinstance(val, dict) else {"value": val}), None
    except json.JSONDecodeError:
        pass
    # Common failure: markdown fences or trailing text around the JSON object.
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0)), None
        except json.JSONDecodeError as exc:
            return {}, f"invalid JSON arguments: {exc}"
    return {}, "tool arguments were not JSON"


def _is_tool_failure(exc: Exception) -> bool:
    text = str(exc).lower()
    return "tool_use_failed" in text or "failed to call a function" in text or "tool call validation" in text


class LLMClient:
    def __init__(self, api_key: str, base_url: str, model: str, fallback_model: str | None = None, client: Any = None):
        if client is None:
            from openai import OpenAI

            client = OpenAI(api_key=api_key, base_url=base_url, max_retries=2, timeout=60)
        self.client = client
        self.model = model
        self.fallback_model = fallback_model
        self.name = model

    def _call(self, model: str, messages, tools, temperature: float):
        kwargs: dict[str, Any] = {"model": model, "messages": messages, "temperature": temperature}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        return self.client.chat.completions.create(**kwargs)

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> LLMReply:
        from openai import BadRequestError, RateLimitError

        attempts: list[tuple[str, list | None, float]] = [(self.model, tools, 0.2)]
        if tools:
            attempts.append((self.model, tools, 0.0))  # same model, deterministic
            if self.fallback_model:
                attempts.append((self.fallback_model, tools, 0.0))
            attempts.append((self.model, None, 0.2))  # last resort: no tools at all
        last_exc: Exception | None = None
        for i, (model, tl, temp) in enumerate(attempts):
            try:
                resp = self._call(model, messages, tl, temp)
            except BadRequestError as exc:
                last_exc = exc
                if tl and _is_tool_failure(exc):
                    log.warning("tool call failed on %s (attempt %d): %s", model, i + 1, exc)
                    continue
                raise
            except RateLimitError as exc:
                last_exc = exc
                time.sleep(2 * (i + 1))
                continue
            msg = resp.choices[0].message
            calls = []
            for tc in msg.tool_calls or []:
                args, err = parse_tool_arguments(tc.function.arguments)
                calls.append(ToolCall(tc.id, tc.function.name, args, tc.function.arguments or "", err))
            return LLMReply(
                content=_THINK.sub("", msg.content or "").strip(),
                tool_calls=calls,
                model=model,
                degraded=bool(tools) and tl is None,
            )
        raise RuntimeError(f"LLM unavailable after {len(attempts)} attempts: {last_exc}")


class OfflineLLM:
    """Deterministic stand-in used when no LLM key is configured (tests, offline demo).

    It never calls tools; it formats whatever memory context the agent already fetched.
    That is enough to show the before/after effect of memory without network access.
    """

    name = "offline-template"

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> LLMReply:
        user = next(m["content"] for m in reversed(messages) if m["role"] == "user")
        if "## Memory" not in user or "(no memories" in user:
            return LLMReply(content=GENERIC_TRIAGE, model=self.name)
        memory_block = user.split("## Memory", 1)[1]
        worked, failed, incidents, people = [], [], [], []
        for line in memory_block.splitlines():
            low = line.lower()
            if "did not work" in low or "made it worse" in low:
                failed.append(line.strip("- ").strip())
            elif "worked" in low:
                worked.append(line.strip("- ").strip())
            if re.search(r"INC-\d+", line):
                incidents += re.findall(r"INC-\d+", line)
            if re.search(r"\b(page|paged|owner|prefers|wants|freeze)\b", low):
                people.append(line.strip("- ").strip())
        incidents = sorted(set(incidents))
        parts = ["**Matches past incidents:** " + (", ".join(incidents) or "none found")]
        if worked:
            parts.append("**Do first (worked before):**\n" + "\n".join(f"- {w}" for w in worked[:4]))
        if failed:
            parts.append("**Do NOT do (failed before):**\n" + "\n".join(f"- {f}" for f in failed[:4]))
        if people:
            parts.append("**Team context:**\n" + "\n".join(f"- {p}" for p in people[:3]))
        return LLMReply(content="\n\n".join(parts), model=self.name)


GENERIC_TRIAGE = (
    "**Likely cause:** unknown. Could be a bad deploy, resource exhaustion, or a dependency failure.\n\n"
    "**Suggested steps:**\n"
    "- Check the service logs and dashboards for errors\n"
    "- Restart the affected pods to clear bad state\n"
    "- Scale up replicas to absorb load\n"
    "- If a deploy happened recently, consider rolling back\n"
    "- Escalate to the service owner if the issue persists"
)


def build_llm(settings):
    if not settings.llm_api_key:
        log.warning("No GROQ_API_KEY / LLM_API_KEY set; using OfflineLLM template responses")
        return OfflineLLM()
    return LLMClient(settings.llm_api_key, settings.llm_base_url, settings.llm_model, settings.llm_fallback_model)
