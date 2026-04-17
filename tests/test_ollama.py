from __future__ import annotations

import pytest

from hh_applicant_tool.ai.openai import ChatOpenAI, OpenAIError
from hh_applicant_tool.ai.ollama.client import ChatOllama, OllamaError
from hh_applicant_tool.ai.ollama.config import (
    DEFAULT_HOST_BASE_URL,
    resolve_base_url,
    resolve_ollama_base_url,
)
from hh_applicant_tool.ai.ollama.models import get_model_spec
from hh_applicant_tool.ai.selection import (
    get_ai_provider,
    get_ai_section,
)


class DummyResponse:
    def __init__(self, payload: dict):
        self.payload = payload
        self.status_code = 200
        self.headers = {}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class InvalidJsonResponse(DummyResponse):
    def json(self) -> dict:
        raise ValueError("bad json")


class DummySession:
    def __init__(self, response: DummyResponse):
        self.response = response
        self.calls: list[dict] = []

    def post(self, url, json, headers, timeout):  # noqa: A002
        self.calls.append(
            {
                "url": url,
                "json": json,
                "headers": headers,
                "timeout": timeout,
            }
        )
        return self.response


def test_resolve_base_url_host_and_remote() -> None:
    assert resolve_base_url({"mode": "host"}) == DEFAULT_HOST_BASE_URL
    assert resolve_base_url(
        {
            "mode": "remote",
            "remote_url": "http://10.0.0.2:11434/v1/chat/completions",
        }
    ) == "http://10.0.0.2:11434/v1/chat/completions"


def test_resolve_ollama_base_url_rejects_base_url() -> None:
    with pytest.raises(ValueError, match="Для Ollama не используйте ai_\\*\\.base_url"):
        resolve_ollama_base_url(
            {
                "mode": "host",
                "base_url": "https://api.openai.com/v1/chat/completions",
            }
        )


def test_get_model_spec() -> None:
    assert get_model_spec("llama3_2").model == "llama3.2"
    assert get_model_spec("gpt_oss_20b").model == "gpt-oss:20b"
    assert get_model_spec("gpt_oss_20b_cloud").model == "gpt-oss:20b-cloud"
    assert get_model_spec("gpt_oss_120b_cloud").model == "gpt-oss:120b-cloud"
    assert get_model_spec("llava").vision is True
    assert get_model_spec("unknown").model == "unknown"
    assert get_model_spec("unknown").vision is None


def test_ai_selection_keeps_legacy_openai_sections() -> None:
    section, config = get_ai_section(
        {"ai_cover_letter": {"provider": "openai", "api_key": "x"}},
        "cover_letter",
    )
    assert section == "ai_cover_letter"
    assert get_ai_provider(section, config) == "openai"


def test_ai_selection_supports_legacy_openai_sections() -> None:
    section, config = get_ai_section(
        {"openai_cover_letter": {"api_key": "x"}},
        "cover_letter",
    )
    assert section == "openai_cover_letter"
    assert get_ai_provider(section, config) == "openai"


def test_ai_selection_supports_legacy_ollama_sections() -> None:
    section, config = get_ai_section(
        {"ollama_cover_letter": {"model": "llama3_2"}},
        "cover_letter",
    )
    assert section == "ollama_cover_letter"
    assert get_ai_provider(section, config) == "ollama"


def test_chat_ollama_uses_max_tokens() -> None:
    session = DummySession(
        {
            "choices": [
                {
                    "message": {
                        "content": "ok",
                    }
                }
            ]
        }
    )
    client = ChatOllama(
        api_key="ollama",
        base_url=DEFAULT_HOST_BASE_URL,
        model="llama3.2",
        max_tokens=123,
        session=session,
    )

    assert client.complete("hello") == "ok"
    assert session.calls[0]["json"]["max_tokens"] == 123
    assert "max_completion_tokens" not in session.calls[0]["json"]


def test_chat_ollama_uses_think_for_gpt_oss() -> None:
    session = DummySession(
        {
            "choices": [
                {
                    "message": {
                        "content": "ok",
                    }
                }
            ]
        }
    )
    client = ChatOllama(
        api_key="ollama",
        base_url=DEFAULT_HOST_BASE_URL,
        model="gpt-oss:20b",
        think="high",
        session=session,
    )

    assert client.complete("hello") == "ok"
    assert session.calls[0]["json"]["think"] == "high"


def test_chat_ollama_reports_invalid_json() -> None:
    client = ChatOllama(
        api_key="ollama",
        base_url=DEFAULT_HOST_BASE_URL,
        model="llama3.2",
        session=DummySession(InvalidJsonResponse({})),
    )

    with pytest.raises(OllamaError, match="Invalid JSON response"):
        client.complete("hello")


def test_chat_openai_reports_invalid_json() -> None:
    client = ChatOpenAI(
        api_key="x",
        base_url="http://example/v1/chat/completions",
        model="gpt-4o-mini",
        session=DummySession(InvalidJsonResponse({})),
    )

    with pytest.raises(OpenAIError, match="Invalid JSON response"):
        client.complete("hello")
