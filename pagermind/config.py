"""Runtime configuration, read once from environment variables (or a .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader so we don't need python-dotenv as a dependency."""
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


ROOT = Path(__file__).resolve().parent.parent
_load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    # Memory
    memory_backend: str = os.getenv("MEMORY_BACKEND", "hindsight")  # "hindsight" | "local"
    hindsight_url: str = os.getenv("HINDSIGHT_URL", "http://localhost:8888")
    hindsight_api_key: str | None = os.getenv("HINDSIGHT_API_KEY") or None
    team: str = os.getenv("PAGERMIND_TEAM", "shopfast-sre")

    # LLM (any OpenAI-compatible endpoint; Groq by default)
    llm_base_url: str = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
    llm_api_key: str | None = os.getenv("GROQ_API_KEY") or os.getenv("LLM_API_KEY") or None
    llm_model: str = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")
    llm_fallback_model: str = os.getenv("LLM_FALLBACK_MODEL", "qwen/qwen3-32b")

    @property
    def bank_id(self) -> str:
        return f"pagermind-{self.team}"


settings = Settings()
