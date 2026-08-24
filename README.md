# opencode-skills

Скилы OpenCode для работы с DWH.

## Текущий набор скилов:
1. gp-table-ddl - получение DDL таблицы dwh gp smkt. Используется, когда агенту нужно узнать структуру таблицы (набор полей и их типы) для решения задачи

```
├── connections.yaml                 контуры БД (хост, порт, база) — в git
├── connections.local.yaml           логин — локально, в .gitignore
├── utils/dwhdb/                       общий модуль подключения к БД
└── skills/
    ├── gp-table-ddl/                получение схемы и DDL таблиц Greenplum
    ├── gp-test-query/               тест запроса (не работает для DDL / DML), выводит результат ANALYZE
```

## Подключение к OpenCode V1

В `~/.config/opencode/opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "skills": {"paths" : ["<Путь к скачанному репозиторию>/work-opencode-skills/skills"] }
}
```

Требуется указать путь к скачанному репозиторию в конфиге. Например, если репозиторий на рабочем столе:
```json
{
  "$schema": "https://opencode.ai/config.json",
  "skills" : {"paths": ["~/Documents/opencode/skills/work-opencode-skills/skills"]},
}
```
Обновление скилов = `git pull`.
Проверка: перезапустить `opencode` и спросить, какие есть скилы.

Что бы не давать разрешение при выполнении скиллов, можно включить их в permission (есть риски безопасности)
```json
  "permission": {
      "external_directory": {
          "~/Documents/opencode/skills/**": "allow"
      },
      "edit": {
          "~/Documents/opencode/skills/**": "deny"
      },
      "read" : {
          "*" : "ask",
          "**.md" : "allow"
      },
      "bash": {
          "*": "ask",
          "python3 scripts/get_ddl.py *": "allow",
          "python3 scripts/test_query.py *": "allow"
      } 
    }
```

## Добавление скила

Папка в `skills/` с файлом `SKILL.md`; имя папки становится ID, оно же
в `name`. Скрипты — в `scripts/` внутри скила, только если они нужны
именно этому скилу; общий код идёт в `utils/`.

`description` — единственное, что модель видит постоянно, поэтому пиши
в нём и что скил делает, и когда его применять.
