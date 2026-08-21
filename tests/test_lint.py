"""forge lint: контракт очереди + заморозка acceptance (onboarding ob5)."""

from pathlib import Path

from forge.lint import lint_tasks, render_lint

GOOD = """\
package: ok
tasks:
  - id: t1-code
    title: "Код"
    spec_ref: "s"
    scope_paths: ["src/**"]
    acceptance: ["python -m pytest -q"]
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
