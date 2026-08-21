"""forge lint: контракт очереди + заморозка acceptance (onboarding ob5)."""

from pathlib import Path

from forge.lint import has_existing_tests, lint_tasks, render_lint

GOOD = """\
package: ok
tasks:
  - id: t1-code
    title: "Код"
    spec_ref: "s"
    scope_paths: ["src/**"]
    acceptance: ["python -c \\"import src\\""]
    budget: {max_cost_usd: 0.5}
"""

TESTS_IN_SCOPE = """\
package: bad
tasks:
  - id: t1-code
    title: "Код"
    spec_ref: "s"
    scope_paths: ["src/**", "tests/**"]
    acceptance: ["python -m pytest -q"]
    budget: {max_cost_usd: 0.5}
"""

NO_ACCEPTANCE = """\
package: weak
tasks:
  - id: t1-code
    title: "Код"
    spec_ref: "s"
    scope_paths: ["src/**"]
"""


def test_lint_good_queue(tmp_path: Path) -> None:
    path = tmp_path / "tasks.yaml"
    path.write_text(GOOD, encoding="utf-8")
    errors, warnings = lint_tasks(path)
    assert errors == [] and warnings == []
    assert "✅" in render_lint(path, errors, warnings)


def test_lint_catches_tests_in_scope(tmp_path: Path) -> None:
    path = tmp_path / "tasks.yaml"
    path.write_text(TESTS_IN_SCOPE, encoding="utf-8")
    errors, warnings = lint_tasks(path)
    assert errors == []
    assert any("заморозка acceptance" in w for w in warnings)


def test_lint_warns_on_missing_acceptance_and_budget(tmp_path: Path) -> None:
    path = tmp_path / "tasks.yaml"
    path.write_text(NO_ACCEPTANCE, encoding="utf-8")
    errors, warnings = lint_tasks(path)
    assert errors == []
    assert any("гейт №2 пуст" in w for w in warnings)
    assert any("бюджет" in w for w in warnings)


def test_lint_reports_contract_error(tmp_path: Path) -> None:
    path = tmp_path / "tasks.yaml"
    path.write_text("package: x\ntasks:\n  - id: BAD_ID\n    scope_paths: ['a/**']\n",
                    encoding="utf-8")
    errors, _warnings = lint_tasks(path)
    assert errors and "контракт" in errors[0]
    assert "❌" in render_lint(path, errors, [])


ORDER_BAD = """\
package: bad-order
tasks:
  - id: t1-code
    title: "Код"
    spec_ref: "s"
    scope_paths: ["src/**"]
    acceptance: ["python -m pytest -q"]
    budget: {max_cost_usd: 0.5}
  - id: t2-tests
    title: "Тесты"
    spec_ref: "s"
    scope_paths: ["tests/**"]
    depends_on: [t1-code]
    acceptance: ["python -m pytest -q"]
    budget: {max_cost_usd: 0.5}
"""

ORDER_GOOD = """\
package: good-order
tasks:
  - id: t1-tests
    title: "Тесты первым делом"
    spec_ref: "s"
    scope_paths: ["tests/**"]
    acceptance: ["python -m pytest -q"]
    budget: {max_cost_usd: 0.5}
  - id: t2-code
    title: "Код"
    spec_ref: "s"
    scope_paths: ["src/**"]
    depends_on: [t1-tests]
    acceptance: ["python -m pytest -q"]
    budget: {max_cost_usd: 0.5}
"""


def test_lint_warns_on_test_acceptance_before_tests_exist(tmp_path: Path) -> None:
    """Живой кейс 2026-08-21: pytest-acceptance раньше задачи с тестами → exit 5 → DISPUTE."""
    path = tmp_path / "tasks.yaml"
    path.write_text(ORDER_BAD, encoding="utf-8")
    errors, warnings = lint_tasks(path)
    assert errors == []
    order_warnings = [w for w in warnings if "позиции DAG" in w or "гарантированно упад" in w
                      or "запускает тесты" in w]
    assert any(w.startswith("⚠ t1-code") for w in order_warnings)
    assert not any(w.startswith("⚠ t2-tests") for w in order_warnings)


def test_lint_no_order_warning_when_tests_task_first(tmp_path: Path) -> None:
    path = tmp_path / "tasks.yaml"
    path.write_text(ORDER_GOOD, encoding="utf-8")
    errors, warnings = lint_tasks(path)
    assert errors == []
    assert not any("запускает тесты" in w for w in warnings)


def test_has_existing_tests(tmp_path: Path) -> None:
    assert not has_existing_tests(tmp_path)
    (tmp_path / "tests").mkdir()
    assert has_existing_tests(tmp_path)
    (tmp_path / "tests").rmdir()
    src = tmp_path / "pkg"
    src.mkdir()
    (src / "test_api.py").write_text("", encoding="utf-8")
    assert has_existing_tests(tmp_path)
