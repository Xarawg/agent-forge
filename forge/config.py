"""Конфигурация agent-forge: models.yaml + пресет провайдера + .env (SPEC.md §FR-5/§FR-6)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROLES = ("planner", "coder", "reviewer", "repair")

#: Whitelist команд для инструмента run_command агента (SPEC.md §FR-2).
#: Acceptance-команды из tasks.yaml запускает сам runner (доверенные, их пишет владелец).
#: dotnet — с v1.1: серверный стек продукта (.NET 10), задачи модулей гоняют build/test.
COMMAND_ALLOWLIST = ("python", "pytest", "npm", "node", "dotnet", "ruff", "mypy")


@dataclass
class RoleConfig:
    role: str
    model: str
    max_tokens: int
    temperature: float
    price_per_m_in: float
    price_per_m_out: float
    base_url: str
    api_key: str  # пусто в mock-режиме или для ollama

    def cost_usd(self, tokens_in: int, tokens_out: int) -> float:
        return (tokens_in * self.price_per_m_in + tokens_out * self.price_per_m_out) / 1_000_000


@dataclass
class Budgets:
    per_task_max_tokens: int = 200_000
    per_run_max_cost_usd: float = 0.50
    per_day_max_cost_usd: float = 5.00
    repair_max_iterations: int = 3
    max_state_size_chars: int = 4096   # ограничение размера состояния в промпте (SKILL.state)


@dataclass
class RetryConfig:
    max_attempts: int = 5
    backoff_seconds: list[float] = field(default_factory=lambda: [5, 15, 45, 120, 300])


@dataclass
class ForgeConfig:
    root: Path  # корень репозитория agent-forge (там prompts/, config/, runs/)
    roles: dict[str, RoleConfig]
    budgets: Budgets
    retry: RetryConfig
    mock: bool
    provider_name: str
    fallback_models: list[str] = field(default_factory=list)
    prompts_dir: Path = Path("prompts")
    runs_dir: Path = Path("runs")
    command_allowlist: tuple[str, ...] = COMMAND_ALLOWLIST

    def role(self, name: str) -> RoleConfig:
        return self.roles[name]


def forge_root() -> Path:
    """Корень репозитория agent-forge: FORGE_HOME или родитель пакета (исходный checkout)."""
    env = os.environ.get("FORGE_HOME")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent


def load_env_file(root: Path) -> dict[str, str]:
    """Простой парсер .env (KEY=VALUE), без внешних зависимостей. Секреты не логируются."""
    env_path = root / ".env"
    result: dict[str, str] = {}
    if not env_path.exists():
        return result
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def _env(env: dict[str, str], *names: str) -> str:
    """Первое непустое значение; os.environ приоритетнее .env."""
    for name in names:
        value = os.environ.get(name) or env.get(name)
        if value:
            return value
    return ""


def load_config(root: Path | None = None, provider_path: Path | None = None) -> ForgeConfig:
    """Собрать конфиг: models.yaml + пресет провайдера + env-переопределения ролей."""
    root = (root or forge_root()).resolve()
    env = load_env_file(root)

    models_raw = yaml.safe_load((root / "config" / "models.yaml").read_text(encoding="utf-8"))

    if provider_path is None:
        provider_path = Path(
            _env(env, "FORGE_PROVIDER") or str(root / "config" / "providers" / "deepseek.yaml")
        )
        if not provider_path.is_absolute():
            provider_path = root / provider_path
    provider_raw = yaml.safe_load(provider_path.read_text(encoding="utf-8"))
    provider = provider_raw.get("provider", {})
    provider_roles: dict[str, dict[str, str]] = provider_raw.get("roles", {}) or {}

    mock = _env(env, "FORGE_MOCK").lower() in ("1", "true", "yes")

    roles: dict[str, RoleConfig] = {}
    for role in ROLES:
        rc = models_raw["roles"][role]
        upper = role.upper()
        base_url = _env(env, f"FORGE_{upper}_BASE_URL", "FORGE_BASE_URL") or provider.get("base_url", "")
        key_env = provider.get("api_key_env") or ""
        api_key = _env(env, f"FORGE_{upper}_API_KEY", "FORGE_API_KEY", key_env)
        model = (
            _env(env, f"FORGE_{upper}_MODEL")
            or provider_roles.get(role, {}).get("model")
            or rc["model"]
        )
        if not mock and not api_key and key_env:
            raise RuntimeError(
                f"Нет API-ключа для роли {role}: задайте {key_env} или FORGE_API_KEY в .env, "
                f"либо запускайте mock-режим (FORGE_MOCK=1), либо пресет ollama."
            )
        roles[role] = RoleConfig(
            role=role,
            model=model,
            max_tokens=int(rc["max_tokens"]),
            temperature=float(rc["temperature"]),
            price_per_m_in=float(rc.get("price_per_m_in", 0.0)),
            price_per_m_out=float(rc.get("price_per_m_out", 0.0)),
            base_url=base_url,
            api_key=api_key,
        )

    raw_budgets = models_raw.get("budgets", {}) or {}
    raw_retry = models_raw.get("retry", {}) or {}
    return ForgeConfig(
        root=root,
        roles=roles,
        budgets=Budgets(
            per_task_max_tokens=int(raw_budgets.get("per_task_max_tokens", 200_000)),
            per_run_max_cost_usd=float(raw_budgets.get("per_run_max_cost_usd", 0.50)),
            per_day_max_cost_usd=float(raw_budgets.get("per_day_max_cost_usd", 5.00)),
            repair_max_iterations=int(raw_budgets.get("repair_max_iterations", 3)),
            max_state_size_chars=int(raw_budgets.get("max_state_size_chars", 4096)),
        ),
        retry=RetryConfig(
            max_attempts=int(raw_retry.get("max_attempts", 5)),
            backoff_seconds=[float(s) for s in raw_retry.get("backoff_seconds", [5, 15, 45, 120, 300])],
        ),
        mock=mock,
        provider_name=str(provider.get("name", provider_path.stem)),
        fallback_models=[str(m) for m in (provider_raw.get("fallback_models") or [])],
        prompts_dir=root / "prompts",
        runs_dir=root / "runs",
    )