"""forge wizard: промпт → черновик задач с капами профиля и прогнозом стоимости."""

from pathlib import Path

import pytest
import yaml

from forge.lint import test_scope_warnings as scope_warnings
from forge.llm import MockClient
from forge.models import load_tasks
from forge.profiles import get_profile
from forge.wizard import OUT_NAME, _normalize, run_wizard


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
    tasks, warnings = _normalize(raw, get_profile("normal"), ["python -m pytest -q"],
                                 existing_tests=True)
    assert tasks[0]["acceptance"] == ["python -m pytest -q"]
    assert any("acceptance" in w for w in warnings)


def test_normalize_strips_test_acceptance_before_tests_exist() -> None:
    """Acceptance обязан проходить на позиции задачи в DAG: pytest до появления
    тестов гарантированно падает (exit 5) — wizard убирает такую проверку."""
    raw = {"tasks": [
        {"id": "t1-code", "title": "x", "spec_ref": "s", "scope_paths": ["src/**"],
         "acceptance": ["python -m pytest -q", "python -c \"import src\""]},
        {"id": "t2-tests", "title": "y", "spec_ref": "s", "scope_paths": ["tests/**"],
         "depends_on": ["t1-code"], "acceptance": ["python -m pytest -q"]},
    ]}
    tasks, warnings = _normalize(raw, get_profile("normal"), [], existing_tests=False)
    by_id = {t["id"]: t for t in tasks}
    # у ранней задачи тестовая команда убрана, не-тестовая осталась
    assert by_id["t1-code"]["acceptance"] == ["python -c \"import src\""]
    # задача, пишущая тесты, и все после неё сохраняют pytest
    assert by_id["t2-tests"]["acceptance"] == ["python -m pytest -q"]
    assert any("убран" in w and "t1-code" in w for w in warnings)


def test_normalize_keeps_test_acceptance_when_repo_has_tests() -> None:
    raw = {"tasks": [{"id": "t1", "title": "x", "spec_ref": "s", "scope_paths": ["src/**"],
                      "acceptance": ["python -m pytest -q"]}]}
    tasks, warnings = _normalize(raw, get_profile("normal"), [], existing_tests=True)
    assert tasks[0]["acceptance"] == ["python -m pytest -q"]
    assert not any("убран" in w for w in warnings)


def test_normalize_warns_on_empty_acceptance_without_scan() -> None:
    raw = {"tasks": [{"id": "t1", "title": "x", "spec_ref": "s", "scope_paths": ["src/**"]}]}
    tasks, warnings = _normalize(raw, get_profile("normal"), [])
    assert not tasks[0].get("acceptance")
    assert any("гейт №2 пуст" in w for w in warnings)


def test_test_scope_warnings() -> None:
    tasks = [{"id": "t1", "scope_paths": ["src/**", "tests/**"]}]
    warnings = scope_warnings(tasks)
    assert warnings and "заморозка acceptance" in warnings[0]
    assert scope_warnings([{"id": "t2", "scope_paths": ["src/**"]}]) == []


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


# --- интервью: QUESTIONS-протокол planner'а (onboarding ob2) ------------------


def test_wizard_interview_asks_and_continues(cfg, target: Path, monkeypatch) -> None:
    monkeypatch.setenv("FORGE_MOCK_SCENARIO", "ambiguous")
    asked: list[str] = []
    out = run_wizard(cfg, MockClient(cfg), target, "сделай что-нибудь",
                     check=False, ask=lambda q: asked.append(q) or "модуль auth")
    assert len(asked) == 2  # mock-planner спросил два вопроса
    assert "Planner уточняет" in out
    package = load_tasks(target / OUT_NAME)
    assert package.tasks  # после ответов черновик собран


def test_wizard_interview_noninteractive_warns(cfg, target: Path, monkeypatch) -> None:
    monkeypatch.setenv("FORGE_MOCK_SCENARIO", "ambiguous")
    out = run_wizard(cfg, MockClient(cfg), target, "сделай что-нибудь",
                     check=False, ask=None)
    assert "неинтерактивный режим" in out
    assert (target / OUT_NAME).exists()


# --- устойчивость к реальному выводу модели (найдено живым прогоном DeepSeek) ---


def test_strip_fences() -> None:
    from forge.wizard import _strip_fences

    assert _strip_fences("```yaml\npackage: x\n```") == "package: x"
    assert _strip_fences("package: x") == "package: x"
    assert _strip_fences("```\npackage: x\n```\n") == "package: x"


def test_wizard_repairs_fenced_yaml(cfg, target: Path) -> None:
    """Модель вернула YAML в markdown-ограждении — wizard должен справиться сам."""
    client = MockClient(cfg)
    original = client.chat

    def fenced_chat(role, messages, tools=None):  # noqa: ANN001
        result = original(role, messages, tools)
        if role == "planner":
            result.content = "```yaml\n" + result.content + "\n```"
        return result

    client.chat = fenced_chat  # type: ignore[method-assign]
    out = run_wizard(cfg, client, target, "задача", check=False)
    assert "валиден" in out
    assert load_tasks(target / OUT_NAME).tasks


def test_wizard_repairs_broken_yaml_via_retry(cfg, target: Path) -> None:
    """Первый ответ — битый YAML, второй (после repair-просьбы) — валидный."""
    client = MockClient(cfg)
    original = client.chat
    calls = {"n": 0}

    def broken_then_ok(role, messages, tools=None):  # noqa: ANN001
        result = original(role, messages, tools)
        if role == "planner":
            calls["n"] += 1
            if calls["n"] == 1:
                result.content = "tasks:\n  - id: x\n    title: двоеточие: без кавычек"
        return result

    client.chat = broken_then_ok  # type: ignore[method-assign]
    out = run_wizard(cfg, client, target, "задача", check=False)
    assert calls["n"] == 2, "wizard обязан попросить planner починить YAML"
    assert "валиден" in out


def test_wizard_accepts_bare_task_list(cfg, target: Path) -> None:
    """Модель вернула голый список задач без обёртки tasks: — wizard дополнит."""
    from forge.llm import MOCK_TASKS_DRAFT

    bare_list = yaml.safe_load(MOCK_TASKS_DRAFT)["tasks"]
    client = MockClient(cfg)
    original = client.chat

    def list_chat(role, messages, tools=None):  # noqa: ANN001
        result = original(role, messages, tools)
        if role == "planner":
            result.content = yaml.safe_dump(bare_list, allow_unicode=True)
        return result

    client.chat = list_chat  # type: ignore[method-assign]
    out = run_wizard(cfg, client, target, "задача", check=False)
    assert "валиден" in out
    assert load_tasks(target / OUT_NAME).tasks


def test_normalize_dir_scope_gets_glob() -> None:
    """scope `dir/` → `dir/**`, иначе coder не сможет писать (glob_to_regex)."""
    raw = {"tasks": [{"id": "t1", "title": "x", "spec_ref": "s",
                      "scope_paths": ["calc/", "calc.py", "tests/"],
                      "acceptance": ["python -m pytest -q"]}]}
    tasks, warnings = _normalize(raw, get_profile("normal"), [])
    assert tasks[0]["scope_paths"] == ["calc/**", "calc.py", "tests/**"]
    assert any("нормализован" in w for w in warnings)
