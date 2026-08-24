# 50 — Шаблон промпта задачи (заполняет agent-forge, не модель)

Плейсхолдеры в {{фигурных}} подставляет runner. Модель получает уже заполненный текст.

---

## Задача {{task.id}}: {{task.title}}

Спека: {{task.spec_ref}} (выдержка ниже). Пакет: {{package.name}}.

### Выдержка спеки
{{spec_excerpt}}

### Релевантный канон
{{canon_excerpt}}

### Репо-контекст (карта сущностей, AGENTS.md, сигнатуры соседей)
{{repo_context}}

### Scope (писать только сюда)
{{task.scope_paths}}

### Acceptance (должны быть зелёными)
{{task.acceptance}}

### Журнал прошлых итераций (если repair)
{{history}}

---

Работай по роли coder (prompts/20). Заверши маркером DONE / BLOCKED / GAP.
