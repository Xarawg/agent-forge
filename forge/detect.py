"""Сканер целевого репозитория: стек, тестовые команды, baseline-прогон.

Основа онбординга (`forge init` / `forge wizard`): инструмент сам определяет,
как проверять проект, вместо того чтобы спрашивать это у пользователя.
Acceptance-команды — доверенный shell владельца (SPEC.md §FR-3); baseline
прогоняет их на чистом репо ДО старта кодогенерации: если тесты уже красные,
честно говорим «сначала почини проект», а не стартуем.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

#: Команды из CI-конфигов, которые считаем кандидатами в acceptance.
_CI_TEST_RE = re.compile(
    r"^\s*-?\s*run:\s*(.+?(?:pytest|npm\s+test|npm\s+run\s+\w+|dotnet\s+test|"
    r"go\s+test|cargo\s+test|make\s+\w+).*)$",
    re.MULTILINE,
)


@dataclass
class RepoScan:
    """Результат скана: что за проект и как его проверять."""

    root: Path
    stacks: list[str] = field(default_factory=list)  # python / node / dotnet / go / rust
    test_commands: list[str] = field(default_factory=list)  # кандидаты в acceptance
    has_git: bool = False
    ci_files: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class BaselineResult:
    """Прогон одной baseline-команды на чистом репо."""

    command: str
    exit_code: int
    output_tail: str  # последние символы вывода — для отчёта пользователю


def _detect_python(root: Path, scan: RepoScan) -> None:
    if not (root / "pyproject.toml").exists() and not (root / "requirements.txt").exists():
        return
    scan.stacks.append("python")
    if (root / "tests").is_dir() or (root / "pyproject.toml").exists():
        scan.test_commands.append("python -m pytest -q")


def _detect_node(root: Path, scan: RepoScan) -> None:
    pkg = root / "package.json"
    if not pkg.exists():
        return
    scan.stacks.append("node")
    try:
        scripts = json.loads(pkg.read_text(encoding="utf-8")).get("scripts", {})
    except json.JSONDecodeError:
        scan.notes.append("package.json не парсится — проверьте вручную")
        return
    if "test" in scripts:
        scan.test_commands.append("npm test")
    elif "build" in scripts:
        scan.notes.append("в package.json нет scripts.test — acceptance ограничится build")
        scan.test_commands.append("npm run build")


def _detect_dotnet(root: Path, scan: RepoScan) -> None:
    if list(root.glob("*.sln")) or list(root.glob("**/*.csproj")):
        scan.stacks.append("dotnet")
        scan.test_commands.append("dotnet test")


def _detect_go_rust(root: Path, scan: RepoScan) -> None:
    if (root / "go.mod").exists():
        scan.stacks.append("go")
        scan.test_commands.append("go test ./...")
    if (root / "Cargo.toml").exists():
        scan.stacks.append("rust")
        scan.test_commands.append("cargo test")


def _detect_ci(root: Path, scan: RepoScan) -> None:
    """Команды из CI-конфигов — готовый источник acceptance (их писал владелец)."""
    for ci_dir in (root / ".github" / "workflows", root / ".gitlab-ci.yml"):
        files: list[Path]
        if ci_dir.is_dir():
            files = sorted(ci_dir.glob("*.yml")) + sorted(ci_dir.glob("*.yaml"))
        elif ci_dir.is_file():
            files = [ci_dir]
        else:
            continue
        for path in files:
            rel = path.relative_to(root).as_posix()
            scan.ci_files.append(rel)
            for match in _CI_TEST_RE.finditer(path.read_text(encoding="utf-8")):
                command = match.group(1).strip().strip('"').strip("'")
                if command and command not in scan.test_commands:
                    scan.test_commands.append(command)


def scan_repo(root: Path) -> RepoScan:
    """Определить стек и кандидатов в acceptance-команды по маркерным файлам."""
    root = root.resolve()
    scan = RepoScan(root=root, has_git=(root / ".git").exists())
    _detect_python(root, scan)
    _detect_node(root, scan)
    _detect_dotnet(root, scan)
    _detect_go_rust(root, scan)
    _detect_ci(root, scan)
    if not scan.stacks:
        scan.notes.append("стек не определён — нет pyproject/package.json/*.sln/go.mod/Cargo.toml")
    if scan.stacks and not scan.test_commands:
        scan.notes.append("тестовые команды не найдены — acceptance придётся написать вручную")
    return scan


def run_baseline(root: Path, commands: list[str], timeout: int = 300) -> list[BaselineResult]:
    """Прогнать команды на чистом репо. Зелёный baseline = земля твёрдая."""
    results: list[BaselineResult] = []
    for command in commands:
        try:
            proc = subprocess.run(
                command, shell=True, cwd=root, capture_output=True, text=True, timeout=timeout,
            )
            output = (proc.stdout + proc.stderr).strip()
            results.append(BaselineResult(command, proc.returncode, output[-1500:]))
        except subprocess.TimeoutExpired:
            results.append(BaselineResult(command, 124, f"TIMEOUT после {timeout}s"))
        except OSError as exc:
            results.append(BaselineResult(command, 127, f"команда не запустилась: {exc}"))
    return results


def render_scan(scan: RepoScan) -> str:
    """Скан простым языком — для вывода init/wizard."""
    lines = [f"Репозиторий: {scan.root}"]
    lines.append("Стек: " + (", ".join(scan.stacks) if scan.stacks else "не определён"))
    lines.append("Git: " + ("есть" if scan.has_git else "нет (forge инициализирует)"))
    if scan.ci_files:
        lines.append("CI-конфиги: " + ", ".join(scan.ci_files))
    if scan.test_commands:
        lines.append("Найденные проверки (кандидаты в acceptance):")
        lines.extend(f"  - {cmd}" for cmd in scan.test_commands)
    for note in scan.notes:
        lines.append(f"⚠ {note}")
    return "\n".join(lines)


def render_baseline(results: list[BaselineResult]) -> str:
    """Baseline-прогон простым языком; красный baseline — явный стоп-сигнал."""
    if not results:
        return "Baseline: проверок нет — пропуск."
    lines = ["Baseline (прогон проверок на чистом репо):"]
    for result in results:
        mark = "✅" if result.exit_code == 0 else "❌"
        lines.append(f"  {mark} {result.command} (exit={result.exit_code})")
    if any(r.exit_code != 0 for r in results):
        lines.append(
            "❌ Baseline красный: проект не проходит собственные проверки ДО агентов. "
            "Сначала почините проект — иначе гейты будут ловить чужие ошибки."
        )
    else:
        lines.append("✅ Baseline зелёный — можно запускать очередь.")
    return "\n".join(lines)
