"""`forge init` — подготовка целевого проекта одной командой (GAP_ANALYSIS §2-A2).

Проверяет/инициализирует git, создаёт skeleton tasks.yaml с учётом найденного
стека, проверяет наличие .env и ключа провайдера (НЕ читая значения, NFR-3),
прогоняет baseline найденных проверок и печатает следующие шаги.
API-ключ не требуется: init работает до любой кодогенерации.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .detect import render_baseline, render_scan, run_baseline, scan_repo
from .profiles import DEFAULT_PROFILE, get_profile, render_profiles

SKELETON_NAME = "tasks.yaml"


def _ensure_git(root: Path, lines: list[str]) -> None:
    """Git-репозиторий нужен для веток forge/<id> (SPEC.md §1.4)."""
    if (root / ".git").exists():
        lines.append("Git: репозиторий уже есть.")
        return
    proc = subprocess.run(
        ["git", "init"], cwd=root, capture_output=True, text=True, timeout=30,
    )
    if proc.returncode == 0:
        lines.append("Git: репозиторий инициализирован (git init).")
    else:
        lines.append(f"⚠ Git: `git init` не удался — {proc.stderr.strip()[:200]}")


def _skeleton_yaml(scan_commands: list[str], profile_name: str) -> str:
    """Skeleton tasks.yaml: пример задачи + найденные проверки в комментариях."""
    profile = get_profile(profile_name)
    suggested = (
        "\n".join(f"#   - \"{cmd}\"" for cmd in scan_commands)
        or "#   (проверки не найдены — напишите свои)"
    )
    return f"""# Очередь задач agent-forge — формат: config/tasks.example.yaml.
# Профиль: {profile.name} ({profile.hint})
# Найденные в репозитории проверки (кандидаты в acceptance):
{suggested}
#
# Правило: acceptance-команды должны быть написаны ВАМИ и проверять главное.
# Тестовые файлы держите ВНЕ scope_paths задачи — тогда coder физически
# не может подправить тест под себя (scope-контроль, SPEC.md §FR-2).

package: my-package

tasks:
  - id: example-1
    title: "Пример задачи — замените на свою"
    spec_ref: "SPEC.md §1"
    scope_paths:
      - "src/**"
    depends_on: []
    acceptance:
      - "python -c \\"print('ok')\\""
    budget:
      max_tokens: {profile.task_max_tokens}
      max_cost_usd: {profile.task_max_cost_usd:.2f}
    # gate: wave-1   # человеческий гейт: прогон встанет до `forge accept example-1`
"""


def _write_skeleton(root: Path, scan_commands: list[str], profile_name: str,
                    force: bool, lines: list[str]) -> Path:
    path = root / SKELETON_NAME
    if path.exists() and not force:
        lines.append(f"{SKELETON_NAME}: уже существует — не трогаю (перезапись: --force).")
        return path
    path.write_text(_skeleton_yaml(scan_commands, profile_name), encoding="utf-8")
    lines.append(f"{SKELETON_NAME}: skeleton создан — отредактируйте под свой пакет (гейт №1).")
    return path


def _check_env(forge_root: Path, lines: list[str]) -> None:
    """Наличие .env и ключа — только факт, значения не читаются (NFR-3)."""
    env_path = forge_root / ".env"
    if not env_path.exists():
        lines.append(f"⚠ .env не найден ({env_path}). Скопируйте .env.example и добавьте ключ "
                     "провайдера — либо работайте в mock-режиме (FORGE_MOCK=1).")
        return
    raw = env_path.read_text(encoding="utf-8")
    keys = {line.split("=", 1)[0].strip() for line in raw.splitlines()
            if "=" in line and not line.strip().startswith("#")}
    if any(k.endswith("_API_KEY") or k == "FORGE_API_KEY" for k in keys):
        lines.append(".env: есть, ключ провайдера задан (значение не читалось).")
    else:
        lines.append("⚠ .env есть, но переменной *_API_KEY в нём нет — "
                     "добавьте ключ или используйте FORGE_MOCK=1.")


def init_project(target: Path, forge_root: Path, profile_name: str = DEFAULT_PROFILE,
                 force: bool = False, check: bool = True) -> str:
    """Вся подготовка проекта; возвращает отчёт простым языком."""
    root = target.resolve()
    if not root.is_dir():
        raise ValueError(f"Каталог {root} не существует")
    profile = get_profile(profile_name)

    lines: list[str] = [f"forge init — подготовка проекта (профиль: {profile.name})", ""]
    scan = scan_repo(root)
    lines.append(render_scan(scan))
    lines.append("")
    _ensure_git(root, lines)
    tasks_path = _write_skeleton(root, scan.test_commands, profile.name, force, lines)
    _check_env(forge_root, lines)

    if check and scan.test_commands:
        lines.append("")
        lines.append(render_baseline(run_baseline(root, scan.test_commands)))

    lines += [
        "",
        render_profiles(),
        "",
        "Следующие шаги:",
        f"  1. Отредактируйте {tasks_path.name} под свою задачу (гейт №1 — задания пишете вы)",
        "  2. Пробный прогон без ключа и без денег:",
        f"     FORGE_MOCK=1 forge run --tasks {tasks_path.name} --target .",
        "  3. Или опишите задачу словами — черновик соберёт wizard:",
        "     forge wizard --target . --prompt \"что нужно сделать\"",
        "  4. Наблюдение: forge status · forge ui · отчёт: forge report --plain",
    ]
    return "\n".join(lines)


def env_has_api_key(forge_root: Path) -> bool:
    """Факт наличия ключа в .env/окружении (для тестов и wizard)."""
    if any(k.endswith("_API_KEY") or k == "FORGE_API_KEY" for k in os.environ):
        return True
    env_path = forge_root / ".env"
    if not env_path.exists():
        return False
    return any(
        (k.endswith("_API_KEY") or k == "FORGE_API_KEY")
        for k in (line.split("=", 1)[0].strip()
                  for line in env_path.read_text(encoding="utf-8").splitlines()
                  if "=" in line and not line.strip().startswith("#"))
    )
