"""Загрузка и рендеринг промптов из prompts/ (SPEC.md §7: текстовка не в коде)."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

PROMPT_FILES = {
    "system": "00_system.md",
    "planner": "10_planner.md",
    "coder": "20_codegen.md",
    "reviewer": "30_reviewer.md",
    "repair": "40_repair.md",
    "task_template": "50_task_template.md",
}


def load_prompt(prompts_dir: Path, name: str) -> str:
    path = prompts_dir / PROMPT_FILES[name]
    return path.read_text(encoding="utf-8")


def render(template: str, values: dict[str, str]) -> str:
    """Подстановка {{плейсхолдеров}} шаблона 50_task_template.md."""
    out = template
    for key, value in values.items():
        out = out.replace("{{" + key + "}}", value)
    return out


def prompts_version(prompts_dir: Path) -> str:
    """Версия библиотеки промптов для воспроизводимости (SPEC.md §FR-7).

    Git-хеш последнего коммита, трогавшего prompts/; вне git — sha256 содержимого.
    """
    try:
        proc = subprocess.run(
            ["git", "log", "-1", "--format=%H", "--", "prompts/"],
            cwd=prompts_dir.parent,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return "git:" + proc.stdout.strip()[:12]
    except (OSError, subprocess.TimeoutExpired):
        pass
    digest = hashlib.sha256()
    for path in sorted(prompts_dir.glob("*.md")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return "sha256:" + digest.hexdigest()[:12]
