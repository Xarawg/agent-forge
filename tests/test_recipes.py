"""Рецепты: forge wizard --recipe — черновик без вызова LLM (onboarding ob4)."""

from pathlib import Path

import pytest

from forge.models import load_tasks
from forge.wizard import OUT_NAME, list_recipes, run_recipe


def test_recipes_gallery_present(cfg) -> None:
    recipes = list_recipes(cfg.root / "config" / "recipes")
    assert {"test-coverage", "feature", "docs-sync"} <= set(recipes)


def test_recipe_test_coverage_defaults(cfg, target: Path) -> None:
    out = run_recipe(cfg, target, "test-coverage", ask=None)  # дефолтные ответы
    package = load_tasks(target / OUT_NAME)
    task = package.tasks[0]
    assert task.scope_paths == ["tests/**"]
    assert task.acceptance == ["python -m pytest -q"]
    assert task.gate == "review"  # careful-профиль по умолчанию
    assert "$0" in out  # без вызова модели


def test_recipe_feature_two_tasks_with_answers(cfg, target: Path) -> None:
    answers = iter(["авторизация по токену", "server/auth", "server/tests",
                    "python -m pytest server/tests -q"])
    run_recipe(cfg, target, "feature", ask=lambda _q: next(answers))
    package = load_tasks(target / OUT_NAME)
    impl, tests = package.tasks
    assert impl.scope_paths == ["server/auth/**"]
    assert "авторизация по токену" in impl.title
    assert tests.depends_on == ["recipe-feature-impl"]
    assert tests.acceptance == ["python -m pytest server/tests -q"]


def test_recipe_unknown_name_lists_available(cfg, target: Path) -> None:
    with pytest.raises(ValueError, match="test-coverage"):
        run_recipe(cfg, target, "no-such-recipe", ask=None)


def test_recipe_refuses_overwrite(cfg, target: Path) -> None:
    run_recipe(cfg, target, "docs-sync", ask=None)
    with pytest.raises(ValueError, match="--force"):
        run_recipe(cfg, target, "docs-sync", ask=None)


def test_all_recipes_render_valid_dags(cfg, target: Path, tmp_path: Path) -> None:
    """Каждый рецепт галереи обязан рендериться в валидный контракт."""
    for name in list_recipes(cfg.root / "config" / "recipes"):
        out = tmp_path / f"{name}.yaml"
        run_recipe(cfg, target, name, out=out, ask=None)
        package = load_tasks(out)  # DAG, kebab-id, scope — валидирует load_tasks
        assert package.tasks, f"рецепт {name} отрендерил пустую очередь"
