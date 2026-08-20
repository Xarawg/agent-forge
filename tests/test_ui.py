"""Тесты веб-UI `forge ui` (forge/ui.py): API поверх runs/, только чтение."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from forge.journal import Journal
from forge.models import TaskState
from forge.ui import create_server

RUN_ID = "run-20260101-120000"

TASKS_YAML = """\
package: ui-test
tasks:
  - id: task-queued
    title: "Задача в очереди"
    spec_ref: "SPEC.md"
    scope_paths: ["a/**"]
  - id: task-running
    title: "Задача в работе"
    spec_ref: "SPEC.md"
    scope_paths: ["b/**"]
  - id: task-validating
    title: "Задача на валидации"
    spec_ref: "SPEC.md"
    scope_paths: ["c/**"]
  - id: task-review
    title: "Задача на ревью"
    spec_ref: "SPEC.md"
    scope_paths: ["d/**"]
  - id: task-blocked
    title: "Заблокированная задача"
    spec_ref: "SPEC.md"
    scope_paths: ["e/**"]
  - id: task-failed
    title: "Проваленная задача"
    spec_ref: "SPEC.md"
    scope_paths: ["f/**"]
  - id: task-done
    title: "Готовая задача"
    spec_ref: "SPEC.md"
    scope_paths: ["g/**"]
    gate: m1
"""


def _get(base: str, path: str) -> tuple[int, Any]:
    """GET → (status, json). 404 приходит как HTTPError — возвращаем его тело."""
    request = urllib.request.Request(base + path)
    try:
        with urllib.request.urlopen(request, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


@pytest.fixture()
def runs_dir(tmp_path: Path) -> Path:
    path = tmp_path / "runs"
    path.mkdir()
    return path


@pytest.fixture()
def ui_server(runs_dir: Path) -> Iterator[str]:
    """Сервер на эфемерном порту в потоке; base URL наружу."""
    server = create_server(runs_dir, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture()
def synthetic_run(runs_dir: Path, tmp_path: Path) -> str:
    """Прогон с задачами во всех состояниях и событиями в журнале."""
    tasks_path = tmp_path / "tasks.yaml"
    tasks_path.write_text(TASKS_YAML, encoding="utf-8")
    journal = Journal(runs_dir, RUN_ID)
    journal.write_meta(
        {
            "run_id": RUN_ID,
            "package": "ui-test",
            "tasks_path": str(tasks_path),
            "provider": "mock-provider",
            "mock": True,
            "started_at": "2026-01-01T12:00:00+00:00",
            "accepted": [],
        }
    )
    states = ["queued", "running", "validating", "review", "blocked", "failed", "done"]
    for state in states:
        journal.set_task_state(
            TaskState(
                id=f"task-{state}",
                state=state,
                note=f"заметка {state}",
                repair_iterations=1 if state == "failed" else 0,
                tokens_in=100,
                tokens_out=50,
                cost_usd=0.01,
            )
        )
    for i in range(5):
        journal.event(
            task_id="task-done", phase="coder", role="coder",
            tokens_in=10, tokens_out=5, cost_usd=0.001, note=f"шаг {i}",
        )
    journal.event(phase="run", note=f"run {RUN_ID} started")
    return RUN_ID


def test_runs_empty(runs_dir: Path, ui_server: str) -> None:
    status, data = _get(ui_server, "/api/runs")
    assert status == 200
    assert data == {"runs": []}


def test_index_served(ui_server: str) -> None:
    with urllib.request.urlopen(ui_server + "/", timeout=5) as resp:
        body = resp.read().decode("utf-8")
    assert resp.status == 200
    assert "agent-forge" in body


def test_runs_summary(runs_dir: Path, ui_server: str, synthetic_run: str) -> None:
    status, data = _get(ui_server, "/api/runs")
    assert status == 200
    (run,) = data["runs"]
    assert run["run_id"] == synthetic_run
    assert run["package"] == "ui-test"
    assert run["provider"] == "mock-provider"
    assert run["started_at"] == "2026-01-01T12:00:00+00:00"
    # По одной задаче в каждом состоянии; стоимость — сумма cost_usd событий.
    assert run["states"] == {
        "queued": 1, "running": 1, "validating": 1,
        "review": 1, "blocked": 1, "failed": 1, "done": 1,
    }
    assert run["total_cost_usd"] == pytest.approx(0.005)


def test_run_detail_titles_and_totals(runs_dir: Path, ui_server: str, synthetic_run: str) -> None:
    status, data = _get(ui_server, f"/api/run/{synthetic_run}")
    assert status == 200
    assert data["run"]["package"] == "ui-test"
    tasks = {t["id"]: t for t in data["tasks"]}
    assert len(tasks) == 7
    # title и gate подтянулись из tasks.yaml прогона
    assert tasks["task-done"]["title"] == "Готовая задача"
    assert tasks["task-done"]["gate"] == "m1"
    assert tasks["task-done"]["state"] == "done"
    assert tasks["task-failed"]["repairs"] == 1
    assert tasks["task-blocked"]["note"] == "заметка blocked"
    totals = data["totals"]
    assert totals["tokens_in"] == 7 * 100
    assert totals["tokens_out"] == 7 * 50
    assert totals["cost_usd"] == pytest.approx(0.07)
    assert totals["repairs"] == 1


def test_run_detail_without_tasks_yaml(runs_dir: Path, ui_server: str, synthetic_run: str) -> None:
    """tasks.yaml недоступен — title деградирует до id, сервер не падает."""
    meta_path = runs_dir / synthetic_run / "run.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["tasks_path"] = str(runs_dir / "no-such-tasks.yaml")
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    status, data = _get(ui_server, f"/api/run/{synthetic_run}")
    assert status == 200
    task = next(t for t in data["tasks"] if t["id"] == "task-done")
    assert task["title"] == "task-done"
    assert task["gate"] is None


def test_events_tail_and_task_filter(runs_dir: Path, ui_server: str, synthetic_run: str) -> None:
    status, data = _get(ui_server, f"/api/run/{synthetic_run}/events?task=task-done&tail=2")
    assert status == 200
    events = data["events"]
    assert len(events) == 2
    assert all(e["task_id"] == "task-done" for e in events)
    # tail — последние по порядку журнала
    assert events[-1]["note"] == "шаг 4"


def test_events_note_truncated(runs_dir: Path, ui_server: str, synthetic_run: str) -> None:
    journal = Journal(runs_dir, synthetic_run)
    journal.event(task_id="task-done", phase="coder", note="x" * 1000)
    status, data = _get(ui_server, f"/api/run/{synthetic_run}/events?task=task-done&tail=1")
    assert status == 200
    assert len(data["events"][0]["note"]) == 501  # 500 символов + «…»


def test_unknown_run_404(runs_dir: Path, ui_server: str, synthetic_run: str) -> None:
    status, data = _get(ui_server, "/api/run/run-20991231-235959")
    assert status == 404
    assert "error" in data
    status, _ = _get(ui_server, "/api/run/run-20991231-235959/events")
    assert status == 404


def test_run_id_traversal_404(runs_dir: Path, ui_server: str, synthetic_run: str) -> None:
    status, _ = _get(ui_server, "/api/run/..%2F..")
    assert status == 404
