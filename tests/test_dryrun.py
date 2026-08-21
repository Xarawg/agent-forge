"""forge run --dry-run: прогноз стоимости очереди без запуска (onboarding ob1)."""

import json
from pathlib import Path

from forge.dryrun import dry_run_report

QUEUE = """\
package: forecast
tasks:
  - id: t1-small
    title: "Мелкая"
    spec_ref: "s"
    scope_paths: ["a/**"]
    budget: {max_cost_usd: 0.30}
  - id: t2-big
    title: "Крупная"
    spec_ref: "s"
    scope_paths: ["b/**"]
    budget: {max_cost_usd: 1.00}
    gate: wave-1
"""


def test_dry_run_caps_without_history(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks.yaml"
    tasks.write_text(QUEUE, encoding="utf-8")
    runs = tmp_path / "runs"
    runs.mkdir()
    text = dry_run_report(tasks, runs, per_run_cap=5.00)
    assert "t1-small" in text and "t2-big" in text
    assert "максимум $1.30" in text  # 0.30 + 1.00
    assert "История прогонов пуста" in text
    assert "помещается в кап" in text


def test_dry_run_uses_history_median(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks.yaml"
    tasks.write_text(QUEUE, encoding="utf-8")
    runs = tmp_path / "runs"
    state_dir = runs / "run-20260101-000000" / "tasks"
    state_dir.mkdir(parents=True)
    (runs / "run-20260101-000000" / "run.json").write_text("{}", encoding="utf-8")
    for i, cost in enumerate((0.10, 0.20, 0.30)):
        (state_dir / f"old-{i}.json").write_text(
            json.dumps({"id": f"old-{i}", "state": "done", "note": "",
                        "repair_iterations": 0, "tokens_in": 0, "tokens_out": 0,
                        "cost_usd": cost, "updated_at": ""}),
            encoding="utf-8",
        )
    text = dry_run_report(tasks, runs, per_run_cap=1.00)
    # Медиана $0.20: t1 = min(0.30, 0.20) = 0.20, t2 = min(1.00, 0.20) = 0.20
    assert "ожидаемо ~$0.4000" in text
    assert "медиане прошлых done-задач" in text
    assert "остановится раньше" in text  # кап $1.00 < сумма капов $1.30
