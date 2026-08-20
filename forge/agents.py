"""Агентные циклы: coder/repair (модель ↔ инструменты) и reviewer (SPEC.md §FR-2/FR-3)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import ForgeConfig
from .journal import Journal
from .llm import ChatResult, LLMClient
from .tools import TOOL_SCHEMAS, ToolBox

#: Маркеры завершения агента (prompts/20, prompts/40).
DONE_MARKERS = ("DONE",)
STOP_MARKERS = ("DONE", "BLOCKED", "GAP", "STUCK", "DISPUTE")

MAX_AGENT_STEPS = 40  # калибровка пилотом: 25 не хватало с учётом write/test/repair-цикла


@dataclass
class AgentOutcome:
    marker: str  # DONE / BLOCKED / GAP / STUCK / DISPUTE / STEPS_EXHAUSTED
    text: str    # последний текстовый ответ агента (сводка/причина)


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


def _save_history(history_path: Path, steps: int, messages: list[dict[str, Any]]) -> None:
    """Снапшот диалога агента на диск (AF-08): resume после kill продолжает
    фазу с контекстом, а не рестартует её с чистого диалога."""
    history_path.write_text(
        json.dumps({"steps": steps, "messages": messages}, ensure_ascii=False),
        encoding="utf-8",
    )


def _drop_history(history_path: Path | None) -> None:
    """Фаза завершилась штатно (любой маркер, включая STEPS_EXHAUSTED) —
    снапшот не нужен: повторный запуск задачи начнётся с чистого диалога."""
    if history_path is not None:
        history_path.unlink(missing_ok=True)


def run_tool_agent(
    client: LLMClient,
    cfg: ForgeConfig,
    journal: Journal,
    *,
    role: str,
    system_prompt: str,
    user_prompt: str,
    toolbox: ToolBox,
    task_id: str,
    phase: str,
    max_steps: int = MAX_AGENT_STEPS,
    history_path: Path | None = None,
) -> AgentOutcome:
    """Цикл «модель ↔ инструменты» до маркера завершения или исчерпания шагов."""
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    start_step = 0
    if history_path is not None and history_path.exists():
        saved = json.loads(history_path.read_text(encoding="utf-8"))
        messages = saved["messages"]
        start_step = int(saved.get("steps", 0))
        journal.event(
            task_id=task_id, phase=phase, role=role,
            note=f"восстановлен диалог из снапшота: {start_step} шагов, {len(messages)} сообщений",
        )
    last_text = ""
    for step in range(start_step, max_steps):
        result = client.chat(role, messages, tools=TOOL_SCHEMAS)
        log_model_call(journal, cfg, task_id, phase, role, result)
        journal.event(
            task_id=task_id, phase=phase, role=role,
            note=f"raw reply: {(result.content or '<tool_calls>')[:2000]}",
        )

        if result.tool_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": result.content or None,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                            },
                        }
                        for tc in result.tool_calls
                    ],
                }
            )
            for tc in result.tool_calls:
                output = toolbox.call(tc.name, tc.arguments)
                is_scope_error = output.startswith("ERROR:") and (
                    "вне scope" in output or "canon/" in output
                )
                journal.event(
                    task_id=task_id,
                    phase=phase,
                    role=role,
                    command=f"{tc.name} {json.dumps(tc.arguments, ensure_ascii=False)[:300]}",
                    note=("SCOPE_VIOLATION: " if is_scope_error else "") + output[:1000],
                )
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": output})
            if history_path is not None:
                _save_history(history_path, step + 1, messages)
            continue

        last_text = result.content
        marker = parse_marker(result.content)
        if marker:
            _drop_history(history_path)
            return AgentOutcome(marker=marker, text=result.content)
        # Нет ни инструментов, ни маркера — просим завершить по протоколу.
        messages.append({"role": "assistant", "content": result.content})
        messages.append(
            {
                "role": "user",
                "content": "Заверши работу маркером: DONE / BLOCKED: <причина> / GAP: <чего не хватает>"
                + (" / STUCK / DISPUTE" if role == "repair" else ""),
            }
        )
        if history_path is not None:
            _save_history(history_path, step + 1, messages)
    _drop_history(history_path)
    return AgentOutcome(marker="STEPS_EXHAUSTED", text=last_text)


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
