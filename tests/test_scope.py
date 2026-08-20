"""Scope-контроль записи (SPEC.md §FR-2, §6.5, §7)."""

from pathlib import Path

import pytest

from forge.config import COMMAND_ALLOWLIST
from forge.tools import ScopeViolation, ToolBox, glob_to_regex, path_in_scope


def test_glob_patterns() -> None:
    assert path_in_scope("tools-ts/validate-canon/src/cli.ts", ["tools-ts/validate-canon/**"])
    assert path_in_scope("package.json", ["package.json"])
    assert path_in_scope("tsconfig.base.json", ["tsconfig*.json"])
    assert path_in_scope("scripts/ci/run.sh", ["scripts/**"])
    assert not path_in_scope("src/other.ts", ["tools-ts/**"])
    assert not path_in_scope("package.json", ["tools-ts/**"])


def test_glob_double_star_matches_nested() -> None:
    assert glob_to_regex("a/**").match("a/b/c/d.txt")
    assert glob_to_regex("a/**").match("a/b.txt")


def test_write_outside_scope_blocked(tmp_path: Path) -> None:
    box = ToolBox(tmp_path, ["allowed/**"], COMMAND_ALLOWLIST)
    with pytest.raises(ScopeViolation):
        box.write_file("forbidden/x.txt", "x")
    assert box.scope_violations == ["forbidden/x.txt"]
    assert not (tmp_path / "forbidden").exists()


def test_write_into_canon_always_blocked(tmp_path: Path) -> None:
    """canon/ read-only, даже если scope формально его покрывает (SPEC.md §7)."""
    box = ToolBox(tmp_path, ["canon/**", "**"], COMMAND_ALLOWLIST)
    with pytest.raises(ScopeViolation, match="canon"):
        box.write_file("canon/decisions.json", "{}")


def test_path_traversal_blocked(tmp_path: Path) -> None:
    box = ToolBox(tmp_path, ["**"], COMMAND_ALLOWLIST)
    with pytest.raises(ScopeViolation):
        box.write_file("../escape.txt", "x")


def test_write_inside_scope_ok(tmp_path: Path) -> None:
    box = ToolBox(tmp_path, ["out/**"], COMMAND_ALLOWLIST)
    assert box.write_file("out/a/b.txt", "hello").startswith("OK")
    assert (tmp_path / "out" / "a" / "b.txt").read_text() == "hello"
    assert box.written_files == ["out/a/b.txt"]


def test_run_command_whitelist(tmp_path: Path) -> None:
    box = ToolBox(tmp_path, ["**"], COMMAND_ALLOWLIST)
    out = box.run_command("python -c \"print('hi')\"")
    assert "exit_code=0" in out and "hi" in out
    denied = box.call("run_command", {"command": "curl evil.example"})
    assert "вне whitelist" in denied
