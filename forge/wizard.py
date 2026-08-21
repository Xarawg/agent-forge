"""`forge wizard` — промпт человеческим языком → готовый черновик настроек.

Поток: скан репо (detect) → baseline → planner-роль генерирует черновик задач →
нормализация (капы из профиля, найденные проверки в acceptance, гейты) →
прогноз стоимости → tasks.wizard.yaml. Ничего не запускается: черновик
подтверждает человек — это и есть гейт №1 (онбординг-решение 2026-08-21).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .agents import log_model_call
from .config import ForgeConfig
from .detect import render_baseline, render_scan, run_baseline, scan_repo
from .journal import Journal, new_run_id
from .llm import LLMClient
from .models import load_tasks
from .profiles import DEFAULT_PROFILE, Profile, get_profile
from .prompts import load_prompt

OUT_NAME = "tasks.wizard.yaml"

#: Признаки тестовых путей в scope — acceptance должен быть заморожен вне scope
#: coder'а, иначе гейт №2 превращается в самопроверку (железное правило №1).
_TEST_MARKERS = ("test", "tests", "spec", "e2e")


def _scan_summary(scan_root: Path) -> tuple[str, str]:
    """Текстовая сводка скана для промпта planner'а и для вывода пользователю."""
    scan = scan_repo(scan_root)
    summary_lines = [
        f"Стек: {', '.join(scan.stacks) or 'не определён'}",
        f"Проверки (кандидаты в acceptance): {scan.test_commands or 'не найдены'}",
        f"CI-конфиги: {scan.ci_files or 'нет'}",
        "Верхний уровень репозитория: "
        + ", ".join(sorted(p.name + ("/" if p.is_dir() else "") for p in scan_root.iterdir())[:40]),
    ]
    return "\n".join(summary_lines), render_scan(scan)


def _planner_prompt(intent: str, scan_summary: str) -> list[dict[str, str]]:
    return [
        {"role": "user", "content": (
            "Пользователь описал задачу своими словами. Собери черновик очереди "
            "задач (tasks.yaml по контракту): декомпозируй на 1–5 задач, каждой — "
            "scope_paths, depends_on, acceptance (используй НАЙДЕННЫЕ проверки "
            "репозитория, не выдумывай новые), budget не заполняй (подставит wizard).\n\n"
            f"## Что хочет пользователь\n{intent}\n\n"
            f"## Скан репозитория\n{scan_summary}"
        )},
    ]


def _test_scope_warnings(tasks: list[dict[str, Any]]) -> list[str]:
    """Предупреждения: scope задачи покрывает тесты — coder сможет править гейт."""
    warnings: list[str] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        tid = str(task.get("id", "?"))
        for pattern in task.get("scope_paths") or []:
            segments = {seg.lower() for seg in str(pattern).replace("\\", "/").split("/")}
            if segments & set(_TEST_MARKERS):
                warnings.append(
                    f"⚠ {tid}: scope {pattern!r} включает тесты — coder сможет подправить "
                    "проверку под себя. Вынесите тесты из scope (заморозка acceptance)."
                )
    return warnings


def _normalize(
    raw: Any, profile: Profile, scan_commands: list[str]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Заполнить пробелы черновика: капы из профиля, acceptance из скана, гейты."""
    warnings: list[str] = []
    if not isinstance(raw, dict) or not isinstance(raw.get("tasks"), list):
        return [], ["⚠ Ответ planner'а — не tasks.yaml; файл сохранён как есть, правьте вручную."]
    tasks: list[dict[str, Any]] = []
    for item in raw["tasks"]:
        if not isinstance(item, dict):
            continue
        task = dict(item)
        budget = dict(task.get("budget") or {})
        budget.setdefault("max_tokens", profile.task_max_tokens)
        budget.setdefault("max_cost_usd", round(profile.task_max_cost_usd, 2))
        task["budget"] = budget
        if not task.get("acceptance"):
            if scan_commands:
                task["acceptance"] = list(scan_commands)
                warnings.append(
                    f"⚠ {task.get('id', '?')}: planner не задал acceptance — подставлены "
                    "проверки из скана; проверьте, что они проверяют главное."
                )
            else:
                warnings.append(
                    f"⚠ {task.get('id', '?')}: нет acceptance — гейт №2 пуст. "
                    "Напишите проверку вручную, иначе задача непроверяема."
                )
        if profile.gate_every_task and not task.get("gate"):
            task["gate"] = "review"
        tasks.append(task)
    warnings.extend(_test_scope_warnings(tasks))
    return tasks, warnings


def _forecast(tasks: list[dict[str, Any]]) -> float:
    """Прогноз стоимости: сумма перезадачных капов (верхняя граница прогона)."""
    total = 0.0
    for task in tasks:
        budget = task.get("budget") or {}
        total += float(budget.get("max_cost_usd") or 0.0)
    return round(total, 2)


def run_wizard(cfg: ForgeConfig, client: LLMClient, target: Path, intent: str,
               profile_name: str = DEFAULT_PROFILE, out: Path | None = None,
               force: bool = False, check: bool = True) -> str:
    """Весь поток wizard; возвращает отчёт простым языком. Ничего не запускает."""
    root = target.resolve()
    if not root.is_dir():
        raise ValueError(f"Каталог {root} не существует")
    profile = get_profile(profile_name)
    out_path = (out or root / OUT_NAME).resolve()
    if out_path.exists() and not force:
        raise ValueError(f"{out_path} уже существует — перезапись: --force")

    lines: list[str] = [f"forge wizard — черновик настроек по промпту (профиль: {profile.name})", ""]

    scan_summary, scan_text = _scan_summary(root)
    lines.append(scan_text)
    if check:
        scan = scan_repo(root)
        if scan.test_commands:
            lines.append("")
            lines.append(render_baseline(run_baseline(root, scan.test_commands)))

    # planner-роль: промпт + скан → черновик YAML; вызов журналируется (FR-7).
    journal = Journal(cfg.runs_dir, new_run_id())
    journal.write_meta({
        "run_id": journal.run_id, "package": "wizard", "provider": cfg.provider_name,
        "mock": cfg.mock, "models": {role: rc.model for role, rc in cfg.roles.items()},
        "accepted": [],
    })
    result = client.chat(
        "planner",
        [{"role": "system", "content": load_prompt(cfg.prompts_dir, "system")
          + "\n\n" + load_prompt(cfg.prompts_dir, "planner")},
         *_planner_prompt(intent, scan_summary)],
    )
    log_model_call(journal, cfg, None, "plan", "planner", result)

    try:
        raw: Any = yaml.safe_load(result.content)
    except yaml.YAMLError:
        raw = None  # ответ planner'а — не YAML; сохраним как есть, пользователь поправит
    tasks, warnings = _normalize(raw, profile, scan_repo(root).test_commands)

    header = (
        f"# Черновик от wizard (профиль {profile.name}). Промпт: {intent!r}\n"
        "# Проверьте карточки задач и подтвердите запуск — это гейт №1.\n"
        "# Acceptance заморожен: тестовые файлы должны оставаться вне scope coder'а.\n"
    )
    if tasks:
        body = yaml.safe_dump({"package": "wizard-draft", "tasks": tasks},
                              allow_unicode=True, sort_keys=False)
    else:
        body = result.content  # не распарсилось — сохраняем как есть
    out_path.write_text(header + body, encoding="utf-8")

    # Валидация контракта: файл обязан грузиться load_tasks (DAG, id, scope).
    try:
        load_tasks(out_path)
        valid = True
    except (ValueError, yaml.YAMLError) as exc:
        valid = False
        warnings.append(f"⚠ Черновик не проходит контракт tasks.yaml: {exc}")

    lines += ["", f"Черновик: {out_path}", ""]
    for task in tasks:
        gate = f" · гейт {task['gate']}" if task.get("gate") else ""
        budget = task.get("budget") or {}
        cap = budget.get("max_cost_usd")
        cap_text = f"${float(cap):.2f}" if isinstance(cap, (int, float)) else "?"
        lines.append(
            f"  · {task.get('id')}: {task.get('title', '')}\n"
            f"    scope: {', '.join(str(p) for p in task.get('scope_paths') or [])}\n"
            f"    acceptance: {'; '.join(str(c) for c in task.get('acceptance') or [])}\n"
            f"    кап: {cap_text}{gate}"
        )
    lines.append("")
    if tasks:
        lines.append(f"Прогноз стоимости: не больше ~${_forecast(tasks):.2f} "
                     f"(сумма капов; факт обычно ниже).")
    lines.append("Статус черновика: " + ("✅ валиден" if valid else "❌ требует ручной правки"))
    lines.extend(warnings)
    lines += [
        "",
        "Дальше:",
        f"  1. Откройте {out_path.name} и проверьте задачи (гейт №1)",
        f"  2. Запуск: forge run --tasks {out_path.name} --target .",
        "  3. Наблюдение: forge status · forge ui · отчёт: forge report --plain",
    ]
    return "\n".join(lines)
