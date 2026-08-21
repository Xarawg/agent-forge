"""forge wizard: промпт → черновик задач с капами профиля и прогнозом стоимости."""

from pathlib import Path

import pytest
import yaml

from forge.llm import MockClient
from forge.models import load_tasks
from forge.profiles import get_profile
from forge.wizard import OUT_NAME, _normalize, _test_scope_warnings, run_wizard


def test_wizard_writes_valid_draft(cfg, target: Path) -> None:
    out = run_wizard(cfg, MockClient(cfg), target, "добавь hello-world endpoint", check=False)
    draft_path = target / OUT_NAME
    assert draft_path.exists()
    package = load_tasks(draft_path)  # контракт tasks.yaml: DAG, id, scope
    task = package.tasks[0]
    profile = get_profile("careful")
    assert task.budget.max_tokens == profile.task_max_tokens  # кап подставлен из профиля
    assert task.budget.max_cost_usd == pytest.approx(profile.task_max_cost_usd)
    assert task.gate == "review"  # careful: гейт после каждой задачи
    assert "Прогноз стоимости" in out and "валиден" in out


def test_wizard_refuses_overwrite_without_force(cfg, target: Path) -> None:
    run_wizard(cfg, MockClient(cfg), target, "первая задача", check=False)
    with pytest.raises(ValueError, match="--force"):
        run_wizard(cfg, MockClient(cfg), target, "вторая задача", check=False)
    run_wizard(cfg, MockClient(cfg), target, "вторая задача", force=True, check=False)


def test_wizard_normal_profile_no_gate_per_task(cfg, target: Path) -> None:
    run_wizard(cfg, MockClient(cfg), target, "задача", profile_name="normal", check=False)
    package = load_tasks(target / OUT_NAME)
    assert package.tasks[0].gate is None


def test_wizard_logs_planner_call(cfg, target: Path) -> None:
    run_wizard(cfg, MockClient(cfg), target, "задача", check=False)
    runs = [p for p in cfg.runs_dir.iterdir() if p.is_dir()]
    assert runs, "вызов planner'а должен журналироваться"
    events = [line for line in (runs[0] / "events.jsonl").read_text(encoding="utf-8").splitlines()
              if '"plan"' in line]
    assert events


def test_normalize_fills_acceptance_from_scan() -> None:
    raw = {"tasks": [{"id": "t1", "title": "x", "spec_ref": "s", "scope_paths": ["src/**"]}]}
    tasks, warnings = _normalize(raw, get_profile("normal"), ["python -m pytest -q"])
    assert tasks[0]["acceptance"] == ["python -m pytest -q"]
    assert any("acceptance" in w for w in warnings)


def test_normalize_warns_on_empty_acceptance_without_scan() -> None:
    raw = {"tasks": [{"id": "t1", "title": "x", "spec_ref": "s", "scope_paths": ["src/**"]}]}
    tasks, warnings = _normalize(raw, get_profile("normal"), [])
    assert not tasks[0].get("acceptance")
    assert any("гейт №2 пуст" in w for w in warnings)


def test_test_scope_warnings() -> None:
    tasks = [{"id": "t1", "scope_paths": ["src/**", "tests/**"]}]
    warnings = _test_scope_warnings(tasks)
    assert warnings and "заморозка acceptance" in warnings[0]
    assert _test_scope_warnings([{"id": "t2", "scope_paths": ["src/**"]}]) == []


def test_wizard_survives_non_yaml_planner_reply(cfg, target: Path, monkeypatch) -> None:
    monkeypatch.setenv("FORGE_MOCK_SCENARIO", "default")
    client = MockClient(cfg)
    original = client.chat

    def broken_chat(role, messages, tools=None):  # noqa: ANN001
        result = original(role, messages, tools)
        if role == "planner":
            result.content = "это не yaml вообще: [[["
        return result

    client.chat = broken_chat  # type: ignore[method-assign]
    out = run_wizard(cfg, client, target, "задача", check=False)
    assert "не tasks.yaml" in out or "не проходит контракт" in out
    assert (target / OUT_NAME).exists()


def test_wizard_draft_parses_with_yaml_directly(cfg, target: Path) -> None:
    run_wizard(cfg, MockClient(cfg), target, "задача", check=False)
    raw = yaml.safe_load((target / OUT_NAME).read_text(encoding="utf-8"))
    assert raw["package"] == "wizard-draft" and raw["tasks"]
