# 10 полевых сценариев agent-forge

Каждый сценарий — реальный способ работы с агентной кодогенерацией: от greenfield
по спецификации до внедрения в легаси и чужой vibe-code. Цепочка показывает,
какие команды forge и в каком порядке подаёт человек; всё остальное делают
агенты за гейтами. English version: [USECASES.md](USECASES.md).

---

## 0. Детальный разбор: вход в большой рабочий проект

Это опорный кейс: существующий продукт, десятки тысяч строк, нужно
проинициализировать его состояние для agent-forge, найти важные сущности и
настроить работу модели с минимумом расхода токенов — так, чтобы при
доработке сервиса модель видела связанные модели и контракты (иначе — дубли),
но не читала несвязанные файлы (иначе — деньги и деградация внимания).
Каждый шаг разобран «под капотом».

Проект для примера: `big-shop` — монолит на Python (FastAPI), ~200 модулей,
pytest есть, покрытие частичное, AGENTS.md нет.

### Шаг 0.1. Инициализация: `forge init --target ./big-shop --profile careful`

**Что происходит под капотом.** `forge/detect.py` сканирует дерево (без LLM):
маркеры стека (`pyproject.toml`, `package.json`, `*.sln`, `go.mod`,
`Cargo.toml`), CI-конфиги (`.github/workflows/*` — оттуда берутся команды
проверок, которые CI уже считает истиной), существующие тестовые команды.
Затем: `git init` при необходимости, skeleton `tasks.yaml`, и главное —
**baseline**: найденные проверки прогоняются на чистом дереве.

**Что видит человек.** `Baseline зелёный — можно запускать очередь` либо
честный красный стоп со списком упавших команд.

**Зачем это.** Если `pytest` не проходит до агентов, то acceptance любой
задачи будет красным не по вине агента — и каждый прогон упрётся в DISPUTE.
Baseline гарантирует: проблемы проекта чинит человек, проблемы агента видны
на зелёном фоне.

**Типичный отказ.** «стек не определён» — нет маркерных файлов: добавьте
`pyproject.toml`/тестовую команду руками (один раз), как в сценарии 7.

### Шаг 0.2. Карта сущностей: `forge map --target ./big-shop`

**Что происходит под капотом.** `forge/map.py` — детерминированный AST-скан
(без единого вызова модели, $0): для каждого `.py` извлекаются публичные
классы (с именами публичных методов) и функции верхнего уровня с сигнатурами
(без тел), а также локальные импорты, разрешённые в файлы проекта. Из импортов
строится граф связей «файл ↔ файл».

**Артефакты (коммитятся в репо):**
- `canon/entities.json` — машиночитаемый каталог, read-only для агентов;
- `docs/ENTITIES.md` — человекочитаемая карта по каталогам (её же читает
  новый разработчик при входе в проект).

**Почему это отвечает на задачу «не потерять связанное, не загрузить лишнее».**
При доработке `services/orders.py` модель не читает 200 файлов. Она получает:
полное содержимое scope-файлов, **каталог имён всех сущностей** (анти-дубль:
«не пиши `OrderModel`, он уже есть») и **сигнатуры соседей по графу импортов**
(`models/order.py`, `services/pricing.py` — видны контракты без чтения файлов
целиком). Экономика на репо agent-forge (41 файл, 213 сущностей): полное
чтение — ~250K символов; карта — каталог ~8K + сигнатуры соседей ~2K.

**Когда перегенерировать.** После каждого принятого прогона, меняющего
публичную поверхность: `forge map --target .` (секунды, $0).

### Шаг 0.3. Конвенции: AGENTS.md в корень big-shop

Один файл на 20–40 строк: стек, команды проверок, соглашения («ошибки —
через `AppError`, не голые raise», «миграции — alembic, не правим руками»).
Шаблон — `prompts/60_target_AGENTS.md`. Под капотом: runner прикладывает
выдержку AGENTS.md (до 4K символов) в промпт каждой задачи — это самый
дешёвый способ сделать конвенции видимыми модели.

### Шаг 0.4. Черновик задач: `forge wizard --target ./big-shop --prompt "…"`

Промпт: «добавь экспорт заказов в CSV: endpoint в services/orders, тесты».

**Под капотом.** Planner-роль получает скан репо (стек, найденные проверки,
дерево ограниченной глубины) — не файлы целиком — и правило acceptance-
порядка (prompts/10, п.5): команда acceptance обязана быть проходимой на
позиции задачи в DAG. Результат — черновик `tasks.wizard.yaml`: DAG задач со
scope, acceptance из **найденных** проверок (wizard не выдумывает команды;
непроходимые на текущий момент — выкидывает с предупреждением), бюджетами по
профилю careful.

**Гейт №1.** Человек открывает черновик и правит: merge задач, сужение scope,
правка формулировок. `forge lint tasks.wizard.yaml` — контракт + советы
(тесты в scope coder'а, непроходимый acceptance, отсутствие бюджетов).

### Шаг 0.5. Прогон: `forge run --tasks tasks.wizard.yaml --target ./big-shop`

**Под капотом, на каждую задачу:**
1. topo-порядок по `depends_on`; задача, чья зависимость не `done`, не
   стартует никогда (стоп-правило DAG, AF-18);
2. ветка `forge/<task-id>`; коммит после гейта reviewer, push — только
   человеком (NFR-5);
3. сборка промпта coder'а: выдержка спеки + canon (до 30K) + репо-контекст
   шага 0.2–0.3 + scope + acceptance + журнал repair-итераций;
4. цикл «модель ↔ инструменты»: `read_file` / `list_dir` / `run_command`
   (белый список: python, pytest…; установка зависимостей заблокирована),
   `write_file` — только внутри scope (нарушение → SCOPE_VIOLATION в журнал);
5. гейт №2 автоматический: acceptance-команды (доверенные, их писал владелец)
   → reviewer по чек-листу → repair ≤ N итераций → `done | failed | blocked`;
6. гейт №3 человеческий: в профиле careful прогон встаёт после задачи —
   `forge status` покажет `⏸ Прогон ждёт решения: forge accept <id> && forge
   resume <run_id>`.

**Наблюдение:** `forge status` (таблица + подсказка гейта), `forge log
<task-id>` (каждый вызов модели с токенами и ценой), `forge ui` (канбан),
`forge report --plain` («Сделано N из M · потрачено $X» — M по полной
очереди, включая нетронутые).

### Шаг 0.6. Типичные отказы и что делать

| Симптом | Причина | Действие |
|---|---|---|
| DISPUTE | противоречие спеки / reviewer требует вне scope | прочитать `forge log`, уточнить спеку или принять вручную |
| REJECT «нет diff» | обычно ложный: работа уже в дереве | проверить файлы глазами, `forge accept` (override) |
| `per-task кап исчерпан` | coder читает слишком много | сузить scope, проверить что `forge map` свежий |
| задача не стартует | зависимость не done (AF-18) | разрешить зависимость, `forge resume` |
| acceptance красный до агентов | baseline был проигнорирован | чинить проект руками, агенты — потом |

После принятия всех задач: `forge map --target .` (карта свежая),
`forge report --plain`, проверка `git diff` и push — вручную.

---

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
