"""Профили онбординга: careful / normal / fast.

Один выбор вместо правки models.yaml: профиль задаёт перезадачные капы,
которые wizard/init подставляют в генерируемую очередь, и советы по гейтам.
Дефолт для новых пользователей — careful: дёшево, гейт после каждой задачи.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    name: str
    task_max_tokens: int
    task_max_cost_usd: float
    per_run_max_cost_usd: float
    per_day_max_cost_usd: float
    repair_max_iterations: int
    gate_every_task: bool  # совет: гейт после каждой задачи vs только между волнами
    hint: str


PROFILES: dict[str, Profile] = {
    "careful": Profile(
        name="careful",
        task_max_tokens=150_000,
        task_max_cost_usd=0.30,
        per_run_max_cost_usd=2.00,
        per_day_max_cost_usd=3.00,
        repair_max_iterations=2,
        gate_every_task=True,
        hint="Осторожный: минимальные капы, гейт после каждой задачи. "
             "Подходит для первых прогонов и бесплатных моделей (OpenRouter :free).",
    ),
    "normal": Profile(
        name="normal",
        task_max_tokens=200_000,
        task_max_cost_usd=0.50,
        per_run_max_cost_usd=5.00,
        per_day_max_cost_usd=5.00,
        repair_max_iterations=3,
        gate_every_task=False,
        hint="Обычный: дефолты models.yaml, гейты между волнами.",
    ),
    "fast": Profile(
        name="fast",
        task_max_tokens=300_000,
        task_max_cost_usd=1.00,
        per_run_max_cost_usd=12.00,
        per_day_max_cost_usd=20.00,
        repair_max_iterations=3,
        gate_every_task=False,
        hint="Быстрый: крупные задачи, редкие гейты. Только когда пайплайн уже проверен.",
    ),
}

DEFAULT_PROFILE = "careful"


def get_profile(name: str) -> Profile:
    """Профиль по имени; неизвестное имя — ошибка с перечнем доступных."""
    try:
        return PROFILES[name]
    except KeyError:
        raise ValueError(
            f"Неизвестный профиль {name!r}. Доступны: {', '.join(PROFILES)}"
        ) from None


def render_profiles() -> str:
    """Таблица профилей для вывода в init/wizard."""
    lines = ["Профили (выбор вместо правки models.yaml):"]
    for profile in PROFILES.values():
        lines.append(
            f"  {profile.name:8} — задача ≤ ${profile.task_max_cost_usd:.2f}, "
            f"прогон ≤ ${profile.per_run_max_cost_usd:.2f}, день ≤ ${profile.per_day_max_cost_usd:.2f}, "
            f"repair ≤ {profile.repair_max_iterations}"
            + (", гейт после каждой задачи" if profile.gate_every_task else "")
        )
        lines.append(f"           {profile.hint}")
    return "\n".join(lines)
