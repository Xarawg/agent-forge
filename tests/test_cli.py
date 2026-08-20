"""CLI и planner-мock: черновик tasks.yaml (SPEC.md §FR-1), разбор аргументов."""

import yaml

from forge.cli import build_parser
from forge.llm import MockClient


def test_planner_mock_draft_is_valid_yaml(cfg) -> None:
    client = MockClient(cfg)
    result = client.chat("planner", [{"role": "user", "content": "SPEC"}])
    draft = yaml.safe_load(result.content)
    assert draft["tasks"] and draft["tasks"][0]["id"]


def test_cli_parser_commands() -> None:
    parser = build_parser()
    args = parser.parse_args(["run", "--tasks", "config/tasks.example.yaml"])
    assert args.command == "run" and args.tasks.endswith("tasks.example.yaml")
    assert parser.parse_args(["resume", "run-1"]).run_id == "run-1"
    assert parser.parse_args(["accept", "task-1"]).task_id == "task-1"
    assert parser.parse_args(["log", "task-1"]).task_id == "task-1"
    assert parser.parse_args(["report"]).command == "report"
    assert parser.parse_args(["status"]).command == "status"
    assert parser.parse_args(["import", "--spec", "SPEC.md"]).command == "import"
