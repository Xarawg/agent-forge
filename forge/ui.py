"""Веб-UI `forge ui`: канбан прогонов поверх runs/ (SPEC.md §FR-4).

Только чтение: сервер ничего не мутирует в runs/. Строго stdlib
(http.server/json/urllib) — ноль новых зависимостей. Статика читается из
forge/ui_static/ рядом с модулем (работает и в editable-install).
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .models import load_tasks

#: Порядок колонок канбана (реальные состояния runner'а, forge/models.py:TASK_STATES).
STATE_ORDER = ("queued", "running", "validating", "review", "blocked", "failed", "done")

NOTE_LIMIT = 500  # обрезка note в API (карточки и лог-вьюер)
MAX_TAIL = 500


def _read_json(path: Path) -> dict[str, Any]:
    """JSON-файл → dict; битый/отсутствующий файл — пустой dict, сервер не роняем."""
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_events(run_dir: Path) -> list[dict[str, Any]]:
    """events.jsonl → список событий; битые строки пропускаются."""
    path = run_dir / "events.jsonl"
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    events: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            record: Any = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            events.append(record)
    return events


def _valid_run_id(run_id: str) -> bool:
    """Защита от выхода за runs/ через путь."""
    return bool(run_id) and "/" not in run_id and "\\" not in run_id and ".." not in run_id


def list_runs(runs_dir: Path) -> list[dict[str, Any]]:
    """GET /api/runs: сводка по каждому прогону в runs/."""
    runs: list[dict[str, Any]] = []
    if not runs_dir.is_dir():
        return runs
    dirs = sorted((p for p in runs_dir.iterdir() if p.is_dir()), key=lambda p: p.name)
    for run_dir in dirs:
        meta = _read_json(run_dir / "run.json")
        states: dict[str, int] = {}
        tasks_dir = run_dir / "tasks"
        if tasks_dir.is_dir():
            for state_path in sorted(tasks_dir.glob("*.json")):
                state = str(_read_json(state_path).get("state", "queued"))
                states[state] = states.get(state, 0) + 1
        total_cost = round(sum(float(e.get("cost_usd", 0.0) or 0.0) for e in _read_events(run_dir)), 6)
        runs.append(
            {
                "run_id": run_dir.name,
                "started_at": str(meta.get("started_at", "")),
                "package": str(meta.get("package", "")),
                "provider": str(meta.get("provider", "")),
                "mock": bool(meta.get("mock", False)),
                "states": states,
                "total_cost_usd": total_cost,
            }
        )
    return runs


def _task_info(meta: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """title/gate задач из tasks.yaml прогона; если файл недоступен — пусто (id вместо title)."""
    tasks_path = meta.get("tasks_path")
    if not tasks_path:
        return {}
    try:
        package = load_tasks(Path(str(tasks_path)))
    except (OSError, ValueError):
        return {}
    return {t.id: {"title": t.title, "gate": t.gate} for t in package.tasks}


def run_detail(runs_dir: Path, run_id: str) -> dict[str, Any] | None:
    """GET /api/run/<run_id>: мета прогона, задачи, итоги. None = прогон не найден."""
    if not _valid_run_id(run_id):
        return None
    run_dir = runs_dir / run_id
    if not run_dir.is_dir():
        return None
    meta = _read_json(run_dir / "run.json")
    info = _task_info(meta)
    tasks: list[dict[str, Any]] = []
    tasks_dir = run_dir / "tasks"
    if tasks_dir.is_dir():
        for state_path in sorted(tasks_dir.glob("*.json")):
            st = _read_json(state_path)
            task_id = str(st.get("id", state_path.stem))
            extra = info.get(task_id, {})
            tasks.append(
                {
                    "id": task_id,
                    "title": str(extra.get("title", task_id)),
                    "state": str(st.get("state", "queued")),
                    "cost_usd": float(st.get("cost_usd", 0.0) or 0.0),
                    "tokens_in": int(st.get("tokens_in", 0) or 0),
                    "tokens_out": int(st.get("tokens_out", 0) or 0),
                    "repairs": int(st.get("repair_iterations", 0) or 0),
                    "note": str(st.get("note", ""))[:NOTE_LIMIT],
                    "gate": extra.get("gate"),
                }
            )
    totals = {
        "cost_usd": round(sum(t["cost_usd"] for t in tasks), 6),
        "tokens_in": sum(t["tokens_in"] for t in tasks),
        "tokens_out": sum(t["tokens_out"] for t in tasks),
        "repairs": sum(t["repairs"] for t in tasks),
    }
    return {"run": meta, "tasks": tasks, "totals": totals}


def run_events(runs_dir: Path, run_id: str, task: str | None, tail: int) -> list[dict[str, Any]] | None:
    """GET /api/run/<run_id>/events: последние tail событий (фильтр по task). None = 404."""
    if not _valid_run_id(run_id):
        return None
    run_dir = runs_dir / run_id
    if not run_dir.is_dir():
        return None
    events = _read_events(run_dir)
    if task:
        events = [e for e in events if e.get("task_id") == task]
    tail = max(1, min(tail, MAX_TAIL))
    result: list[dict[str, Any]] = []
    for event in events[-tail:]:
        record = dict(event)
        note = record.get("note")
        if isinstance(note, str) and len(note) > NOTE_LIMIT:
            record["note"] = note[:NOTE_LIMIT] + "…"
        result.append(record)
    return result


def _static_index() -> bytes:
    return (Path(__file__).resolve().parent / "ui_static" / "index.html").read_bytes()


def _parse_int(raw: str | None, default: int) -> int:
    try:
        return int(raw) if raw is not None else default
    except ValueError:
        return default


def make_handler(runs_dir: Path) -> type[BaseHTTPRequestHandler]:
    """Класс хендлера с привязанным runs_dir (фабрика — для тестируемости)."""

    class ForgeUIHandler(BaseHTTPRequestHandler):
        server_version = "agent-forge-ui"

        def log_message(self, fmt: str, *args: Any) -> None:
            """Тихий сервер: access-лог в stderr не нужен."""

        def do_GET(self) -> None:  # имя метода — контракт BaseHTTPRequestHandler
            parsed = urlparse(self.path)
            path = parsed.path
            if path in ("/", "/index.html"):
                self._send(200, _static_index(), "text/html; charset=utf-8")
                return
            if path == "/api/runs":
                self._json(200, {"runs": list_runs(runs_dir)})
                return
            if path.startswith("/api/run/"):
                self._handle_run_api(unquote(path[len("/api/run/"):]), parse_qs(parsed.query))
                return
            self._json(404, {"error": "not found"})

        def _handle_run_api(self, rest: str, query: dict[str, list[str]]) -> None:
            if rest.endswith("/events"):
                run_id = rest[: -len("/events")].strip("/")
                task_values = query.get("task")
                task = task_values[0] if task_values else None
                tail_values = query.get("tail")
                tail = _parse_int(tail_values[0] if tail_values else None, 50)
                events = run_events(runs_dir, run_id, task, tail)
                if events is None:
                    self._json(404, {"error": f"run {run_id!r} not found"})
                else:
                    self._json(200, {"events": events})
                return
            run_id = rest.strip("/")
            detail = run_detail(runs_dir, run_id)
            if detail is None:
                self._json(404, {"error": f"run {run_id!r} not found"})
            else:
                self._json(200, detail)

        def _json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send(status, body, "application/json; charset=utf-8")

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            try:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass  # клиент отвалился посреди ответа — сервер не роняем

    return ForgeUIHandler


def create_server(runs_dir: Path, port: int = 8765, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    """Фабрика сервера; порт 0 — эфемерный (тесты)."""
    return ThreadingHTTPServer((host, port), make_handler(runs_dir))


def serve(runs_dir: Path, port: int) -> int:
    """Запуск UI-сервера до Ctrl+C (команда `forge ui`)."""
    server = create_server(runs_dir, port)
    actual_port = int(server.server_address[1])
    print(f"agent-forge UI: http://127.0.0.1:{actual_port}  (runs: {runs_dir}) — Ctrl+C для остановки")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
