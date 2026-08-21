"""forge report --plain: итог прогона простым языком (render_plain)."""

from pathlib import Path

from forge.journal import Journal
from forge.models import TaskState
from forge.report import build_report, render_plain


def _run_with_states(runs_dir: Path, states: list[tuple[str, str, str]]) -> str:
    """Мини-прогон: run.json + tasks/<id>.json в заданных состояниях."""
    journal = Journal(runs_dir, "run-20990101-000000")
    journal.write_meta({"run_id": journal.run_id, "provider": "mock", "mock": True,
                        "models": {}, "accepted": []})
    for task_id, state, note in states:
        journal.set_task_state(TaskState(id=task_id, state=state, note=note))
    return journal.run_id


def test_plain_all_done(cfg) -> None:
    run_id = _run_with_states(cfg.runs_dir, [("t1-add-feature", "done", "")])
    text = render_plain(build_report(cfg.runs_dir, run_id))
    assert "Сделано: 1 из 1" in text
    assert "Все задачи выполнены" in text
    assert "resume" not in text


def test_plain_failed_and_blocked(cfg) -> None:
    run_id = _run_with_states(cfg.runs_dir, [
        ("t1-ok", "done", ""),
        ("t2-broken", "failed", "не починено за 3 repair-итераций"),
        ("t3-dispute", "blocked", "DISPUTE: противоречие в спеке"),
        ("t4-waiting", "queued", ""),
    ])
    text = render_plain(build_report(cfg.runs_dir, run_id))
    assert "Сделано: 1 из 4" in text
    assert "❌ Не получилось" in text and "t2-broken" in text
    assert "⏸ Остановлено" in text and "DISPUTE" in text
    assert "Ещё не выполнены: 1" in text
    assert f"forge resume {run_id}" in text
    assert "forge log t2-broken" in text


def test_plain_empty_run(cfg) -> None:
    run_id = _run_with_states(cfg.runs_dir, [])
    text = render_plain(build_report(cfg.runs_dir, run_id))
    assert "Задач в прогоне нет" in text


def test_history_snapshots_are_not_task_states(cfg) -> None:
    """Снапшоты диалога (AF-12) лежат в tasks/ рядом с состояниями — отчёт
    обязан их игнорировать (баг найден живым kill'ом прогона 2026-08-21)."""
    run_id = _run_with_states(cfg.runs_dir, [("t1-ok", "done", "")])
    history = cfg.runs_dir / run_id / "tasks" / "t1-ok.coder.history.json"
    history.write_text('{"steps": 3, "messages": []}', encoding="utf-8")
    report = build_report(cfg.runs_dir, run_id)  # не падает
    assert [t.task_id for t in report.tasks] == ["t1-ok"]

    from forge.ui import list_runs, run_detail

    runs = list_runs(cfg.runs_dir)
    assert runs[0]["states"] == {"done": 1}  # history не посчитан как задача
    detail = run_detail(cfg.runs_dir, run_id)
    assert detail is not None and len(detail["tasks"]) == 1
