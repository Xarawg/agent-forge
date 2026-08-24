"""forge map + репо-контекст (вариант B: детерминированный AST-скан, без LLM)."""

import json
from pathlib import Path

from forge.map import (
    build_repo_context,
    load_entity_index,
    neighbors_of,
    scan_entities,
    write_map,
)

PKG = {
    "storage.py": (
        '"""Хранилище."""\n'
        "import json\n\n"
        "def load(db: str) -> list:\n    return []\n\n"
        "def save(notes: list, db: str) -> None:\n    pass\n"
    ),
    "core.py": (
        '"""Ядро."""\n'
        "from storage import load, save\n\n"
        "def add_note(text: str, tags: list | None = None) -> dict:\n    return {}\n\n"
        "class NoteService:\n"
        "    def add(self, text: str) -> dict:\n        return {}\n"
        "    def _hidden(self) -> None:\n        pass\n"
    ),
    "cli.py": (
        "import core\n\n"
        "def main(argv: list[str]) -> None:\n    pass\n"
    ),
    "tests/test_x.py": "def test_ok():\n    assert True\n",
}


def _make_pkg(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    for rel, body in PKG.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return root


def test_scan_entities_extracts_public_surface(tmp_path: Path) -> None:
    root = _make_pkg(tmp_path)
    maps = scan_entities(root)
    assert set(maps) == {"storage.py", "core.py", "cli.py", "tests/test_x.py"}

    core = maps["core.py"]
    kinds = {e.name: e.kind for e in core.entities}
    assert kinds == {"add_note": "function", "NoteService": "class"}
    sigs = {e.signature for e in core.entities}
    assert "def add_note(text: str, tags: list | None=None) -> dict" in sigs
    # у класса видны публичные методы, приватные скрыты
    cls = next(e for e in core.entities if e.kind == "class")
    assert "add" in cls.signature and "_hidden" not in cls.signature


def test_scan_resolves_local_imports(tmp_path: Path) -> None:
    root = _make_pkg(tmp_path)
    maps = scan_entities(root)
    assert maps["core.py"].imports == ["storage.py"]
    assert maps["cli.py"].imports == ["core.py"]
    assert maps["storage.py"].imports == []  # внешний json — не локальный


def test_write_map_creates_canon_and_docs(tmp_path: Path) -> None:
    root = _make_pkg(tmp_path)
    canon, docs = write_map(root, scan_entities(root))
    assert canon.name == "entities.json" and canon.parent.name == "canon"
    payload = json.loads(canon.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert payload["files"]["core.py"]["entities"][0]["name"] == "add_note"
    text = docs.read_text(encoding="utf-8")
    assert "Карта сущностей" in text and "NoteService" in text


def test_neighbors_graph_both_directions(tmp_path: Path) -> None:
    root = _make_pkg(tmp_path)
    write_map(root, scan_entities(root))
    index = load_entity_index(root)
    files = index["files"]
    # scope = core.py: соседи — storage (импортирует) и cli (импортируется из)
    assert neighbors_of({"core.py"}, files) == {"storage.py", "cli.py"}
    assert neighbors_of({"storage.py"}, files) == {"core.py"}


def test_repo_context_empty_without_artifacts(tmp_path: Path) -> None:
    root = _make_pkg(tmp_path)
    assert build_repo_context(root, ["core.py"]) == ""


def test_repo_context_catalog_and_neighbors(tmp_path: Path) -> None:
    root = _make_pkg(tmp_path)
    write_map(root, scan_entities(root))
    context = build_repo_context(root, ["core.py"])
    # анти-дубль каталог: все сущности проекта
    assert "НЕ дублируй" in context
    assert "function `add_note` — `core.py`" in context
    assert "function `load` — `storage.py`" in context
    # сигнатуры соседей, но не тела
    assert "Сигнатуры связанных модулей" in context
    assert "def load(db: str) -> list" in context
    assert "return []" not in context  # тела соседей в контекст не попадают


def test_repo_context_agents_md(tmp_path: Path) -> None:
    root = _make_pkg(tmp_path)
    (root / "AGENTS.md").write_text("# Правила репо\nСтек: python, pytest.\n", encoding="utf-8")
    context = build_repo_context(root, ["core.py"])
    assert "AGENTS.md целевого репозитория" in context
    assert "Стек: python, pytest" in context
