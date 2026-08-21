"""`forge lint` — проверка очереди задач до запуска (советчик, не блокер).

Главная проверка — заморозка acceptance (онбординг-решение 2026-08-21,
железное правило №1): тестовые файлы, которые читают acceptance-команды,
должны оставаться ВНЕ scope_paths coder'а — иначе coder может подправить
проверку под себя и гейт №2 превращается в самопроверку.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from .models import load_tasks

#: Признаки тестовых путей в scope задачи.
TEST_MARKERS = ("test", "tests", "spec", "e2e")

#: Acceptance-команды, которым для прохода нужны существующие тесты.
#: pytest без тестов падает с exit 5 — гарантированный DISPUTE, а не проверка.
TEST_COMMAND_RE = re.compile(
    r"pytest|\bnpm\s+(run\s+)?test\b|\byarn\s+test\b|\bpnpm\s+test\b|"
    r"dotnet\s+test|go\s+test|cargo\s+test"
)


def is_test_command(command: str) -> bool:
    """Команда запускает тесты (и потому требует их наличия)."""
    return bool(TEST_COMMAND_RE.search(command))


def scope_covers_tests(task: dict[str, Any]) -> bool:
    """Scope задачи покрывает тестовые пути — значит, задача может писать тесты."""
    for pattern in task.get("scope_paths") or []:
        segments = {seg.lower() for seg in str(pattern).replace("\\", "/").split("/")}
        if segments & set(TEST_MARKERS):
            return True
    return False


def _topo_ids(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Топологический порядок по depends_on; неизвестные ссылки — в конец (как есть)."""
    by_id = {str(t.get("id")): t for t in tasks if isinstance(t, dict) and t.get("id")}
    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()
    def visit(task: dict[str, Any]) -> None:
        tid = str(task.get("id"))
        if tid in seen:
            return
        seen.add(tid)
        for dep in task.get("depends_on") or []:
            dep_task = by_id.get(str(dep))
            if dep_task is not None:
                visit(dep_task)
        ordered.append(task)
    for task in tasks:
        if isinstance(task, dict) and task.get("id"):
            visit(task)
    ordered.extend(t for t in tasks if not (isinstance(t, dict) and t.get("id")))
    return ordered


def acceptance_order_warnings(
    tasks: list[dict[str, Any]], *, existing_tests: bool | None = None
) -> list[str]:
    """Acceptance обязан проходить на позиции задачи в DAG: тестовая команда
    требует тестов, а они появляются либо в репо, либо из задачи, пишущей тесты.
    existing_tests=None — про репо ничего не известно (lint без target)."""
    warnings: list[str] = []
    tests_available = bool(existing_tests)
    for task in _topo_ids(tasks):
        tid = str(task.get("id", "?"))
        writes_tests = scope_covers_tests(task)
        if not tests_available and not writes_tests:
            for command in task.get("acceptance") or []:
                if is_test_command(str(command)):
                    hint = (
                        "в репозитории тесты не найдены, и ни одна предшествующая "
                        "задача их не пишет"
                        if existing_tests is False else
                        "ни одна предшествующая задача не пишет тесты — "
                        "если их нет и в репозитории"
                    )
                    warnings.append(
                        f"⚠ {tid}: acceptance {command!r} запускает тесты, но {hint}. "
                        "Команда упадёт (pytest → exit 5) и задача уйдёт в DISPUTE. "
                        "Уберите проверку, замените на smoke (импорт/сборка) или "
                        "поднимите задачу с тестами раньше."
                    )
        if writes_tests:
            tests_available = True
    return warnings


def has_existing_tests(root: Path) -> bool:
    """Эвристика: в репозитории уже есть тесты (корень и пара уровней вглубь)."""
    root = root.resolve()
    for name in ("tests", "test", "__tests__", "spec"):
        if (root / name).is_dir():
            return True
    patterns = ("test_*.py", "*_test.py", "*.test.js", "*.test.ts", "*_test.go", "*Test.cs")
    for pattern in patterns:
        for glob in (pattern, f"*/{pattern}", f"*/*/{pattern}"):
            if any(root.glob(glob)):
                return True
    return False


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
    warnings.extend(acceptance_order_warnings(raw_tasks))

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
