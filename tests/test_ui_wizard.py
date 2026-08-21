"""UI /wizard: форма черновика задач — просмотр карточками и сохранение (ob3)."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

from forge.models import load_tasks
from forge.ui import create_server

DRAFT = """\
package: wizard-draft
tasks:
  - id: draft-1
    title: "Первая задача"
    spec_ref: "s"
    scope_paths: ["src/**"]
    depends_on: []
    acceptance: ["python -m pytest -q"]
    budget: {max_tokens: 150000, max_cost_usd: 0.3}
    gate: review
  - id: draft-2
    title: "Вторая задача"
    spec_ref: "s"
    scope_paths: ["docs/**"]
    depends_on: ["draft-1"]
    acceptance: ["python -c \\"print(1)\\""]
    budget: {max_tokens: 150000, max_cost_usd: 0.3}
"""


@pytest.fixture()
def draft_file(tmp_path: Path) -> Path:
    path = tmp_path / "tasks.wizard.yaml"
    path.write_text(DRAFT, encoding="utf-8")
    return path


@pytest.fixture()
def ui_server(tmp_path: Path) -> Iterator[str]:
    runs = tmp_path / "runs"
    runs.mkdir()
    server = create_server(runs, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _get_page(base: str, path: str) -> tuple[int, str]:
    request = urllib.request.Request(base + path)
    try:
        with urllib.request.urlopen(request, timeout=5) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def _post_form(base: str, path: str, fields: dict[str, str]) -> tuple[int, str]:
    body = urllib.parse.urlencode(fields).encode("utf-8")
    request = urllib.request.Request(base + path, data=body, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=5) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def test_wizard_form_renders_cards(ui_server: str, draft_file: Path) -> None:
    status, page = _get_page(ui_server, f"/wizard?file={draft_file}")
    assert status == 200
    assert "draft-1" in page and "Первая задача" in page
    assert "src/**" in page and "python -m pytest -q" in page
    assert "Прогноз стоимости" in page and "$0.60" in page  # 0.30 + 0.30


def test_wizard_form_requires_yaml(ui_server: str, tmp_path: Path) -> None:
    status, _ = _get_page(ui_server, "/wizard?file=/etc/passwd")
    assert status == 400
    not_yaml = tmp_path / "notes.txt"
    not_yaml.write_text("x", encoding="utf-8")
    status, _ = _get_page(ui_server, f"/wizard?file={not_yaml}")
    assert status == 400


def test_wizard_save_roundtrip(ui_server: str, draft_file: Path) -> None:
    fields = {
        "file": str(draft_file),
        "t0_id": "draft-1", "t0_title": "Переименованная",
        "t0_spec_ref": "s2", "t0_scope": "src/**\nlib/**",
        "t0_acceptance": "python -m pytest -q",
        "t0_max_tokens": "200000", "t0_max_cost": "0.45", "t0_gate": "review",
        "t1_id": "draft-2", "t1_title": "Вторая задача",
        "t1_spec_ref": "s", "t1_scope": "docs/**",
        "t1_acceptance": "python -c \"print(1)\"",
        "t1_max_tokens": "150000", "t1_max_cost": "0.3", "t1_gate": "",
    }
    status, page = _post_form(ui_server, "/wizard/save", fields)
    assert status == 200 and "сохранён" in page
    package = load_tasks(draft_file)
    first, second = package.tasks
    assert first.title == "Переименованная"
    assert first.scope_paths == ["src/**", "lib/**"]
    assert first.budget.max_cost_usd == 0.45
    assert second.depends_on == ["draft-1"]  # depends_on сохранён из исходника


def test_wizard_save_rejects_invalid_without_touching_file(
    ui_server: str, draft_file: Path
) -> None:
    before = draft_file.read_text(encoding="utf-8")
    fields = {
        "file": str(draft_file),
        "t0_id": "draft-1", "t0_title": "x", "t0_spec_ref": "s",
        "t0_scope": "",  # пустой scope — нарушение контракта
        "t0_acceptance": "python -m pytest -q",
        "t0_max_tokens": "", "t0_max_cost": "", "t0_gate": "",
    }
    status, page = _post_form(ui_server, "/wizard/save", fields)
    assert status == 200
    assert "Контракт не пройден" in page
    assert draft_file.read_text(encoding="utf-8") == before  # файл не изменён


def test_wizard_save_bad_cost(ui_server: str, draft_file: Path) -> None:
    fields = {
        "file": str(draft_file),
        "t0_id": "draft-1", "t0_title": "x", "t0_spec_ref": "s",
        "t0_scope": "src/**", "t0_acceptance": "python -m pytest -q",
        "t0_max_tokens": "", "t0_max_cost": "дорого", "t0_gate": "",
    }
    status, page = _post_form(ui_server, "/wizard/save", fields)
    assert status == 200 and "не число" in page


def test_wizard_api_still_json_404(ui_server: str) -> None:
    status, body = _get_page(ui_server, "/nope")
    assert status == 404
    assert json.loads(body)["error"] == "not found"
