"""forge report / forge status: сводка по прогону (SPEC.md §FR-4, §FR-7)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .journal import Journal


@dataclass
class TaskReport:
    task_id: str
    state: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    repair_iterations: int = 0
    note: str = ""


@dataclass
class RunReport:
    run_id: str
    meta: dict[str, object]
    tasks: list[TaskReport] = field(default_factory=list)

    @property
    def total_cost(self) -> float:
        return sum(t.cost_usd for t in self.tasks)

    @property
    def total_tokens(self) -> int:
        return sum(t.tokens_in + t.tokens_out for t in self.tasks)


def latest_run_id(runs_dir: Path) -> str | None:
    """Последний прогон по имени каталога (run-YYYYmmdd-HHMMSS сортируются по времени)."""
    runs = sorted(p.name for p in runs_dir.glob("run-*") if p.is_dir())
    return runs[-1] if runs else None


def build_report(runs_dir: Path, run_id: str) -> RunReport:
    journal = Journal(runs_dir, run_id)
    report = RunReport(run_id=run_id, meta=journal.read_meta())
    for state_path in sorted((journal.run_dir / "tasks").glob("*.json")):
        if ".history" in state_path.name:
            continue  # снапшоты диалога (AF-12) — не состояния задач
        state = journal.task_state(state_path.stem)
        report.tasks.append(
            TaskReport(
                task_id=state.id,
                state=state.state,
                tokens_in=state.tokens_in,
                tokens_out=state.tokens_out,
                cost_usd=state.cost_usd,
                repair_iterations=state.repair_iterations,
                note=state.note,
            )
        )
    return report


def render_status(report: RunReport) -> str:
    """Таблица задач прогона для `forge status`."""
    lines = [
        f"run: {report.run_id}  provider: {report.meta.get('provider', '?')}"
        f"  mock: {report.meta.get('mock', '?')}",
        f"{'TASK':40} {'STATE':10} {'TOKENS':>10} {'COST':>8} {'REPAIR':>6}  NOTE",
    ]
    for t in report.tasks:
        lines.append(
            f"{t.task_id:40} {t.state:10} {t.tokens_in + t.tokens_out:>10} "
            f"${t.cost_usd:>7.4f} {t.repair_iterations:>6}  {t.note[:60]}"
        )
    if not report.tasks:
        lines.append("(задач пока нет)")
    return "\n".join(lines)


def render_report(report: RunReport, per_run_cap: float | None = None) -> str:
    """Полная сводка `forge report`: токены, стоимость, воспроизводимость."""
    lines = [
        render_status(report),
        "",
        f"Итого токенов: {report.total_tokens}",
        f"Итого стоимость: ${report.total_cost:.4f}",
    ]
    if per_run_cap is not None:
        verdict = "OK" if report.total_cost <= per_run_cap else "ПРЕВЫШЕНИЕ"
        lines.append(f"Per-run кап: ${per_run_cap:.2f} — {verdict}")
    models = report.meta.get("models")
    if isinstance(models, dict):
        lines.append("Модели: " + ", ".join(f"{k}={v}" for k, v in models.items()))
    lines.append(f"Версия промптов: {report.meta.get('prompts_version', '?')}")
    lines.append(f"Провайдер: {report.meta.get('provider', '?')}, mock: {report.meta.get('mock', '?')}")
    return "\n".join(lines)


def render_plain(report: RunReport) -> str:
    """Отчёт простым языком (`forge report --plain`): сделано / не получилось / что дальше.

    Для пользователей, которые не обязаны разбираться в токенах и состояниях:
    итоги прогона словами и конкретные следующие команды.
    """
    done = [t for t in report.tasks if t.state == "done"]
    failed = [t for t in report.tasks if t.state == "failed"]
    blocked = [t for t in report.tasks if t.state == "blocked"]
    pending = [t for t in report.tasks if t.state not in ("done", "failed", "blocked")]

    lines = [f"Прогон {report.run_id} — итог простым языком", ""]
    lines.append(
        f"Сделано: {len(done)} из {len(report.tasks)} задач · "
        f"потрачено ${report.total_cost:.4f} · починок (repair): "
        f"{sum(t.repair_iterations for t in report.tasks)}"
    )

    if done:
        lines.append("")
        lines.append("✅ Получилось:")
        lines.extend(f"  · {t.task_id}" for t in done)
    if failed:
        lines.append("")
        lines.append("❌ Не получилось (агент честно остановился, ничего не сломано молча):")
        for t in failed:
            reason = f" — {t.note[:80]}" if t.note else ""
            lines.append(f"  · {t.task_id}{reason}")
        lines.append(f"  Разобраться: forge log {failed[0].task_id} --run {report.run_id}")
    if blocked:
        lines.append("")
        lines.append("⏸ Остановлено и ждёт вашего решения:")
        for t in blocked:
            reason = f" — {t.note[:80]}" if t.note else ""
            lines.append(f"  · {t.task_id}{reason}")
        lines.append("  Обычно это DISPUTE (противоречие в спеке — уточните её) "
                     "или исчерпан бюджет (поднимите кап в tasks.yaml).")
    if pending:
        lines.append("")
        lines.append(f"⏳ Ещё не выполнены: {len(pending)} задач.")

    lines.append("")
    if not report.tasks:
        lines.append("Задач в прогоне нет — возможно, прогон только начался. Позже: forge status.")
    elif failed or blocked or pending:
        lines.append(f"Что дальше: разберите причины выше, затем продолжите — "
                     f"forge resume {report.run_id}")
        lines.append("Завершённые (done) задачи переигрываться не будут.")
    else:
        lines.append("Все задачи выполнены. Проверьте результат (git diff), "
                     "затем push — вручную, forge его не делает (NFR-5).")
    return "\n".join(lines)
