"""Сканер стека и baseline (forge/detect.py): маркерные файлы, CI-команды."""

from pathlib import Path

from forge.detect import render_baseline, render_scan, scan_repo


def test_detect_python_repo(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    scan = scan_repo(tmp_path)
    assert "python" in scan.stacks
    assert "python -m pytest -q" in scan.test_commands


def test_detect_node_repo(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"scripts": {"test": "node --test", "build": "tsc"}}', encoding="utf-8"
    )
    scan = scan_repo(tmp_path)
    assert "node" in scan.stacks
    assert "npm test" in scan.test_commands


def test_detect_node_without_test_script(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"scripts": {"build": "tsc"}}', encoding="utf-8")
    scan = scan_repo(tmp_path)
    assert "npm run build" in scan.test_commands
    assert any("scripts.test" in n for n in scan.notes)


def test_detect_dotnet_and_git(tmp_path: Path) -> None:
    (tmp_path / "app.sln").write_text("", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    scan = scan_repo(tmp_path)
    assert "dotnet" in scan.stacks
    assert "dotnet test" in scan.test_commands
    assert scan.has_git


def test_detect_ci_commands(tmp_path: Path) -> None:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        "jobs:\n  test:\n    steps:\n"
        "      - run: pip install -e .\n"
        "      - run: python -m pytest -q\n",
        encoding="utf-8",
    )
    scan = scan_repo(tmp_path)
    assert ".github/workflows/ci.yml" in scan.ci_files
    assert "python -m pytest -q" in scan.test_commands
    # pip install из CI не должен становиться acceptance
    assert not any("pip install" in c for c in scan.test_commands)


def test_detect_empty_repo(tmp_path: Path) -> None:
    scan = scan_repo(tmp_path)
    assert scan.stacks == []
    assert any("стек не определён" in n for n in scan.notes)


def test_render_baseline_red_stops() -> None:
    from forge.detect import BaselineResult

    text = render_baseline([BaselineResult("pytest", 1, "boom")])
    assert "❌" in text and "Сначала почините проект" in text
    ok = render_baseline([BaselineResult("pytest", 0, "ok")])
    assert "✅" in ok and "можно запускать" in ok


def test_render_scan_lists_commands(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text("module x\n", encoding="utf-8")
    text = render_scan(scan_repo(tmp_path))
    assert "go" in text and "go test ./..." in text
