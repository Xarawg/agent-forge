"""Веб-UI `forge ui`: канбан прогонов поверх runs/ (SPEC.md §FR-4).

Почти всё — только чтение: сервер не мутирует runs/. Единственное исключение —
/wizard: форма просмотра/правки черновика tasks.wizard.yaml (онбординг ob3);
мутация ограничена перезаписью одного YAML-файла черновика, runs/ не трогается.
Строго stdlib (http.server/json/urllib) — ноль новых зависимостей. Статика
читается из forge/ui_static/ рядом с модулем (работает и в editable-install).
"""

from __future__ import annotations

import html
import json
import os
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import yaml

from .lint import lint_tasks
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
                if ".history" in state_path.name:
                    continue  # снапшоты диалога (AF-12) — не состояния задач
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
            if ".history" in state_path.name:
                continue  # снапшоты диалога (AF-12) — не состояния задач
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


# --- /wizard: форма черновика задач (onboarding ob3) ---------------------------

_WIZARD_CSS = (
    "body{background:#0d1117;color:#e6edf3;font:14px/1.5 system-ui,sans-serif;margin:2em auto;"
    "max-width:900px;padding:0 1em}"
    ".card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:1em;margin:1em 0}"
    "label{display:block;color:#8b949e;font-size:12px;margin-top:.6em}"
    "input,textarea{width:100%;box-sizing:border-box;background:#0d1117;color:#e6edf3;"
    "border:1px solid #30363d;border-radius:6px;padding:.4em;font:13px monospace}"
    "textarea{min-height:4.5em}"
    "button{background:#238636;color:#fff;border:0;border-radius:6px;padding:.6em 1.4em;"
    "font-size:15px;cursor:pointer}"
    ".warn{color:#d29922}.err{color:#f85149}.ok{color:#3fb950}.cap{color:#8b949e}"
    "a{color:#58a6ff}"
)


def _wizard_page(file: Path, message: str = "", message_class: str = "ok") -> str:
    """HTML-форма черновика: карточки задач, lint-предупреждения, прогноз."""
    esc = html.escape
    parts = [
        f"<html><head><meta charset='utf-8'><title>forge wizard</title>"
        f"<style>{_WIZARD_CSS}</style></head><body>",
        f"<h1>Черновик очереди</h1><p class='cap'>{esc(str(file))} · "
        "<a href='/'>← канбан</a></p>",
    ]
    if message:
        parts.append(f"<p class='{message_class}'>{esc(message)}</p>")
    try:
        raw: Any = yaml.safe_load(file.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        parts.append(f"<p class='err'>Не читается: {esc(str(exc))}</p></body></html>")
        return "".join(parts)
    tasks = [t for t in (raw or {}).get("tasks", []) if isinstance(t, dict)]

    _errors, warnings = lint_tasks(file)
    for warning in warnings:
        parts.append(f"<p class='warn'>⚠ {esc(warning)}</p>")

    total_cap = 0.0
    parts.append(f"<form method='post' action='/wizard/save'>"
                 f"<input type='hidden' name='file' value='{esc(str(file))}'>")
    for i, task in enumerate(tasks):
        budget = task.get("budget") or {}
        cap = float(budget.get("max_cost_usd") or 0.0)
        total_cap += cap
        scope = "\n".join(str(p) for p in task.get("scope_paths") or [])
        acceptance = "\n".join(str(c) for c in task.get("acceptance") or [])
        parts.append(f"""<div class='card'>
<b>{esc(str(task.get('id', f'task-{i}')))}</b>
<input type='hidden' name='t{i}_id' value='{esc(str(task.get('id', '')))}'>
<label>Что делаем (title)</label>
<input name='t{i}_title' value='{esc(str(task.get('title', '')))}'>
<label>Источник истины (spec_ref)</label>
<input name='t{i}_spec_ref' value='{esc(str(task.get('spec_ref', '')))}'>
<label>Какие файлы может трогать coder (scope_paths, по одному на строку)</label>
<textarea name='t{i}_scope'>{esc(scope)}</textarea>
<label>Как проверяем (acceptance, по одной команде на строку) — пишете вы, coder их не трогает</label>
<textarea name='t{i}_acceptance'>{esc(acceptance)}</textarea>
<label>Кап токенов / кап $ / гейт (метка или пусто)</label>
<input name='t{i}_max_tokens' value='{esc(str(budget.get('max_tokens', '')))}'>
<input name='t{i}_max_cost' value='{esc(str(budget.get('max_cost_usd', '')))}'>
<input name='t{i}_gate' value='{esc(str(task.get('gate') or ''))}'>
</div>""")
    parts.append(f"<p class='cap'>Прогноз стоимости: не больше ~${total_cap:.2f} (сумма капов).</p>")
    parts.append("<button type='submit'>Сохранить черновик</button></form>")
    parts.append("<p class='cap'>После сохранения — запуск из терминала: "
                 f"<code>forge run --tasks {esc(file.name)} --target .</code></p>")
    parts.append("</body></html>")
    return "".join(parts)


def _wizard_save(file: Path, form: dict[str, list[str]]) -> tuple[bool, str]:
    """Перезапись черновика из формы. Валидация контракта ДО записи (atomic)."""

    def field(name: str) -> str:
        values = form.get(name)
        return values[0].strip() if values else ""

    tasks: list[dict[str, Any]] = []
    for i in range(len([k for k in form if k.endswith("_id")])):
        budget: dict[str, Any] = {}
        if field(f"t{i}_max_tokens"):
            budget["max_tokens"] = _parse_int(field(f"t{i}_max_tokens"), 0)
        if field(f"t{i}_max_cost"):
            try:
                budget["max_cost_usd"] = float(field(f"t{i}_max_cost"))
            except ValueError:
                return False, f"Задача #{i}: max_cost не число: {field(f't{i}_max_cost')!r}"
        task: dict[str, Any] = {
            "id": field(f"t{i}_id"),
            "title": field(f"t{i}_title"),
            "spec_ref": field(f"t{i}_spec_ref"),
            "scope_paths": [ln for ln in field(f"t{i}_scope").splitlines() if ln.strip()],
            "depends_on": [],
            "acceptance": [ln for ln in field(f"t{i}_acceptance").splitlines() if ln.strip()],
            "budget": budget,
        }
        if field(f"t{i}_gate"):
            task["gate"] = field(f"t{i}_gate")
        tasks.append(task)

    # depends_on сохраняем из исходного файла (в форме не редактируется).
    try:
        old_raw: Any = yaml.safe_load(file.read_text(encoding="utf-8"))
        old_deps = {str(t.get("id")): t.get("depends_on") or []
                    for t in (old_raw or {}).get("tasks", []) if isinstance(t, dict)}
        for task in tasks:
            task["depends_on"] = [str(d) for d in old_deps.get(str(task["id"]), [])]
    except (OSError, yaml.YAMLError):
        pass

    body = yaml.safe_dump({"package": "wizard-draft", "tasks": tasks},
                          allow_unicode=True, sort_keys=False)
    header = "# Черновик (отредактирован в UI /wizard). Подтверждение запуска — гейт №1.\n"
    # Атомарно: temp-файл рядом + валидация контракта + os.replace.
    tmp = Path(tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=file.parent, delete=False, suffix=".tmp").name)
    try:
        tmp.write_text(header + body, encoding="utf-8")
        load_tasks(tmp)  # контракт: DAG, kebab-id, scope
    except (ValueError, yaml.YAMLError, OSError) as exc:
        tmp.unlink(missing_ok=True)
        return False, f"Контракт не пройден, файл НЕ изменён: {exc}"
    os.replace(tmp, file)
    return True, "Черновик сохранён и проходит контракт tasks.yaml."


def _valid_wizard_file(raw: str) -> Path | None:
    """Путь к черновику из параметра: существующий *.yaml, без ограничений по
    расположению (локальный инструмент владельца), но только YAML."""
    path = Path(raw)
    if not raw or path.suffix not in (".yaml", ".yml") or not path.is_file():
        return None
    return path


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
            if path == "/wizard":
                file_param = parse_qs(parsed.query).get("file", [""])[0]
                wizard_file = _valid_wizard_file(unquote(file_param))
                if wizard_file is None:
                    self._json(400, {"error": "нужен ?file=<существующий .yaml черновика>"})
                else:
                    self._send(200, _wizard_page(wizard_file).encode("utf-8"),
                               "text/html; charset=utf-8")
                return
            self._json(404, {"error": "not found"})

        def do_POST(self) -> None:  # единственная мутация UI: перезапись черновика
            parsed = urlparse(self.path)
            if parsed.path != "/wizard/save":
                self._json(404, {"error": "not found"})
                return
            length = _parse_int(self.headers.get("Content-Length"), 0)
            form = parse_qs(self.rfile.read(length).decode("utf-8"))
            wizard_file = _valid_wizard_file(form.get("file", [""])[0])
            if wizard_file is None:
                self._json(400, {"error": "некорректный file"})
                return
            ok, message = _wizard_save(wizard_file, form)
            self._send(200, _wizard_page(wizard_file, message,
                                         "ok" if ok else "err").encode("utf-8"),
                       "text/html; charset=utf-8")

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
    print(f"форма черновика wizard: http://127.0.0.1:{actual_port}/wizard?file=<путь к tasks.wizard.yaml>")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
