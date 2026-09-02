"""Агентные циклы: coder/repair (модель ↔ инструменты) и reviewer (SPEC.md §FR-2/§FR-3)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import ForgeConfig
from .journal import Journal
from .llm import ChatResult, LLMClient
from .tools import TOOL_SCHEMAS, ToolBox, validate_state_patch, apply_state_patch

#: Маркеры завершения агента (prompts/20, prompts/40).
DONE_MARKERS = ("DONE",)
STOP_MARKERS = ("DONE", "BLOCKED", "GAP", "STUCK", "DISPUTE")

MAX_AGENT_STEPS = 40  # калибровка пилотом: 25 не хватало с учётом write/test/repair-цикла


@dataclass
class AgentOutcome:
    marker: str  # DONE / BLOCKED / GAP / STUCK / DISPUTE / STEPS_EXHAUSTED
    text: str    # последний текстовый ответ агента (сводка/причина)
    final_state: dict[str, Any] | None = None   # финальное состояние SKILL


def parse_marker(content: str) -> str | None:
    """Маркер — последняя непустая строка ответа (prompts/20 п.4)."""
    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
    if not lines:
        return None
    last = lines[-1]
    for marker in STOP_MARKERS:
        if last == marker or last.startswith(marker + ":"):
            return marker
    return None


def log_model_call(
    journal: Journal,
    cfg: ForgeConfig,
    task_id: str | None,
    phase: str,
    role: str,
    result: ChatResult,
) -> float:
    """Событие вызова модели в журнал; возвращает стоимость вызова."""
    rc = cfg.role(role)
    cost = rc.cost_usd(result.tokens_in, result.tokens_out)
    journal.event(
        task_id=task_id,
        phase=phase,
        role=role,
        model=result.model,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        cost_usd=cost,
    )
    return cost


def _parse_skill_response(content: str) -> tuple[dict[str, Any], str, str | None]:
    """Извлекает JSON из ответа модели (SKILL.state протокол).

    Возвращает (state_patch, action, marker). Маркер может быть полем в JSON
    или стоять после JSON.
    """
    import re

    # 1) Ищем блок ```json ... ```
    json_match = re.search(r'```json\s*([\s\S]*?)\s*```', content)
    if json_match:
        json_str = json_match.group(1)
        rest = content[json_match.end():].strip()
    else:
        # 2) Ищем первый '{' и пытаемся найти сбалансированный JSON
        start = content.find('{')
        if start == -1:
            raise ValueError("No JSON object found in response")
        stack = 0
        end = None
        for i, ch in enumerate(content[start:], start):
            if ch == '{':
                stack += 1
            elif ch == '}':
                stack -= 1
                if stack == 0:
                    end = i + 1
                    break
        if end is None:
            raise ValueError("Unbalanced JSON in response")
        json_str = content[start:end]
        rest = content[end:].strip()

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}")

    state_patch = data.get("state_patch", {})
    action = data.get("action", "")
    marker = data.get("marker")  # может быть внутри JSON

    if marker is None and rest:
        # Ищем маркер в остатке (первое слово)
        for m in STOP_MARKERS:
            if rest.startswith(m) or rest.startswith(m + ":"):
                marker = m
                break

    return state_patch, action, marker


def run_tool_agent(
    client: LLMClient,
    cfg: ForgeConfig,
    journal: Journal,
    *,
    role: str,
    system_prompt: str,
    user_prompt_template: str,          # шаблон с {{state}} и {{observation}}
    toolbox: ToolBox,
    task_id: str,
    phase: str,
    max_steps: int = MAX_AGENT_STEPS,
    initial_state: dict[str, Any] | None = None,
    initial_observation: str = "",
) -> AgentOutcome:
    """Цикл «модель → действие → наблюдение» по протоколу SKILL.state.

    История не накапливается: на каждом шаге передаётся только system и новый
    user_prompt, сформированный из шаблона с текущими state и observation.
    """
    state = initial_state or {}
    observation = initial_observation
    last_text = ""

    for step in range(max_steps):
        # Собрать промпт с подстановкой текущего состояния и наблюдения
        user_prompt = user_prompt_template.replace("{{state}}", json.dumps(state, ensure_ascii=False))
        user_prompt = user_prompt.replace("{{observation}}", observation)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # Вызов модели БЕЗ инструментов (вся логика действия в JSON)
        result = client.chat(role, messages, tools=None)
        log_model_call(journal, cfg, task_id, phase, role, result)

        # Парсим ответ
        try:
            state_patch, action, marker = _parse_skill_response(result.content)
        except ValueError as e:
            journal.event(
                task_id=task_id, phase=phase, role=role,
                note=f"Ошибка парсинга JSON: {e}\nОтвет: {result.content[:500]}"
            )
            # Продолжаем, но с пустым патчем и без действия (или можно прерваться?)
            state_patch, action, marker = {}, "", None

        # Валидация патча
        if not validate_state_patch(state_patch):
            journal.event(
                task_id=task_id, phase=phase, role=role,
                note=f"Невалидный патч состояния: {state_patch}"
            )
            state_patch = {}

        # Применяем патч
        new_state = apply_state_patch(state, state_patch)
        state = new_state

        # Выполняем действие
        output = ""
        if action:
            try:
                output = toolbox.execute(action, state)
            except Exception as exc:
                output = f"ERROR: {exc}"
            journal.event(
                task_id=task_id, phase=phase, role=role,
                command=action, note=output[:1000]
            )
            observation = output
        else:
            observation = ""

        last_text = result.content

        # Проверяем маркер завершения
        if marker:
            return AgentOutcome(marker=marker, text=result.content, final_state=state)

        # Если маркер не указан явно, пробуем извлечь из текста (старый формат)
        if parse_marker(result.content):
            return AgentOutcome(marker=parse_marker(result.content), text=result.content, final_state=state)

    # Шаги исчерпаны
    return AgentOutcome(marker="STEPS_EXHAUSTED", text=last_text, final_state=state)


def run_reviewer(
    client: LLMClient,
    cfg: ForgeConfig,
    journal: Journal,
    *,
    system_prompt: str,
    review_prompt: str,
    task_id: str,
) -> str:
    """Одношаговое ревью без инструментов (prompts/30). Возвращает текст вердикта."""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": review_prompt},
    ]
    result = client.chat("reviewer", messages)
    log_model_call(journal, cfg, task_id, "review", "reviewer", result)
    journal.event(task_id=task_id, phase="review", role="reviewer", note=f"verdict: {result.content[:1000]}")
    return result.content


def parse_verdict(review_text: str) -> str:
    """APPROVE / REWORK / REJECT из первой строки вердикта reviewer'а."""
    for line in review_text.splitlines():
        line = line.strip()
        for verdict in ("APPROVE", "REWORK", "REJECT"):
            if line.startswith(verdict):
                return verdict
    return "REWORK"  # нераспознанный вердикт — на переделку, не пропускаем молча