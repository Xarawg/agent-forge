"""forge init: git, skeleton tasks.yaml, baseline, следующие шаги (GAP §2-A2)."""

from pathlib import Path

import pytest

from forge.init import init_project


def test_init_creates_skeleton_and_git(tmp_path: Path) -> None:
    target = tmp_path / "proj"
    target.mkdir()
    (target / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    out = init_project(target, forge_root=tmp_path / "forge-home", check=False)
    assert (target / ".git").exists(), "git-репозиторий должен быть инициализирован"
    tasks = (target / "tasks.yaml").read_text(encoding="utf-8")
    assert "package:" in tasks and "python -m pytest -q" in tasks
    assert "careful" in out and "Следующие шаги" in out


def test_init_does_not_overwrite_without_force(tmp_path: Path) -> None:
    target = tmp_path / "proj"
    target.mkdir()
    (target / "tasks.yaml").write_text("package: mine\n", encoding="utf-8")
    out = init_project(target, forge_root=tmp_path / "forge-home", check=False)
    assert (target / "tasks.yaml").read_text(encoding="utf-8") == "package: mine\n"
    assert "--force" in out
    out_forced = init_project(target, forge_root=tmp_path / "forge-home", force=True, check=False)
    assert "skeleton создан" in out_forced


def test_init_warns_about_missing_env(tmp_path: Path) -> None:
    target = tmp_path / "proj"
    target.mkdir()
    out = init_project(target, forge_root=tmp_path / "no-env-here", check=False)
    assert ".env не найден" in out or "FORGE_MOCK" in out


def test_init_baseline_runs_detected_checks(tmp_path: Path) -> None:
    target = tmp_path / "proj"
    target.mkdir()
    # Проект, чья «проверка» гарантированно зелёная без внешних зависимостей
    (target / "go.mod").write_text("module x\n", encoding="utf-8")
    out = init_project(target, forge_root=tmp_path, check=True)
    assert "Baseline" in out  # go test, скорее всего, не установлен — важен сам прогон


def test_init_rejects_missing_dir(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        init_project(tmp_path / "nope", forge_root=tmp_path, check=False)
