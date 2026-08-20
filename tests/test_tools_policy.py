"""Политика команд run_command (v1.1): dotnet разрешён, установка зависимостей запрещена (AF-10)."""

from pathlib import Path

from forge.tools import ToolBox


def make_toolbox(target: Path) -> ToolBox:
    return ToolBox(target, ["**"], ("python", "pytest", "npm", "node", "dotnet", "ruff", "mypy"))


def test_dotnet_allowed(target: Path) -> None:
    """dotnet в whitelist с v1.1 (серверный стек .NET 10). Сам dotnet может
    отсутствовать в PATH тестовой среды — важно, что нет отказа whitelist."""
    out = make_toolbox(target).call("run_command", {"command": "dotnet --version"})
    assert "вне whitelist" not in out


def test_dependency_install_blocked(target: Path) -> None:
    """AF-10: установка зависимостей блокируется кодом, а не промптом."""
    toolbox = make_toolbox(target)
    for bad in (
        "npm install tsx",
        "npm i typescript",
        "npm ci",
        "npx tsx src/cli.ts",
        "pip install jsonschema",
        "python -m pip install jsonschema",
        "dotnet add package Orleans",
        "cd sub && npm install",
    ):
        out = toolbox.call("run_command", {"command": bad})
        assert out.startswith("ERROR:"), bad
        # npx не в whitelist с v1.1 (запрещён там), остальные — через AF-10.
        assert ("AF-10" in out) or ("вне whitelist" in out), bad


def test_innocent_commands_not_blocked(target: Path) -> None:
    """Обычные команды не задевает: npm test/run, node, dotnet build/test."""
    toolbox = make_toolbox(target)
    for ok in ("npm test", "npm run build", "node --version", "dotnet test", "dotnet build"):
        out = toolbox.call("run_command", {"command": ok})
        assert "AF-10" not in out and "вне whitelist" not in out, ok
