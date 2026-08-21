"""`forge wizard` — промпт человеческим языком → готовый черновик настроек.

Поток: скан репо (detect) → baseline → planner-роль генерирует черновик задач →
нормализация (капы из профиля, найденные проверки в acceptance, гейты) →
прогноз стоимости → tasks.wizard.yaml. Ничего не запускается: черновик
подтверждает человек — это и есть гейт №1 (онбординг-решение 2026-08-21).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from .agents import log_model_call
from .config import ForgeConfig
from .detect import render_baseline, render_scan, run_baseline, scan_repo
from .journal import Journal, new_run_id
from .lint import test_scope_warnings
from .llm import LLMClient
from .models import load_tasks
from .profiles import DEFAULT_PROFILE, Profile, get_profile
from .prompts import load_prompt

OUT_NAME = "tasks.wizard.yaml"


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
    warnings.extend(test_scope_warnings(tasks))
    return tasks, warnings


def _forecast(tasks: list[dict[str, Any]]) -> float:
    """Прогноз стоимости: сумма перезадачных капов (верхняя граница прогона)."""
    total = 0.0
    for task in tasks:
        budget = task.get("budget") or {}
        total += float(budget.get("max_cost_usd") or 0.0)
    return round(total, 2)


MAX_INTERVIEW_ROUNDS = 2  # защита от бесконечных уточнений: дальше — черновик как есть


def _parse_questions(content: str) -> list[str]:
    """QUESTIONS-протокол planner'а (prompts/10): вопросы вместо черновика."""
    if not content.strip().startswith("QUESTIONS"):
        return []
    questions: list[str] = []
    for line in content.splitlines()[1:]:
        line = line.strip()
        if line and (line[0].isdigit() or line.startswith("-")):
            questions.append(line.lstrip("0123456789.-) ").strip())
    return questions


def _interview(
    cfg: ForgeConfig, client: LLMClient, journal: Journal, system: str,
    intent: str, scan_summary: str,
    ask: Callable[[str], str] | None,
    lines: list[str],
) -> str:
    """Цикл «planner ↔ вопросы пользователю» до YAML-черновика.

    ask=None (неинтерактивный режим): вопросы выводятся в отчёт, черновик
    запрашивается без ответов — с явным предупреждением.
    """
    messages = [
        {"role": "system", "content": system},
        *_planner_prompt(intent, scan_summary),
    ]
    for round_no in range(MAX_INTERVIEW_ROUNDS + 1):
        result = client.chat("planner", messages)
        log_model_call(journal, cfg, None, "plan", "planner", result)
        questions = _parse_questions(result.content)
        if not questions:
            return result.content
        if round_no >= MAX_INTERVIEW_ROUNDS or ask is None:
            lines.append("")
            lines.append("Planner запросил уточнения" +
                         (" (неинтерактивный режим — черновик без ответов):" if ask is None
                          else " (лимит раундов):"))
            lines.extend(f"  ? {q}" for q in questions)
            messages.append({"role": "assistant", "content": result.content})
            messages.append({"role": "user", "content": (
                "## Ответы пользователя\n(не получены — собери черновик "
                "с наиболее безопасными допущениями и пометь их в title)"
            )})
            continue
        answers: list[str] = []
        lines.append("")
        lines.append("Planner уточняет перед черновиком:")
        for question in questions:
            answer = ask(question)
            lines.append(f"  ? {question} → {answer}")
            answers.append(f"{question} — {answer}")
        messages.append({"role": "assistant", "content": result.content})
        messages.append({"role": "user", "content":
                         "## Ответы пользователя\n" + "\n".join(answers)})
    return result.content  # недостижимо: цикл возвращает на не-QUESTIONS ответе


def run_wizard(cfg: ForgeConfig, client: LLMClient, target: Path, intent: str,
               profile_name: str = DEFAULT_PROFILE, out: Path | None = None,
               force: bool = False, check: bool = True,
               ask: Callable[[str], str] | None = input) -> str:
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

    # planner-роль: промпт + скан → интервью (QUESTIONS) → черновик YAML (FR-7).
    journal = Journal(cfg.runs_dir, new_run_id())
    journal.write_meta({
        "run_id": journal.run_id, "package": "wizard", "provider": cfg.provider_name,
        "mock": cfg.mock, "models": {role: rc.model for role, rc in cfg.roles.items()},
        "accepted": [],
    })
    system = (load_prompt(cfg.prompts_dir, "system")
              + "\n\n" + load_prompt(cfg.prompts_dir, "planner"))
    draft = _interview(cfg, client, journal, system, intent, scan_summary, ask, lines)

    try:
        raw: Any = yaml.safe_load(draft)
    except yaml.YAMLError:
        raw = None  # ответ planner'а — не YAML; сохраним как есть, пользователь поправит
    tasks, warnings = _normalize(raw, profile, scan_repo(root).test_commands)

    header = (
        f"# Черновик от wizard (профиль {profile.name}). Промпт: {intent!r}\n"
        "# Проверьте карточки задач и подтвердите запуск — это гейт №1.\n"
        "# Acceptance заморожен: тестовые файлы должны оставаться вне scope coder'а.\n"
    )
    return _write_and_report(out_path, tasks, warnings, draft, header, lines)


def _write_and_report(
    out_path: Path, tasks: list[dict[str, Any]], warnings: list[str],
    raw_body: str, header: str, lines: list[str]
) -> str:
    """Запись черновика + валидация контракта + отчёт (общий хвост wizard/recipe)."""
    if tasks:
        body = yaml.safe_dump({"package": "wizard-draft", "tasks": tasks},
                              allow_unicode=True, sort_keys=False)
    else:
        body = raw_body  # не распарсилось — сохраняем как есть
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


def _render_template(value: Any, answers: dict[str, str]) -> Any:
    """Рекурсивная подстановка {ключ} в строках рецепта (без str.format — YAML
    может содержать фигурные скобки в командах)."""
    if isinstance(value, str):
        for key, answer in answers.items():
            value = value.replace("{" + key + "}", answer)
        return value
    if isinstance(value, list):
        return [_render_template(v, answers) for v in value]
    if isinstance(value, dict):
        return {k: _render_template(v, answers) for k, v in value.items()}
    return value


def list_recipes(recipes_dir: Path) -> list[str]:
    """Доступные рецепты (имя файла без .yaml)."""
    return sorted(p.stem for p in recipes_dir.glob("*.yaml"))


def run_recipe(cfg: ForgeConfig, target: Path, recipe_name: str,
               profile_name: str = DEFAULT_PROFILE, out: Path | None = None,
               force: bool = False,
               ask: Callable[[str], str] | None = input) -> str:
    """Рецепт → черновик задач без вызова LLM ($0, детерминированно)."""
    root = target.resolve()
    if not root.is_dir():
        raise ValueError(f"Каталог {root} не существует")
    recipes_dir = cfg.root / "config" / "recipes"
    recipe_path = recipes_dir / f"{recipe_name}.yaml"
    if not recipe_path.exists():
        raise ValueError(
            f"Рецепт {recipe_name!r} не найден. Доступны: {', '.join(list_recipes(recipes_dir))}"
        )
    profile = get_profile(profile_name)
    out_path = (out or root / OUT_NAME).resolve()
    if out_path.exists() and not force:
        raise ValueError(f"{out_path} уже существует — перезапись: --force")

    recipe: Any = yaml.safe_load(recipe_path.read_text(encoding="utf-8"))
    if not isinstance(recipe, dict) or not isinstance(recipe.get("tasks"), list):
        raise ValueError(f"{recipe_path}: ожидается рецепт с ключом tasks: [...]")

    lines: list[str] = [
        f"forge wizard --recipe {recipe_name}: {recipe.get('title', '')} "
        f"(профиль: {profile.name}, без вызова модели — $0)",
        "",
    ]
    answers: dict[str, str] = {}
    for question in recipe.get("questions") or []:
        key = str(question["key"])
        default = str(question.get("default", ""))
        if ask is not None:
            answer = ask(f"{question['ask']} [{default}]").strip() or default
            lines.append(f"  ? {question['ask']} → {answer}")
        else:
            answer = default
            lines.append(f"  ? {question['ask']} → {answer} (дефолт)")
        answers[key] = answer

    rendered = _render_template(recipe["tasks"], answers)
    tasks, warnings = _normalize({"tasks": rendered}, profile, scan_repo(root).test_commands)
    for question in recipe.get("questions") or []:
        if not answers.get(str(question["key"])):
            warnings.append(
                f"⚠ Вопрос «{question['ask']}» остался без ответа — "
                "проверьте title/scope в черновике."
            )
    lines.append("")
    header = (
        f"# Черновик из рецепта {recipe_name} (профиль {profile.name}).\n"
        "# Проверьте задачи и подтвердите запуск — это гейт №1.\n"
    )
    return _write_and_report(out_path, tasks, warnings, "", header, lines)
