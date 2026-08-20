"""Общие фикстуры: mock-конфиг без API-ключа (SPEC.md §6.3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.config import ForgeConfig, load_config
from forge.llm import MockClient
from forge.runner import Runner

FORGE_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ForgeConfig:
    """Конфиг в mock-режиме; runs/ уходит во временный каталог, репо не засоряется."""
    monkeypatch.setenv("FORGE_MOCK", "1")
    monkeypatch.delenv("FORGE_MOCK_SCENARIO", raising=False)
    config = load_config(root=FORGE_ROOT, provider_path=FORGE_ROOT / "config" / "providers" / "deepseek.yaml")
    config.runs_dir = tmp_path / "runs"
    config.runs_dir.mkdir()
    return config


@pytest.fixture()
def target(tmp_path: Path) -> Path:
    """Каталог целевого репозитория (без git — git-фаза runner'а пропускается)."""
    path = tmp_path / "target"
    path.mkdir()
    return path


@pytest.fixture()
def runner(cfg: ForgeConfig, target: Path) -> Runner:
    return Runner(cfg, MockClient(cfg), target)


def write_tasks(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "tasks.yaml"
    path.write_text(body, encoding="utf-8")
    return path


TASK_OK = """\
package: test-package
tasks:
  - id: task-ok
    title: "Тестовая задача"
    spec_ref: "SPEC.md"
    scope_paths: ["out/**"]
    depends_on: []
    acceptance:
      - "python -c \\"import pathlib; assert pathlib.Path('out/mock_output.md').exists()\\""
"""
