"""LLM-клиенты: OpenAI-совместимый API (DeepSeek/OpenRouter/Ollama) и mock-режим.

SPEC.md §FR-5/FR-6/§6.3: retry с экспоненциальным backoff (429/5xx, free-лимиты),
mock-режим FORGE_MOCK=1 — весь цикл без API-ключа.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from .config import ForgeConfig, RoleConfig


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ChatResult:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    model: str = ""


class LLMClient(Protocol):
    """Единый интерфейс для реального и mock-клиента."""

    def chat(
        self,
        role: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResult: ...


class ProviderError(Exception):
    """Отказ провайдера после всех retry."""


class OpenAIClient:
    """POST {base_url}/chat/completions, ретраи по models.yaml (SPEC.md §FR-5)."""

    def __init__(self, cfg: ForgeConfig) -> None:
        self.cfg = cfg

    def chat(
        self,
        role: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResult:
        rc = self.cfg.role(role)
        return self._chat_with_fallback(rc, messages, tools)

    def _chat_with_fallback(
        self,
        rc: RoleConfig,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> ChatResult:
        """Основная модель роли; при перманентном отказе — fallback_models пресета."""
        candidates = [rc.model, *self.cfg.fallback_models]
        last_error: Exception | None = None
        for model in candidates:
            try:
                return self._chat_retried(rc, model, messages, tools)
            except ProviderError as exc:
                last_error = exc
        raise ProviderError(f"все модели роли {rc.role} отказали: {last_error}")

    def _chat_retried(
        self,
        rc: RoleConfig,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> ChatResult:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": rc.max_tokens,
            "temperature": rc.temperature,
        }
        if tools:
            payload["tools"] = tools
        headers = {"Authorization": f"Bearer {rc.api_key}"} if rc.api_key else {}
        backoffs = self.cfg.retry.backoff_seconds
        for attempt in range(self.cfg.retry.max_attempts):
            try:
                with httpx.Client(timeout=180) as client:
                    resp = client.post(
                        rc.base_url.rstrip("/") + "/chat/completions",
                        json=payload,
                        headers=headers,
                    )
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise _Retryable(f"HTTP {resp.status_code}: {resp.text[:200]}")
                resp.raise_for_status()
                return _parse_response(resp.json(), model)
            except (httpx.HTTPError, _Retryable) as exc:
                if attempt >= self.cfg.retry.max_attempts - 1:
                    raise ProviderError(f"{model}: {exc}") from exc
                time.sleep(backoffs[min(attempt, len(backoffs) - 1)])
        raise ProviderError(f"{model}: недостижимо")  # pragma: no cover


class _Retryable(Exception):
    pass


def _parse_response(data: dict[str, Any], model: str) -> ChatResult:
    choice = data["choices"][0]["message"]
    usage = data.get("usage") or {}
    tool_calls = [
        ToolCall(
            id=str(tc.get("id", f"call_{i}")),
            name=tc["function"]["name"],
            arguments=json.loads(tc["function"].get("arguments") or "{}"),
        )
        for i, tc in enumerate(choice.get("tool_calls") or [])
    ]
    return ChatResult(
        content=choice.get("content") or "",
        tool_calls=tool_calls,
        tokens_in=int(usage.get("prompt_tokens", 0)),
        tokens_out=int(usage.get("completion_tokens", 0)),
        model=str(data.get("model") or model),
    )


# ---------------------------------------------------------------------------
# Mock-режим (SPEC.md §6.3): детерминированный стенд вместо модели.
#
# Это НЕ модель — программный стенд, прогоняющий runner через все фазы:
# - coder: пишет <scope>/mock_output.md и завершает DONE;
# - repair: пишет <scope>/mock_state.txt с содержимым "iteration-N"
#   (N — номер repair-итерации из промпта), что позволяет тестам делать
#   acceptance, зеленеющий на заданной итерации;
# - reviewer: APPROVE, если в промпте "ACCEPTANCE_STATUS: OK", иначе REWORK;
# - planner: готовый черновик tasks.yaml.
# Сценарий FORGE_MOCK_SCENARIO=rogue: coder сначала пытается писать вне scope
# (проверка §6.5), получает ошибку инструмента и работает дальше корректно.
# ---------------------------------------------------------------------------

MOCK_TASKS_DRAFT = """package: mock-draft
tasks:
  - id: draft-1
    title: "Черновик задачи от mock-planner"
    spec_ref: "SPEC.md"
    scope_paths: ["draft/**"]
    depends_on: []
    acceptance: ["python -c \\"print('ok')\\""]
"""


class MockClient:
    def __init__(self, cfg: ForgeConfig) -> None:
        self.cfg = cfg

    @property
    def scenario(self) -> str:
        """Сценарий читается лениво — тесты меняют FORGE_MOCK_SCENARIO после старта."""
        return os.environ.get("FORGE_MOCK_SCENARIO", "default")

    def chat(
        self,
        role: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResult:
        tokens_in = sum(len(str(m.get("content") or "")) for m in messages) // 4
        handler = {
            "planner": self._planner,
            "coder": self._coder,
            "repair": self._repair,
            "reviewer": self._reviewer,
        }[role]
        result = handler(messages)
        result.tokens_in = tokens_in or 100
        result.model = f"mock-{role}"
        return result

    # --- роли ----------------------------------------------------------------

    def _planner(self, messages: list[dict[str, Any]]) -> ChatResult:
        return ChatResult(content=MOCK_TASKS_DRAFT, tokens_out=120)

    def _reviewer(self, messages: list[dict[str, Any]]) -> ChatResult:
        last = str(messages[-1].get("content") or "")
        if "ACCEPTANCE_STATUS: OK" in last:
            return ChatResult(content="APPROVE", tokens_out=20)
        return ChatResult(
            content="REWORK: 1. acceptance-команды красные, исправить по выводу валидатора",
            tokens_out=30,
        )

    def _coder(self, messages: list[dict[str, Any]]) -> ChatResult:
        scope_dir = _first_scope_dir(messages)
        wrote = _tool_results(messages)
        if self.scenario == "rogue" and not any("вне scope" in w for w in wrote):
            return ChatResult(
                content="",
                tool_calls=[
                    ToolCall(
                        id="mock-rogue",
                        name="write_file",
                        arguments={"path": "outside_scope/hack.txt", "content": "rogue"},
                    )
                ],
                tokens_out=10,
            )
        if not any("mock_output.md" in w for w in wrote):
            return ChatResult(
                content="",
                tool_calls=[
                    ToolCall(
                        id="mock-write",
                        name="write_file",
                        arguments={
                            "path": f"{scope_dir}/mock_output.md",
                            "content": "# mock output\nСгенерировано MockClient (FORGE_MOCK=1).\n",
                        },
                    )
                ],
                tokens_out=40,
            )
        return ChatResult(content="Сводка: записан mock_output.md.\nDONE", tokens_out=20)

    def _repair(self, messages: list[dict[str, Any]]) -> ChatResult:
        scope_dir = _first_scope_dir(messages)
        last = str(messages[-1].get("content") or "")
        iteration = 1
        for token in last.split():
            if token.startswith("iteration-"):
                try:
                    iteration = int(token.removeprefix("iteration-"))
                except ValueError:
                    pass
        wrote = _tool_results(messages)
        if not any("mock_state.txt" in w for w in wrote):
            return ChatResult(
                content="",
                tool_calls=[
                    ToolCall(
                        id="mock-repair",
                        name="write_file",
                        arguments={
                            "path": f"{scope_dir}/mock_state.txt",
                            "content": f"iteration-{iteration}\n",
                        },
                    )
                ],
                tokens_out=40,
            )
        return ChatResult(content=f"Починено на итерации {iteration}.\nDONE", tokens_out=20)


def _first_scope_dir(messages: list[dict[str, Any]]) -> str:
    """Каталог первой маски scope из промпта задачи (раздел '### Scope')."""
    text = str(messages[1].get("content") or "") if len(messages) > 1 else ""
    in_scope = False
    for line in text.splitlines():
        if line.startswith("### Scope"):
            in_scope = True
            continue
        if in_scope and line.startswith("###"):
            break
        if in_scope and line.strip().startswith("-"):
            mask = line.strip().lstrip("- ").strip().strip("`")
            base = mask.removesuffix("/**")
            last = base.rsplit("/", 1)[-1]
            if "." in last:  # маска указывает на конкретный файл — берём его каталог
                base = base.rsplit("/", 1)[0] if "/" in base else "."
            return base
    return "mock_out"


def _tool_results(messages: list[dict[str, Any]]) -> list[str]:
    """Тексты ответов инструментов в текущей беседе (роль tool)."""
    return [str(m.get("content") or "") for m in messages if m.get("role") == "tool"]


def make_client(cfg: ForgeConfig) -> LLMClient:
    """Фабрика клиента: FORGE_MOCK=1 → MockClient, иначе OpenAI-совместимый."""
    if cfg.mock:
        return MockClient(cfg)
    return OpenAIClient(cfg)
