"""Инструменты агента: read_file, write_file, list_dir, run_command (SPEC.md §FR-2).

Scope-контроль: write_file только в scope_paths задачи; canon/ — всегда read-only
(SPEC.md §7). Любая попытка записи вне scope блокируется и логируется (§6.5).

Инструмент git_commit агенту НЕ выдаётся: коммит делает runner после гейта
reviewer (prompts/20: «Коммитить (коммит делает agent-forge)»).
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

#: OpenAI tool schemas (function calling).
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a text file inside the target repository (relative path).",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write a file. Allowed ONLY inside the task scope_paths.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List directory entries inside the target repository.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a whitelisted command (tests/linters) in the target repository.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
]

MAX_OUTPUT = 30000  # калибровка пилотом run-20260819-105828: 4000 резало исходники, агент сжигал шаги
COMMAND_TIMEOUT = 120

#: canon/ на запись закрыт всегда, даже если scope_paths это формально допускают (SPEC.md §7).
DENY_WRITE_PREFIXES = ("canon/",)

#: Запрет установки зависимостей агентом (AF-10): промпт — не граница, блокируем
#: кодом. Новый пакет/зависимость — решение владельца; агент завершает задачу
#: маркером BLOCKED с обоснованием. Acceptance-команды runner'а не затрагиваются.
DENY_COMMAND_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p)
    for p in (
        r"\bnpm\s+(install|i|ci|add|link)\b",
        r"\bnpx\b",
        r"\bpip3?\s+install\b",
        r"\bdotnet\s+add\b",
    )
)

#: Дефолты окружения Windows для дочерних процессов (выявлено при приёмке
#: проектов на dotnet: без ProgramFiles NuGet падает с «Value cannot be null (Parameter 'path1')»).
#: без ProgramFiles NuGet падает с «Value cannot be null (Parameter 'path1')»).
_WINDOWS_ENV_DEFAULTS = {
    "ProgramFiles": r"C:\Program Files",
    "ProgramFiles(x86)": r"C:\Program Files (x86)",
    "ProgramW6432": r"C:\Program Files",
}


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Перевод gitignore-подобной маски (`a/**`, `*.json`, `dir/file`) в regex.

    `**` матчится через разделители (включая ноль сегментов), `*` — внутри сегмента.
    """
    parts = pattern.strip("/").split("/")
    segments = [
        ".*" if part == "**" else re.escape(part).replace(r"\*", "[^/]*").replace(r"\?", "[^/]")
        for part in parts
    ]
    body = "/".join(segments)
    # `a/**` покрывает и сам каталог `a`.
    if body.endswith("/.*"):
        body = body[: -len("/.*")] + r"(?:/.*)?"
    return re.compile(f"^{body}$")


def path_in_scope(rel_path: str, scope_patterns: list[str]) -> bool:
    """True, если относительный путь покрывается хотя бы одной маской scope."""
    rel = PurePosixPath(rel_path).as_posix().removeprefix("./")
    return any(glob_to_regex(p).match(rel) for p in scope_patterns)


class ScopeViolation(Exception):
    """Попытка записи вне scope_paths (SPEC.md §6.5)."""


class CommandNotAllowed(Exception):
    """Команда вне whitelist run_command (SPEC.md §FR-2)."""


class ToolBox:
    """Файловые и shell-инструменты, привязанные к корню целевого репозитория."""

    def __init__(self, root: Path, scope_paths: list[str], allowlist: tuple[str, ...]) -> None:
        self.root = root.resolve()
        self.scope_paths = scope_paths
        self.allowlist = allowlist
        #: Файлы, записанные агентом за задачу (для reviewer diff и коммита).
        self.written_files: list[str] = []
        #: Нарушения scope (для журнала и тестов).
        self.scope_violations: list[str] = []

    # --- диспетчер ----------------------------------------------------------

    def call(self, name: str, args: dict[str, Any]) -> str:
        """Выполнить инструмент; ошибки возвращаются модели текстом, не исключением."""
        try:
            if name == "read_file":
                return self.read_file(str(args.get("path", "")))
            if name == "write_file":
                return self.write_file(str(args.get("path", "")), str(args.get("content", "")))
            if name == "list_dir":
                return self.list_dir(str(args.get("path", ".")))
            if name == "run_command":
                return self.run_command(str(args.get("command", "")))
            return f"ERROR: unknown tool {name!r}"
        except (ScopeViolation, CommandNotAllowed) as exc:
            return f"ERROR: {exc}"
        except Exception as exc:  # файловые ошибки и т.п. — модели в контекст
            return f"ERROR: {type(exc).__name__}: {exc}"

    # --- пути ----------------------------------------------------------------

    def _resolve(self, rel_path: str) -> Path:
        """Абсолютный путь внутри root; выход за root запрещён."""
        candidate = (self.root / rel_path).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ScopeViolation(f"путь {rel_path!r} выходит за корень репозитория")
        return candidate

    def check_write_allowed(self, rel_path: str) -> None:
        rel = PurePosixPath(rel_path).as_posix().removeprefix("./")
        if any(rel == prefix.rstrip("/") or rel.startswith(prefix) for prefix in DENY_WRITE_PREFIXES):
            self.scope_violations.append(rel_path)
            raise ScopeViolation(f"запись в canon/ запрещена (SPEC.md §7): {rel_path!r}")
        if not path_in_scope(rel, self.scope_paths):
            self.scope_violations.append(rel_path)
            raise ScopeViolation(
                f"write_file вне scope задачи заблокирован: {rel_path!r} "
                f"(разрешено: {', '.join(self.scope_paths)})"
            )

    # --- инструменты ----------------------------------------------------------

    def read_file(self, rel_path: str) -> str:
        path = self._resolve(rel_path)
        text = path.read_text(encoding="utf-8")
        return text[:MAX_OUTPUT] + ("\n... [truncated]" if len(text) > MAX_OUTPUT else "")

    def write_file(self, rel_path: str, content: str) -> str:
        self._resolve(rel_path)  # проверка выхода за root
        self.check_write_allowed(rel_path)
        path = self._resolve(rel_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        rel = PurePosixPath(rel_path).as_posix().removeprefix("./")
        if rel not in self.written_files:
            self.written_files.append(rel)
        return f"OK: wrote {rel} ({len(content)} chars)"

    def list_dir(self, rel_path: str) -> str:
        path = self._resolve(rel_path or ".")
        entries = sorted(p.name + ("/" if p.is_dir() else "") for p in path.iterdir())
        return "\n".join(entries) or "(empty)"

    def run_command(self, command: str) -> str:
        # Разрешаем составные команды (`cd x && npm test`), если каждое звено из whitelist.
        segments = re.split(r"&&|\|\||;", command)
        for seg in segments:
            tokens = seg.strip().split()
            if not tokens:
                continue
            cmd = tokens[0]
            if cmd == "cd":
                continue
            if cmd not in self.allowlist:
                raise CommandNotAllowed(
                    f"команда {cmd!r} вне whitelist run_command "
                    f"(разрешены: {', '.join(self.allowlist)})"
                )
            if any(p.search(seg) for p in DENY_COMMAND_PATTERNS):
                raise CommandNotAllowed(
                    f"установка зависимостей запрещена (AF-10): {seg.strip()!r}. "
                    f"Новая зависимость — решение владельца; заверши задачу BLOCKED с обоснованием."
                )
        env = dict(os.environ)
        if os.name == "nt":
            for var, default in _WINDOWS_ENV_DEFAULTS.items():
                env.setdefault(var, default)
        proc = subprocess.run(
            command,
            shell=True,
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT,
            env=env,
        )
        output = (proc.stdout + proc.stderr).strip()
        if len(output) > MAX_OUTPUT:
            output = output[:MAX_OUTPUT] + "\n... [truncated]"
        return f"exit_code={proc.returncode}\n{output}"
