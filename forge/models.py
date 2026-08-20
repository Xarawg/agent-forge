"""Модель данных agent-forge (SPEC.md §5)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

#: Допустимые состояния задачи (SPEC.md §FR-4).
TASK_STATES = ("queued", "running", "validating", "review", "done", "failed", "blocked")

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


@dataclass
class TaskBudget:
    """Перезадачные капы; None = взять дефолт из models.yaml."""

    max_tokens: int | None = None
    max_cost_usd: float | None = None


@dataclass
class Task:
    id: str
    title: str
    spec_ref: str
    scope_paths: list[str]
    depends_on: list[str] = field(default_factory=list)
    acceptance: list[str] = field(default_factory=list)
    budget: TaskBudget = field(default_factory=TaskBudget)
    gate: str | None = None


@dataclass
class TaskPackage:
    """Очередь задач пакета спецификации (tasks.yaml)."""

    name: str
    tasks: list[Task]
    canon_snapshot: str | None = None


def load_tasks(path: Path) -> TaskPackage:
    """Загрузить и проверить tasks.yaml. Ошибки формата — ValueError с пояснением."""
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("tasks"), list):
        raise ValueError(f"{path}: ожидается mapping с ключом tasks: [...]")
    tasks: list[Task] = []
    seen: set[str] = set()
    for i, item in enumerate(raw["tasks"]):
        if not isinstance(item, dict):
            raise ValueError(f"{path}: задача #{i} не mapping")
        tid = str(item.get("id", ""))
        if not _ID_RE.match(tid):
            raise ValueError(f"{path}: задача #{i}: невалидный id {tid!r} (kebab-case)")
        if tid in seen:
            raise ValueError(f"{path}: дубль id {tid!r}")
        seen.add(tid)
        if not item.get("scope_paths"):
            raise ValueError(f"{path}: задача {tid!r}: пустой scope_paths")
        raw_budget = item.get("budget") or {}
        tasks.append(
            Task(
                id=tid,
                title=str(item.get("title", tid)),
                spec_ref=str(item.get("spec_ref", "")),
                scope_paths=[str(p) for p in item["scope_paths"]],
                depends_on=[str(d) for d in (item.get("depends_on") or [])],
                acceptance=[str(c) for c in (item.get("acceptance") or [])],
                budget=TaskBudget(
                    max_tokens=raw_budget.get("max_tokens"),
                    max_cost_usd=raw_budget.get("max_cost_usd"),
                ),
                gate=item.get("gate"),
            )
        )
    _check_dag(tasks)
    return TaskPackage(
        name=str(raw.get("package", path.stem)),
        tasks=tasks,
        canon_snapshot=raw.get("canon_snapshot"),
    )


def _check_dag(tasks: list[Task]) -> None:
    """depends_on обязан быть DAG без циклов и висячих ссылок (prompts/10 п.3)."""
    ids = {t.id for t in tasks}
    for t in tasks:
        for dep in t.depends_on:
            if dep not in ids:
                raise ValueError(f"задача {t.id!r}: неизвестная зависимость {dep!r}")
    # Топологическая проверка на циклы (Kahn).
    indeg = {t.id: 0 for t in tasks}
    for t in tasks:
        for _dep in t.depends_on:
            indeg[t.id] += 1
    queue = [tid for tid, d in indeg.items() if d == 0]
    done = 0
    while queue:
        cur = queue.pop()
        done += 1
        for t in tasks:
            if cur in t.depends_on:
                indeg[t.id] -= 1
                if indeg[t.id] == 0:
                    queue.append(t.id)
    if done != len(tasks):
        raise ValueError("depends_on содержит цикл")


def topo_order(tasks: list[Task]) -> list[Task]:
    """Порядок выполнения: зависимости раньше зависимых, при равенстве — порядок файла."""
    result: list[Task] = []
    placed: set[str] = set()
    remaining = list(tasks)
    while remaining:
        progressed = False
        for t in list(remaining):
            if all(d in placed for d in t.depends_on):
                result.append(t)
                placed.add(t.id)
                remaining.remove(t)
                progressed = True
        if not progressed:  # цикл — load_tasks уже отловил, страховка
            raise ValueError("depends_on содержит цикл")
    return result


@dataclass
class TaskState:
    """Персистентное состояние задачи (runs/<run_id>/tasks/<id>.json)."""

    id: str
    state: str = "queued"
    note: str = ""
    repair_iterations: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    updated_at: str = ""
