"""forge map: карта сущностей Python-проекта (AST, детерминированно, без LLM).

Зачем (dogfooding-практика 2026, вариант B): при доработке сервиса модель должна
видеть связанные модели/контракты (иначе — дубли), но не грузить в контекст
несвязанные файлы (иначе — расход токенов). Карта решает обе стороны:

- `canon/entities.json` — машиночитаемый каталог: имя/вид/сигнатура/файл/imports;
  читается runner'ом при сборке контекста задачи (`build_repo_context`).
- `docs/ENTITIES.md` — человекочитаемая версия для onboarding'а новичка.

Перегенерация — после каждого принятого прогона; артефакт read-only для агентов
(как и весь canon/).
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field
from pathlib import Path

#: Каталоги, которые не сканируем никогда.
SKIP_DIRS = {
    ".git", ".venv", "venv", "__pycache__", "node_modules", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "dist", "build", "runs", ".tmp-e2e",
    "site-packages", ".idea", ".vscode",
}

#: Потолок размера блока репо-контекста в промпте задачи (символы).
REPO_CONTEXT_LIMIT = 12000

#: Потолок выдержки из AGENTS.md целевого репозитория (символы).
AGENTS_EXCERPT_LIMIT = 4000

#: Потолок строк анти-дубль каталога (имена сущностей целиком).
CATALOG_LIMIT = 250


@dataclass
class Entity:
    """Публичная сущность модуля: класс (с методами) или функция верхнего уровня."""

    name: str
    kind: str  # "class" | "function"
    signature: str
    line: int


@dataclass
class FileMap:
    """Карта одного .py-файла: сущности + локальные импорты."""

    path: str
    entities: list[Entity] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)  # пути локальных модулей


def _signature(node: ast.AST) -> str:
    """Сигнатура без тела: `def f(a: int) -> str` / `class C(Base)`."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        args = ast.unparse(node.args)
        ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
        return f"{prefix} {node.name}({args}){ret}"
    if isinstance(node, ast.ClassDef):
        bases = ", ".join(ast.unparse(b) for b in node.bases)
        methods = [
            n.name for n in node.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.name.startswith("_")
        ]
        sig = f"class {node.name}({bases})" if bases else f"class {node.name}"
        if methods:
            sig += ": " + ", ".join(methods)
        return sig
    return ""


def _local_imports(node: ast.Module, file_path: Path, root: Path) -> list[str]:
    """Импорты, разрешимые в локальные .py-файлы проекта (внешние пакеты мимо)."""
    resolved: set[str] = set()
    for stmt in ast.walk(node):
        names: list[str] = []
        if isinstance(stmt, ast.Import):
            names = [a.name for a in stmt.names]
        elif isinstance(stmt, ast.ImportFrom):
            if stmt.module:
                names = [stmt.module]
            if stmt.level:  # относительный импорт: от каталога файла вверх на level-1
                base = file_path.parent
                for _ in range(max(stmt.level - 1, 0)):
                    base = base.parent
                if stmt.module:
                    names = [str(base / stmt.module.replace(".", "/"))]
                else:
                    names = [str(base)]
        for name in names:
            for candidate in _candidates(name, file_path, root):
                if candidate is not None:
                    resolved.add(candidate)
    return sorted(resolved)


def _candidates(dotted: str, file_path: Path, root: Path) -> list[str | None]:
    """Возможные пути модуля: от корня проекта и от каталога текущего файла."""
    rel = dotted.replace(".", "/")
    if not rel.startswith("/") and ":" not in rel:
        bases = [root / rel, file_path.parent / rel]
    else:  # уже путь от относительного импорта
        bases = [Path(rel)]
    for base in bases:
        for candidate in (base.with_suffix(".py"), base / "__init__.py"):
            try:
                candidate.relative_to(root)
            except ValueError:
                continue
            if candidate.is_file():
                return [str(candidate.relative_to(root)).replace("\\", "/")]
    return [None]


def scan_entities(root: Path) -> dict[str, FileMap]:
    """AST-скан всех .py проекта. Битые файлы пропускаются с записью в errors."""
    root = root.resolve()
    maps: dict[str, FileMap] = {}
    for py in sorted(root.rglob("*.py")):
        if any(part in SKIP_DIRS for part in py.parts):
            continue
        rel = str(py.relative_to(root)).replace("\\", "/")
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        fmap = FileMap(path=rel)
        for node in tree.body:  # только верхний уровень — публичная поверхность
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                is_dunder = node.name.startswith("__") and node.name.endswith("__")
                if node.name.startswith("_") and not is_dunder:
                    continue
                fmap.entities.append(
                    Entity(name=node.name,
                           kind="class" if isinstance(node, ast.ClassDef) else "function",
                           signature=_signature(node), line=node.lineno)
                )
        fmap.imports = [p for p in _local_imports(tree, py, root) if p != rel]
        maps[rel] = fmap
    return maps


def write_map(root: Path, maps: dict[str, FileMap]) -> tuple[Path, Path]:
    """Пишет canon/entities.json (машиночитаемо) и docs/ENTITIES.md (человекочитаемо)."""
    root = root.resolve()
    canon = root / "canon" / "entities.json"
    canon.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "generator": "forge map (AST, без LLM)",
        "files": {
            path: {
                "entities": [
                    {"name": e.name, "kind": e.kind, "signature": e.signature, "line": e.line}
                    for e in fm.entities
                ],
                "imports": fm.imports,
            }
            for path, fm in maps.items()
        },
    }
    canon.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    docs = root / "docs" / "ENTITIES.md"
    docs.parent.mkdir(parents=True, exist_ok=True)
    docs.write_text(render_entities_md(maps), encoding="utf-8")
    return canon, docs


def render_entities_md(maps: dict[str, FileMap]) -> str:
    """Человекочитаемая карта: по каталогам, сущности и локальные зависимости."""
    lines = [
        "# Карта сущностей проекта",
        "",
        "Сгенерировано `forge map` (AST-скан, без LLM). Перегенерация после каждого",
        "принятого прогона. Машиночитаемая версия — `canon/entities.json` (read-only",
        "для агентов). При доработке модуля модель получает из этой карты сигнатуры",
        "связанных сущностей — не открывая несвязанные файлы.",
        "",
    ]
    by_dir: dict[str, list[FileMap]] = {}
    for fm in maps.values():
        by_dir.setdefault(str(Path(fm.path).parent).replace("\\", "/"), []).append(fm)
    total = sum(len(fm.entities) for fm in maps.values())
    lines.append(f"Файлов: {len(maps)} · публичных сущностей: {total}")
    for directory in sorted(by_dir):
        lines += ["", f"## `{directory}/`", ""]
        for fm in by_dir[directory]:
            lines.append(f"### `{fm.path}`")
            for e in fm.entities:
                lines.append(f"- `{e.signature}` (строка {e.line})")
            if fm.imports:
                lines.append(f"- локальные импорты: {', '.join(f'`{i}`' for i in fm.imports)}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# --- контекст задачи по графу (фаза 3) ---------------------------------------


def load_entity_index(root: Path) -> dict[str, object] | None:
    """canon/entities.json целевого репо; отсутствует/битый — None (молча)."""
    path = root / "canon" / "entities.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data.get("files"), dict) else None


def _scope_files(scope_paths: list[str], files: dict[str, object]) -> set[str]:
    """Файлы карты, попадающие под scope задачи (маски `dir/**` → каталог)."""
    matched: set[str] = set()
    for raw in scope_paths:
        prefix = raw.rstrip("*").rstrip("/")
        for path in files:
            if path == prefix or path.startswith(prefix.rstrip("/") + "/") or Path(path).name == prefix:
                matched.add(path)
    return matched


def neighbors_of(scope: set[str], files: dict[str, object]) -> set[str]:
    """Соседи глубины 1 по графу импортов в обе стороны (без самих scope-файлов)."""
    neighbors: set[str] = set()
    for path, info in files.items():
        imports = set(info.get("imports", [])) if isinstance(info, dict) else set()
        if path in scope:
            neighbors |= imports
        elif imports & scope:
            neighbors.add(path)
    return neighbors - scope


def build_repo_context(root: Path, scope_paths: list[str]) -> str:
    """Репо-контекст для промпта coder'а (SPEC.md §FR-2, практика repo-map).

    Три слоя: AGENTS.md целевого репо (выдержка) → анти-дубль каталог имён всех
    сущностей (чтобы модель не писала дубли) → сигнатуры соседей по графу
    импортов (связанные модели/контракты — без чтения их файлов целиком).
    Нет ни entities.json, ни AGENTS.md — пустая строка (поведение как раньше).
    """
    root = root.resolve()
    parts: list[str] = []

    agents = root / "AGENTS.md"
    if agents.is_file():
        try:
            excerpt = agents.read_text(encoding="utf-8")[:AGENTS_EXCERPT_LIMIT]
        except OSError:
            excerpt = ""
        if excerpt.strip():
            parts.append(f"## AGENTS.md целевого репозитория (выдержка)\n{excerpt}")

    index = load_entity_index(root)
    if index:
        files: dict[str, object] = index["files"]  # type: ignore[assignment]
        catalog: list[str] = []
        for path in sorted(files):
            info = files[path]
            if not isinstance(info, dict):
                continue
            for e in info.get("entities", []):
                catalog.append(f"- {e.get('kind', '?')} `{e.get('name', '?')}` — `{path}`")
                if len(catalog) >= CATALOG_LIMIT:
                    break
        if catalog:
            parts.append(
                "## Уже существующие сущности проекта (НЕ дублируй — импортируй)\n"
                + "\n".join(catalog)
            )
        scope = _scope_files(scope_paths, files)
        neighbor_signatures: list[str] = []
        for path in sorted(neighbors_of(scope, files)):
            info = files[path]
            if not isinstance(info, dict):
                continue
            sigs = [f"  - `{e.get('signature', '')}`" for e in info.get("entities", [])]
            if sigs:
                neighbor_signatures.append(f"### `{path}`\n" + "\n".join(sigs))
        if neighbor_signatures:
            parts.append(
                "## Сигнатуры связанных модулей (соседи scope по импортам; читать\n"
                "## эти файлы целиком НЕ нужно, если хватает сигнатур)\n"
                + "\n\n".join(neighbor_signatures)
            )

    context = "\n\n".join(parts)
    return context[:REPO_CONTEXT_LIMIT]
