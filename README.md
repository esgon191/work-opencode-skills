# opencode-skills

Скилы OpenCode для работы с DWH.

```
├── connections.yaml                 контуры БД (хост, порт, база) — в git
├── connections.local.yaml           логин — локально, в .gitignore
├── lib/dwhdb/                       общий модуль подключения к БД
└── skills/
    ├── gp-table-ddl/                схема и DDL таблиц Greenplum
    ├── gp-query-conventions/        правила написания SQL
    └── dwh-naming/                  конвенции именования
```

## Установка

```bash
pip install psycopg2-binary pyyaml keyring

cp connections.local.yaml.example connections.local.yaml
# указать свой user

python lib/dwhdb/connections.py set-password gp_prod
python lib/dwhdb/connections.py check gp_prod
```

## Подключение к OpenCode

В `~/.config/opencode/opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "skills": ["~/work/opencode-skills/skills"]
}
```

Путь абсолютный или через `~/` — относительные резолвятся от рабочей
директории OpenCode, а не от конфига. Обновление скилов = `git pull`.

Проверка: перезапустить `opencode` и спросить, какие есть скилы.

## Добавление скила

Папка в `skills/` с файлом `SKILL.md`; имя папки становится ID, оно же
в `name`. Скрипты — в `scripts/` внутри скила, только если они нужны
именно этому скилу; общий код идёт в `lib/`.

`description` — единственное, что модель видит постоянно, поэтому пиши
в нём и что скил делает, и когда его применять.
