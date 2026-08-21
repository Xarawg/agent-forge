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
