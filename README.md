# opencode-skills

Скилы OpenCode для работы с DWH.

```
├── connections.yaml                 контуры БД (хост, порт, база) — в git
├── connections.local.yaml           логин — локально, в .gitignore
├── utils/dwhdb/                       общий модуль подключения к БД
└── skills/
    ├── gp-table-ddl/                получение схемы и DDL таблиц Greenplum
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
  "skills": {"paths" : ["~/Desktop/work-opencode-skills/skills"] }
}
```
Обновление скилов = `git pull`.
Проверка: перезапустить `opencode` и спросить, какие есть скилы.

## Добавление скила

Папка в `skills/` с файлом `SKILL.md`; имя папки становится ID, оно же
в `name`. Скрипты — в `scripts/` внутри скила, только если они нужны
именно этому скилу; общий код идёт в `lib/`.

`description` — единственное, что модель видит постоянно, поэтому пиши
в нём и что скил делает, и когда его применять.
