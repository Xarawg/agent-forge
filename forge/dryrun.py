"""`forge run --dry-run` — прогноз стоимости очереди ДО запуска (ревью §5.1).

Верхняя граница — сумма перезадачных капов. Если в runs/ есть история,
оценка уточняется медианой фактической стоимости завершённых задач:
прогноз = min(кап, медиана), итог «ожидаемо ~$X, максимум $Y».
Ничего не запускается — только чтение tasks.yaml и журналов.
"""

from __future__ import annotations

import json
from pathlib import Path
from statistics import median

from .models import Task, load_tasks

#: Оценка задачи без капа и без истории (соответствует дефолтному сценарию NFR-4).
FALLBACK_TASK_USD = 0.50


def _task_cap(task: Task) -> float:
    return float(task.budget.max_cost_usd) if task.budget.max_cost_usd is not None else FALLBACK_TASK_USD


def _historical_median(runs_dir: Path) -> float | None:
    """Медиана фактической стоимости done-задач по всем прошлым прогонам."""
    costs: list[float] = []
    for state_path in runs_dir.glob("run-*/tasks/*.json"):
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("state") == "done" and float(data.get("cost_usd") or 0.0) > 0:
            costs.append(float(data["cost_usd"]))
    return float(median(costs)) if costs else None


def dry_run_report(tasks_path: Path, runs_dir: Path, per_run_cap: float) -> str:
    """Таблица «задача → прогноз $» и итог; ничего не запускает."""
    package = load_tasks(tasks_path)
    median_cost = _historical_median(runs_dir)

    lines = [
        f"forge run --dry-run: прогноз очереди {tasks_path.name} ({len(package.tasks)} задач)",
        "",
        f"{'TASK':40} {'ОЖИДАЕМО':>10} {'МАКСИМУМ':>10}  GATE",
    ]
    total_est = 0.0
    total_cap = 0.0
    for task in package.tasks:
        cap = _task_cap(task)
        estimate = min(cap, median_cost) if median_cost is not None else cap
        total_est += estimate
        total_cap += cap
        lines.append(
            f"{task.id:40} ${estimate:>9.4f} ${cap:>9.2f}  {task.gate or ''}"
        )
    lines += [
        "",
        f"Итого: ожидаемо ~${total_est:.4f}, максимум ${total_cap:.2f} (сумма капов).",
        f"Per-run кап: ${per_run_cap:.2f} — "
        + ("прогон остановится раньше, чем очередь закончится."
           if per_run_cap < total_cap else "очередь целиком помещается в кап."),
    ]
    if median_cost is None:
        lines.append("История прогонов пуста — ожидание = капы. После первых прогонов "
                     "прогноз уточнится фактической стоимостью.")
    else:
        lines.append(f"Ожидание — по медиане прошлых done-задач (${median_cost:.4f}).")
    lines.append("Ничего не запущено. Старт: forge run --tasks "
                 f"{tasks_path.name} --target <репо>")
    return "\n".join(lines)
