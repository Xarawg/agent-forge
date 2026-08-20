"""Снапшот истории диалога агента (v1.1, AF-08): kill/resume не теряет контекст фазы."""

import json
from pathlib import Path
from typing import Any

from forge.agents import run_tool_agent
from forge.journal import Journal
from forge.llm import ChatResult, ToolCall
from forge.tools import ToolBox


class StubClient:
    """Скриптованный клиент: отдаёт заранее заданные ChatResult по очереди."""

    def __init__(self, script: list[ChatResult]) -> None:
        self.script = list(script)
        self.calls: list[list[dict[str, Any]]] = []

    def chat(self, role: str, messages: list[dict[str, Any]], tools: Any = None) -> ChatResult:
        self.calls.append([dict(m) for m in messages])
        return self.script.pop(0)


def _journal(tmp_path: Path) -> Journal:
    return Journal(tmp_path / "runs", "run-test")


def test_history_saved_and_resumed(cfg, target: Path, tmp_path: Path) -> None:
    """Прерванный kill'ом диалог (снапшот остался) продолжается с контекстом,
    а не с чистого листа; счётчик шагов сохраняется."""
    history = tmp_path / "task.history.json"
    toolbox = ToolBox(target, ["**"], cfg.command_allowlist)

    # Первая «сессия»: один tool-вызов, потом процесс как будто убит (скрипт кончился).
    first = StubClient([
        ChatResult(content="", tool_calls=[ToolCall(id="t1", name="list_dir", arguments={"path": "."})]),
    ])
    journal = _journal(tmp_path)
    # Прогоняем один шаг вручную: имитируем kill, отдав только 1 ответ при max_steps=40 —
    # скрипт пуст → имитация убийства после первого шага: ловим IndexError.
    try:
        run_tool_agent(first, cfg, journal, role="coder", system_prompt="s", user_prompt="u",
                       toolbox=toolbox, task_id="t", phase="coder", history_path=history)
    except IndexError:
        pass
    assert history.exists(), "снапшот должен пережить аварийное завершение"
    saved = json.loads(history.read_text(encoding="utf-8"))
    assert saved["steps"] == 1

    # Вторая «сессия»: resume — диалог восстановлен, агент отвечает DONE.
    second = StubClient([ChatResult(content="Всё готово.\nDONE")])
    outcome = run_tool_agent(second, cfg, journal, role="coder", system_prompt="s", user_prompt="u",
                             toolbox=toolbox, task_id="t", phase="coder", history_path=history)
    assert outcome.marker == "DONE"
    # Первый вызов resume-клиента получил накопленную историю (system+user+assistant+tool).
    assert len(second.calls[0]) == 4
    assert second.calls[0][-1]["role"] == "tool"
    # После штатного завершения снапшот удалён: повторный запуск начнётся чистым.
    assert not history.exists()


def test_history_dropped_on_steps_exhausted(cfg, target: Path, tmp_path: Path) -> None:
    """Штатное исчерпание шагов сбрасывает снапшот: retry задачи идёт с чистого диалога."""
    history = tmp_path / "task2.history.json"
    toolbox = ToolBox(target, ["**"], cfg.command_allowlist)
    client = StubClient([ChatResult(content="думаю…") for _ in range(5)])
    outcome = run_tool_agent(client, cfg, _journal(tmp_path), role="coder", system_prompt="s",
                             user_prompt="u", toolbox=toolbox, task_id="t2", phase="coder",
                             max_steps=3, history_path=history)
    assert outcome.marker == "STEPS_EXHAUSTED"
    assert not history.exists()
