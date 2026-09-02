"""CLI agent-forge (SPEC.md §FR-4): run / resume / status / log / report / accept / import."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .agents import log_model_call
from .config import ForgeConfig, forge_root, load_config
from .dryrun import dry_run_report
from .init import init_project
from .journal import Journal, new_run_id
from .lint import lint_tasks, render_lint
from .llm import make_client
from .map import scan_entities, write_map
from .prompts import load_prompt
from .report import build_report, latest_run_id, render_plain, render_report, render_status
from .runner import Runner
from .ui import serve
from .wizard import run_recipe, run_wizard


def _resolve_run_id(cfg: ForgeConfig, run_id: str | None) -> str:
    resolved = run_id or latest_run_id(cfg.runs_dir)
    if not resolved:
        raise SystemExit("Нет прогонов в runs/ — сначала `forge run`.")
    return resolved


def _make_runner(cfg: ForgeConfig, target: str | None) -> Runner:
    target_root = Path(target).resolve() if target else Path.cwd()
    return Runner(cfg, make_client(cfg), target_root)


def cmd_run(args: argparse.Namespace) -> int:
    cfg = load_config(provider_path=Path(args.provider) if args.provider else None)
    if args.dry_run:
        print(dry_run_report(Path(args.tasks), cfg.runs_dir, cfg.budgets.per_run_max_cost_usd))
        return 0
    runner = _make_runner(cfg, args.target)
    run_id = runner.run(
        Path(args.tasks),
        spec_path=Path(args.spec) if args.spec else None,
    )
    print(f"run_id: {run_id}")
    print(render_status(build_report(cfg.runs_dir, run_id)))
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    cfg = load_config(provider_path=Path(args.provider) if args.provider else None)
    journal = Journal(cfg.runs_dir, args.run_id)
    meta = journal.read_meta()
    if not meta:
        raise SystemExit(f"Прогон {args.run_id} не найден в {cfg.runs_dir}")
    runner = _make_runner(cfg, args.target or meta.get("target_root"))
    spec = meta.get("spec_path")
    runner.run(Path(str(meta["tasks_path"])), run_id=args.run_id,
               spec_path=Path(str(spec)) if spec else None)
    print(render_status(build_report(cfg.runs_dir, args.run_id)))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    cfg = load_config()
    run_id = _resolve_run_id(cfg, args.run_id)
    print(render_status(build_report(cfg.runs_dir, run_id)))
    return 0


def cmd_log(args: argparse.Namespace) -> int:
    cfg = load_config()
    run_id = _resolve_run_id(cfg, args.run_id)
    journal = Journal(cfg.runs_dir, run_id)
    events = journal.log_for_task(args.task_id)
    if not events:
        print(f"Нет событий по задаче {args.task_id} в прогоне {run_id}")
        return 1
    for e in events:
        line = f"[{e['ts']}] {e['phase']}"
        if e.get("role"):
            line += f"/{e['role']}"
        if e.get("command"):
            line += f" $ {e['command'][:120]}"
        if e.get("exit_code") is not None:
            line += f" (exit={e['exit_code']})"
        if e.get("tokens_in") or e.get("tokens_out"):
            line += f" tok={e['tokens_in']}+{e['tokens_out']} ${e.get('cost_usd', 0):.4f}"
        print(line)
        if e.get("note"):
            print(f"    {e['note'][:400]}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    cfg = load_config()
    run_id = _resolve_run_id(cfg, args.run_id)
    report = build_report(cfg.runs_dir, run_id)
    if args.plain:
        print(render_plain(report))
    else:
        print(render_report(report, cfg.budgets.per_run_max_cost_usd))
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    """Подготовка проекта: git, skeleton tasks.yaml, baseline. Без API-ключа."""
    target = Path(args.target).resolve() if args.target else Path.cwd()
    print(init_project(
        target, forge_root(),
        profile_name=args.profile, force=args.force, check=not args.no_check,
    ))
    return 0


def cmd_wizard(args: argparse.Namespace) -> int:
    """Промпт человеческим языком или рецепт → черновик задач/проверок/бюджетов."""
    cfg = load_config(provider_path=Path(args.provider) if args.provider else None)
    target = Path(args.target).resolve() if args.target else Path.cwd()
    ask = None if args.yes else input
    if args.recipe:
        print(run_recipe(
            cfg, target, args.recipe,
            profile_name=args.profile,
            out=Path(args.out) if args.out else None,
            force=args.force, ask=ask,
        ))
        return 0
    intent = args.prompt
    if args.prompt_file:
        intent = Path(args.prompt_file).read_text(encoding="utf-8")
    if not intent:
        raise SystemExit("wizard: нужен --prompt, --prompt-file или --recipe")
    print(run_wizard(
        cfg, make_client(cfg), target, intent,
        profile_name=args.profile,
        out=Path(args.out) if args.out else None,
        force=args.force, check=not args.no_check, ask=ask,
    ))
    return 0


def cmd_lint(args: argparse.Namespace) -> int:
    """Проверка очереди до запуска: контракт + заморозка acceptance (советчик)."""
    path = Path(args.tasks)
    errors, warnings = lint_tasks(path)
    print(render_lint(path, errors, warnings))
    return 1 if errors else 0


def cmd_map(args: argparse.Namespace) -> int:
    """Карта сущностей проекта: AST-скан → canon/entities.json + docs/ENTITIES.md."""
    target = Path(args.target).resolve() if args.target else Path.cwd()
    maps = scan_entities(target)
    canon, docs = write_map(target, maps)
    total = sum(len(fm.entities) for fm in maps.values())
    print(f"Карта сущностей: {len(maps)} файлов, {total} публичных сущностей")
    print(f"  машиночитаемая (агенты, read-only): {canon}")
    print(f"  человекочитаемая (onboarding):      {docs}")
    print("Перегенерируйте после каждого принятого прогона: forge map --target .")
    return 0


def cmd_accept(args: argparse.Namespace) -> int:
    cfg = load_config()
    run_id = _resolve_run_id(cfg, args.run_id)
    runner = _make_runner(cfg, args.target)
    runner.accept(run_id, args.task_id)
    print(f"Гейт №3 пройден: задача {args.task_id} принята в прогоне {run_id}. "
          f"Продолжить: `forge resume {run_id}`")
    return 0


def cmd_ui(args: argparse.Namespace) -> int:
    """Канбан прогонов: сервер только читает runs/, ключ API не требуется."""
    runs_dir = Path(args.runs_dir).resolve() if args.runs_dir else forge_root() / "runs"
    return serve(runs_dir, int(args.port))


def cmd_import(args: argparse.Namespace) -> int:
    """FR-1: черновик tasks.yaml через planner-роль; владелец правит до запуска."""
    cfg = load_config(provider_path=Path(args.provider) if args.provider else None)
    spec_path = Path(args.spec)
    spec_text = spec_path.read_text(encoding="utf-8")
    client = make_client(cfg)
    journal = Journal(cfg.runs_dir, new_run_id())
    journal.write_meta(
        {
            "run_id": journal.run_id,
            "package": f"import:{spec_path.name}",
            "provider": cfg.provider_name,
            "mock": cfg.mock,
            "models": {role: rc.model for role, rc in cfg.roles.items()},
            "accepted": [],
        }
    )
    result = client.chat(
        "planner",
        [
            {"role": "system", "content": load_prompt(cfg.prompts_dir, "system")
             + "\n\n" + load_prompt(cfg.prompts_dir, "planner")},
            {"role": "user", "content": f"Спецификация пакета:\n\n{spec_text}"},
        ],
    )
    log_model_call(journal, cfg, None, "plan", "planner", result)
    out = Path(args.out) if args.out else Path("tasks.draft.yaml")
    out.write_text(result.content, encoding="utf-8")
    print(f"Черновик задач записан в {out}. Проверьте и отредактируйте до `forge run` (гейт №1).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="forge", description="agent-forge: агентная кодогенерация по SPEC.md"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--provider", help="путь к пресету провайдера (config/providers/*.yaml)")
        p.add_argument("--target", help="корень целевого репозитория (по умолчанию — текущий каталог)")

    p_run = sub.add_parser("run", help="запустить прогон по tasks.yaml")
    p_run.add_argument("--tasks", required=True, help="путь к tasks.yaml")
    p_run.add_argument("--spec", help="путь к SPEC.md пакета (выдержка в промпт)")
    p_run.add_argument("--dry-run", action="store_true",
                       help="прогноз стоимости очереди без запуска (ничего не выполняется)")
    add_common(p_run)
    p_run.set_defaults(func=cmd_run)

    p_resume = sub.add_parser("resume", help="продолжить прогон после остановки")
    p_resume.add_argument("run_id")
    add_common(p_resume)
    p_resume.set_defaults(func=cmd_resume)

    p_status = sub.add_parser("status", help="таблица задач прогона")
    p_status.add_argument("run_id", nargs="?")
    p_status.set_defaults(func=cmd_status)

    p_log = sub.add_parser("log", help="журнал событий задачи")
    p_log.add_argument("task_id")
    p_log.add_argument("--run", dest="run_id")
    p_log.set_defaults(func=cmd_log)

    p_report = sub.add_parser("report", help="сводка: токены, стоимость, модели")
    p_report.add_argument("run_id", nargs="?")
    p_report.add_argument("--plain", action="store_true",
                          help="отчёт простым языком: сделано/не получилось/что дальше")
    p_report.set_defaults(func=cmd_report)

    p_init = sub.add_parser("init", help="подготовить проект: git, skeleton tasks.yaml, baseline")
    p_init.add_argument("--target", help="корень целевого проекта (по умолчанию — текущий каталог)")
    p_init.add_argument("--profile", default="careful",
                        choices=["careful", "normal", "fast"], help="профиль капов (по умолчанию careful)")
    p_init.add_argument("--force", action="store_true", help="перезаписать существующий tasks.yaml")
    p_init.add_argument("--no-check", action="store_true", help="не прогонять baseline-проверки")
    p_init.set_defaults(func=cmd_init)

    p_wizard = sub.add_parser("wizard", help="черновик настроек из промпта: задачи, проверки, бюджеты")
    p_wizard.add_argument("--prompt", help="что нужно сделать, своими словами")
    p_wizard.add_argument("--prompt-file", help="файл с описанием задачи вместо --prompt")
    p_wizard.add_argument("--recipe", help="готовый рецепт из config/recipes/ без вызова LLM ($0)")
    p_wizard.add_argument("--yes", action="store_true",
                          help="неинтерактивно: дефолтные ответы на вопросы, без interview")
    p_wizard.add_argument("--target", help="корень целевого проекта (по умолчанию — текущий каталог)")
    p_wizard.add_argument("--profile", default="careful",
                          choices=["careful", "normal", "fast"], help="профиль капов (по умолчанию careful)")
    p_wizard.add_argument("--out", help="куда записать черновик (по умолчанию <target>/tasks.wizard.yaml)")
    p_wizard.add_argument("--force", action="store_true", help="перезаписать существующий черновик")
    p_wizard.add_argument("--no-check", action="store_true", help="не прогонять baseline-проверки")
    p_wizard.add_argument("--provider")
    p_wizard.set_defaults(func=cmd_wizard)

    p_lint = sub.add_parser("lint", help="проверить очередь до запуска (контракт, заморозка acceptance)")
    p_lint.add_argument("tasks", help="путь к tasks.yaml")
    p_lint.set_defaults(func=cmd_lint)

    p_map = sub.add_parser(
        "map", help="карта сущностей проекта (AST → canon/entities.json + docs/ENTITIES.md)"
    )
    p_map.add_argument("--target", help="корень целевого проекта (по умолчанию — текущий каталог)")
    p_map.set_defaults(func=cmd_map)

    p_accept = sub.add_parser("accept", help="человеческий гейт №3: принять задачу (merge ветки)")
    p_accept.add_argument("task_id")
    p_accept.add_argument("--run", dest="run_id")
    p_accept.add_argument("--target", help="корень целевого репозитория")
    p_accept.set_defaults(func=cmd_accept)

    p_ui = sub.add_parser("ui", help="веб-канбан прогонов поверх runs/ (только чтение)")
    p_ui.add_argument("--port", type=int, default=8765, help="порт (по умолчанию 8765)")
    p_ui.add_argument("--runs-dir", help="каталог runs/ (по умолчанию <корень forge>/runs)")
    p_ui.set_defaults(func=cmd_ui)

    p_import = sub.add_parser("import", help="черновик tasks.yaml из SPEC.md через planner")
    p_import.add_argument("--spec", required=True)
    p_import.add_argument("--out", help="куда записать черновик (по умолчанию tasks.draft.yaml)")
    p_import.add_argument("--provider")
    p_import.set_defaults(func=cmd_import)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (RuntimeError, ValueError, FileNotFoundError) as exc:
        print(f"forge: ошибка: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())