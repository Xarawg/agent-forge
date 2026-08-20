"""Журнал прогонов и состояния задач (SPEC.md §FR-4, §5).

runs/<run_id>/
  run.json          — метаданные прогона (модели, версия промптов, accepted-гейты)
  events.jsonl      — каждое событие: вызов модели, токены, команда, результат
  tasks/<id>.json   — состояние задачи и счётчик repair-итераций
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import TaskState


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_run_id() -> str:
    return datetime.now(UTC).strftime("run-%Y%m%d-%H%M%S")


class Journal:
    def __init__(self, runs_dir: Path, run_id: str) -> None:
        self.run_dir = runs_dir / run_id
        self.run_id = run_id
        (self.run_dir / "tasks").mkdir(parents=True, exist_ok=True)
        self.events_path = self.run_dir / "events.jsonl"
        self.meta_path = self.run_dir / "run.json"

    # --- метаданные прогона -------------------------------------------------

    def write_meta(self, meta: dict[str, Any]) -> None:
        self.meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    def read_meta(self) -> dict[str, Any]:
        if not self.meta_path.exists():
            return {}
        data: dict[str, Any] = json.loads(self.meta_path.read_text(encoding="utf-8"))
        return data

    def accept_task(self, task_id: str) -> None:
        """Отметить прохождение человеческого гейта №3 (SPEC.md §FR-4)."""
        meta = self.read_meta()
        accepted = meta.setdefault("accepted", [])
        if task_id not in accepted:
            accepted.append(task_id)
        self.write_meta(meta)
        self.event(task_id=task_id, phase="gate", note=f"accepted by owner (forge accept {task_id})")

    def accepted_tasks(self) -> list[str]:
        return list(self.read_meta().get("accepted", []))

    # --- события ------------------------------------------------------------

    def event(
        self,
        *,
        task_id: str | None = None,
        phase: str,
        role: str | None = None,
        model: str | None = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_usd: float = 0.0,
        command: str | None = None,
        exit_code: int | None = None,
        note: str = "",
    ) -> dict[str, Any]:
        """Строка events.jsonl по схеме SPEC.md §5. Секреты сюда не попадают."""
        record: dict[str, Any] = {
            "ts": utc_now(),
            "run_id": self.run_id,
            "task_id": task_id,
            "phase": phase,
            "role": role,
            "model": model,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": round(cost_usd, 6),
            "note": note,
        }
        if command is not None:
            record["command"] = command
        if exit_code is not None:
            record["exit_code"] = exit_code
        with self.events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def read_events(self) -> list[dict[str, Any]]:
        if not self.events_path.exists():
            return []
        lines = self.events_path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]

    # --- состояния задач ----------------------------------------------------

    def task_state(self, task_id: str) -> TaskState:
        path = self.run_dir / "tasks" / f"{task_id}.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return TaskState(**data)
        return TaskState(id=task_id)

    def set_task_state(self, state: TaskState, *, note: str = "") -> None:
        state.updated_at = utc_now()
        if note:
            state.note = note
        path = self.run_dir / "tasks" / f"{state.id}.json"
        path.write_text(json.dumps(asdict(state), ensure_ascii=False, indent=2), encoding="utf-8")
        self.event(task_id=state.id, phase="state", note=f"-> {state.state}" + (f": {note}" if note else ""))

    def log_for_task(self, task_id: str) -> list[dict[str, Any]]:
        return [e for e in self.read_events() if e.get("task_id") == task_id]
