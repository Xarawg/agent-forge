# 10 полевых сценариев agent-forge

Каждый сценарий — реальный способ работы с агентной кодогенерацией: от greenfield
по спецификации до внедрения в легаси и чужой vibe-code. Цепочка показывает,
какие команды forge и в каком порядке подаёт человек; всё остальное делают
агенты за гейтами. English version: [USECASES.md](USECASES.md).

## 1. Greenfield: новый сервис от спецификации к коду

**Контекст.** Стартап пишет URL-shortener с нуля. Сначала человек пишет SPEC.md
(API, хранение, критерии приёмки), затем пакет идёт в агентов.

```bash
forge init --target ./shortener                       # git, skeleton, baseline
forge import --spec ./shortener/SPEC.md --out tasks.draft.yaml   # planner: SPEC → DAG
forge lint tasks.draft.yaml                           # контракт + порядок acceptance
forge run --tasks tasks.draft.yaml --target ./shortener --spec ./shortener/SPEC.md --dry-run
forge run --tasks tasks.draft.yaml --target ./shortener --spec ./shortener/SPEC.md
forge accept models-layer && forge resume run-…       # гейт после каркаса
forge report --plain                                  # итог простым языком
```

Задачи идут по DAG: модели → хранилище → API → тесты → docs. Тесты — отдельной
задачей после кода (prompts/10, п.5), acceptance каждой задачи проходим на её
позиции. Каждый `gate` — точка, где человек смотрит diff.

## 2. Contract-first: от OpenAPI-контракта к реализации

**Контекст.** Команда согласовала `openapi.yaml` с фронтендом; бэкенд должен
ему соответствовать. Контракт — источник истины, acceptance — контрактные тесты.

```bash
forge wizard --target ./backend \
  --prompt "реализуй эндпоинты по openapi.yaml; acceptance: schemathesis run openapi.yaml"
# wizard находит проверки, чертит задачу на группу эндпоинтов
forge run --tasks ./backend/tasks.wizard.yaml --target ./backend
# reviewer проверяет: код не выходит за scope, контрактные тесты зелёные
forge accept users-endpoints && forge resume run-…
```

Scope каждой задачи — свой пакет эндпоинтов; `canon/` с openapi.yaml —
read-only для coder'а, контракт нельзя «подправить под код».

## 3. Новый микросервис в существующей монорепе с каноном

**Контекст.** В монорепе есть `canon/decisions.json` (ADR, соглашения). Новый
сервис обязан им следовать, а не изобретать свои.

```bash
forge wizard --target ./monorepo --prompt "новый сервис billing по canon-решениям"
# в tasks.wizard.yaml добавляем вручную: canon_snapshot: canon/decisions.json
forge lint ./monorepo/tasks.wizard.yaml
forge run --tasks ./monorepo/tasks.wizard.yaml --target ./monorepo
```

`canon_snapshot` прикладывается к промпту каждой задачи; попытка coder'а писать
в `canon/` блокируется инструментом и пишется в журнал как SCOPE_VIOLATION.

## 4. Легаси без тестов: сначала земля, потом агенты

**Контекст.** 8-летний Django-проект, тестов нет, «работает — не трогай».
Первый заход агентов — не фичи, а проверяемость.

```bash
forge init --target ./legacy-shop          # baseline КРАСНЫЙ: проверок нет
forge wizard --target ./legacy-shop --recipe test-coverage
# ? модуль → src/payments · команда → python -m pytest -q   (без LLM, $0)
forge run --tasks ./legacy-shop/tasks.wizard.yaml --target ./legacy-shop
forge accept cover-payments && forge resume run-…
```

Baseline честно говорит «проверять нечем» до трат на модели. Первая задача
пишет тесты на существующий код — acceptance прогоняет новые тесты против
старого кода. Только потом имеет смысл рефакторинг.

## 5. Легаси-миграция: порт по модулю с паритетом

**Контекст.** Перенос валидатора с Python на TypeScript; требование — побитовый
паритет поведения. Один модуль = одна задача.

```bash
# tasks.yaml руками: acceptance — прогон golden-наборов через обе реализации
forge lint tools/migration.tasks.yaml
forge run --tasks tools/migration.tasks.yaml --target ./repo --dry-run   # прогноз
forge run --tasks tools/migration.tasks.yaml --target ./repo
```

Acceptance сравнивает вывод старой и новой реализации на golden-данных:
паритет доказан тестом, а не уверениями модели. Красный прогон → repair-цикл
(≤3 итераций), дальше — `failed` с журналом, а не тихий merge.

## 6. Brownfield с документацией: AGENTS.md уже есть

**Контекст.** В репозитории ведут AGENTS.md (стек, команды, соглашения) и
docs/SPEC.md. Инструмент читает то, что уже написано.

```bash
forge import --spec ./repo/docs/SPEC.md --out tasks.draft.yaml
forge lint tasks.draft.yaml
forge run --tasks tasks.draft.yaml --target ./repo --spec ./repo/docs/SPEC.md
```

AGENTS.md из корня target попадает в контекст coder'а — он пишет в соглашениях
проекта, а не «в среднем по GitHub». `--spec` прикладывает выдержку спеки к
промпту каждой задачи.

## 7. Vibe-code: проект сгенерирован «на коленке» другим AI

**Контекст.** Прототип от другого AI-инструмента: код работает, но структуры
нет, тестов нет, проверки не запускаются. Задача — превратить в поддерживаемое.

```bash
forge init --target ./vibe-app --profile careful     # baseline красный — честный стоп
# человек сначала чинит запуск проверок (один раз, руками)
forge wizard --target ./vibe-app \
  --prompt "разбей god-object app.py на модули, сверху pytest-тесты" --profile careful
forge run --tasks ./vibe-app/tasks.wizard.yaml --target ./vibe-app
# careful: кап $0.30/задача и гейт после каждой — полный контроль над хаосом
forge accept split-config && forge resume run-…
```

Wizard не выдумывает проверки: берёт только найденные в репо. Acceptance,
который ещё не может пройти (pytest до появления тестов), выкидывается из
черновика с предупреждением — DISPUTE на пустом месте не случается.

## 8. Чужая AI-driven практика: спеки от spec-kit / BMAD

**Контекст.** Проект вели по другой методологии: каталог `specs/` с чужим
форматом фич, часть реализована, часть — нет, архитектура местами сломана.

```bash
forge import --spec ./repo/specs/004-export/SPEC.md --out tasks.draft.yaml
# гейт №1: человек вычитывает черновик — planner честно выносит противоречия
forge lint tasks.draft.yaml        # предупредит о непроходимом acceptance
forge run --tasks tasks.draft.yaml --target ./repo
```

Если спека расходится с кодом, repair-агент не «додумывает»: маркер DISPUTE →
задача в `blocked`, решение принимает человек (`forge accept` как override или
правка спеки). Противоречия не прячутся — это принцип инструмента.

## 9. Мульти-репо: одно изменение в пяти сервисах

**Контекст.** Смена формата auth-токена затрагивает 5 репозиториев. Одна и та
же очередь прогоняется по каждому — отдельные ветки, журналы, стоимость.

```bash
for repo in api gateway billing notify web; do
  forge run --tasks token-v2.tasks.yaml --target ./$repo
done
forge report run-…    # по каждому прогону: стоимость, состояние, repair'ы
forge ui              # канбан всех прогонов разом, только чтение
```

Никакого push: ветки `forge/<task-id>` и коммиты локальные, публикует владелец
(NFR-5). per-day кап суммируется по всем прогонам суток — бюджет не разъедется.

## 10. Дрейф документации после AI-спринтов

**Контекст.** Несколько спринтов кодогенерации — README и ANALYTICS отстали от
кода. Рецепт docs-sync возвращает синхрон без вызова планировщика.

```bash
forge wizard --target ./repo --recipe docs-sync       # детерминированно, $0
forge run --tasks ./repo/tasks.wizard.yaml --target ./repo
forge report --plain   # «Сделано 2 из 2: README, ANALYTICS — $0.07»
forge ui               # визуальный контроль: что когда починялось
```

Acceptance для docs-задач — не тесты, а проверки владельца (линтер markdown,
прогон примеров из README). Инструменту всё равно, что гейтит задачу, — лишь
бы команда была честной и зеленела.

## Общий скелет любого сценария

1. **Подготовка**: `forge init` / `forge wizard` / `forge import` → черновик, гейт №1 — человек.
2. **Предполёт**: `forge lint` + `--dry-run` → контракт, порядок acceptance, прогноз цены.
3. **Прогон**: `forge run` → coder → acceptance → reviewer → repair, капы бюджета на каждом шаге.
4. **Гейты**: `forge accept` / `forge resume` → человек между милстоунами; blocked/failed — override владельца.
5. **Контроль**: `forge status` / `forge log` / `forge report --plain` / `forge ui` → всё на диске в `runs/`.
