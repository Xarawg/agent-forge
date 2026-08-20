"""Парсинг и валидация tasks.yaml (SPEC.md §FR-1, модель данных §5)."""

from pathlib import Path

import pytest
from conftest import FORGE_ROOT, write_tasks

from forge.models import load_tasks, topo_order


def test_example_tasks_parse() -> None:
    """config/tasks.example.yaml — валидный образец (SPEC.md §6.1)."""
    package = load_tasks(FORGE_ROOT / "config" / "tasks.example.yaml")
    assert package.name == "agent-forge-pilot"
    assert len(package.tasks) == 3
    pilot = package.tasks[0]
    assert pilot.id == "pilot-1-port-validate-canon"
    assert pilot.gate == "pilot-1"
    assert pilot.budget.max_cost_usd == 0.50


def test_topo_order_respects_dependencies(tmp_path: Path) -> None:
    package = load_tasks(write_tasks(tmp_path, """\
package: t
tasks:
  - {id: b-task, title: b, spec_ref: s, scope_paths: ["b/**"], depends_on: [a-task]}
  - {id: a-task, title: a, spec_ref: s, scope_paths: ["a/**"]}
"""))
    assert [t.id for t in topo_order(package.tasks)] == ["a-task", "b-task"]


def test_cycle_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="цикл"):
        load_tasks(write_tasks(tmp_path, """\
package: t
tasks:
  - {id: a-task, title: a, spec_ref: s, scope_paths: ["a/**"], depends_on: [b-task]}
  - {id: b-task, title: b, spec_ref: s, scope_paths: ["b/**"], depends_on: [a-task]}
"""))


def test_duplicate_id_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="дубль"):
        load_tasks(write_tasks(tmp_path, """\
package: t
tasks:
  - {id: a-task, title: a, spec_ref: s, scope_paths: ["a/**"]}
  - {id: a-task, title: a2, spec_ref: s, scope_paths: ["a/**"]}
"""))


def test_unknown_dependency_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="неизвестная зависимость"):
        load_tasks(write_tasks(tmp_path, """\
package: t
tasks:
  - {id: a-task, title: a, spec_ref: s, scope_paths: ["a/**"], depends_on: [ghost]}
"""))
