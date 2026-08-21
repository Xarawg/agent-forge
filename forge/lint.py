"""`forge lint` — проверка очереди задач до запуска (советчик, не блокер).

Главная проверка — заморозка acceptance (онбординг-решение 2026-08-21,
железное правило №1): тестовые файлы, которые читают acceptance-команды,
должны оставаться ВНЕ scope_paths coder'а — иначе coder может подправить
проверку под себя и гейт №2 превращается в самопроверку.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import load_tasks

#: Признаки тестовых путей в scope задачи.
TEST_MARKERS = ("test", "tests", "spec", "e2e")


def test_scope_warnings(tasks: list[dict[str, Any]]) -> list[str]:
    """Предупреждения: scope задачи покрывает тесты — coder сможет править гейт."""
    warnings: list[str] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        tid = str(task.get("id", "?"))
        for pattern in task.get("scope_paths") or []:
            segments = {seg.lower() for seg in str(pattern).replace("\\", "/").split("/")}
            if segments & set(TEST_MARKERS):
                warnings.append(
                    f"⚠ {tid}: scope {pattern!r} включает тесты — coder сможет подправить "
                    "проверку под себя. Вынесите тесты из scope (заморозка acceptance)."
                )
    return warnings


def lint_tasks(path: Path) -> tuple[list[str], list[str]]:
    """Проверить очередь. Возвращает (ошибки, предупреждения).

    Ошибки — нарушение контракта (очередь не запустится). Предупреждения —
    советы: пустой acceptance, отсутствие бюджета, тесты в scope.
    """
    errors: list[str] = []
    warnings: list[str] = []
    try:
        package = load_tasks(path)
    except (ValueError, OSError, yaml.YAMLError) as exc:
        return [f"❌ контракт tasks.yaml: {exc}"], []

    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw_tasks: list[dict[str, Any]] = [
        item for item in (raw or {}).get("tasks", []) if isinstance(item, dict)
    ]
    warnings.extend(test_scope_warnings(raw_tasks))

    for task in package.tasks:
        if not task.acceptance:
            warnings.append(
                f"⚠ {task.id}: нет acceptance — гейт №2 пуст, задача непроверяема."
            )
        if task.budget.max_cost_usd is None and task.budget.max_tokens is None:
            warnings.append(
                f"⚠ {task.id}: нет перезадачного бюджета — действуют дефолты models.yaml."
            )
    return errors, warnings


def render_lint(path: Path, errors: list[str], warnings: list[str]) -> str:
    lines = [f"forge lint: {path}"]
    lines.extend(errors)
    lines.extend(warnings)
    if not errors and not warnings:
        lines.append("✅ Очередь валидна, замечаний нет.")
    elif not errors:
        lines.append(f"✅ Запустится; {len(warnings)} предупреждений — lint советует, не блокирует.")
    else:
        lines.append(f"❌ {len(errors)} ошибок — очередь не запустится, исправьте до `forge run`.")
    return "\n".join(lines)
