# dwh-mcp

Локальный MCP-сервер OpenCode для работы с DWH (Greenplum).

```
├── connections.yaml                 контуры БД (хост, порт, база) — в git
├── connections.local.yaml           логин — локально, в .gitignore
├── pyproject.toml
└── src/dwh_mcp/
    ├── server.py                    MCP-сервер (stdio), описания инструментов
    ├── connections.py               подключение к БД (Greenplum и ClickHouse) + CLI dwh-connections
    ├── ddl.py                       gp_table_ddl
    ├── tables.py                    gp_schema_tables
    ├── query.py                     gp_query_test, gp_query_run
    ├── ch_ddl.py                    ch_table_ddl (ClickHouse)
    ├── ch_tables.py                 ch_schema_tables (ClickHouse)
    └── ch_query.py                  ch_query_test, ch_query_run (ClickHouse)
```

## Инструменты

| Инструмент       | Что делает |
|------------------|------------|
| `gp_connections` | список контуров Greenplum, логин, сохранён ли пароль |
| `gp_table_ddl`   | колонки таблицы: типы, not null, default, комментарии |
| `gp_schema_tables` | таблицы и представления схемы без дочерних партиций; с `name` — только похожие имена. Для исправления опечаток, когда таблица не найдена |
| `gp_query_test`  | EXPLAIN запроса + предупреждения о motion, данные не читает. DML/DDL не принимает |
| `gp_query_run`   | то же + первые 20 строк результата в read-only транзакции. **Требует подтверждения** (см. ниже) |
| `ch_connections` | список контуров ClickHouse, логин, сохранён ли пароль |
| `ch_table_ddl`   | схема таблицы ClickHouse: движок, ключи партиционирования и сортировки, колонки, default, комментарии |
| `ch_schema_tables` | таблицы и представления базы ClickHouse; с `name` — только похожие имена |
| `ch_query_test`  | EXPLAIN PLAN + EXPLAIN ESTIMATE (предупреждение при большом объёме чтения), данные не читает. DML/DDL не принимает |
| `ch_query_run`   | то же + первые 100 строк результата (readonly на уровне серверных настроек). **Требует подтверждения** (см. ниже) |

> ⚠️ `gp_query_run` и `ch_query_run` отдают данные из DWH в модель. **Запрашиваемые
> данные не должны быть персональными** — ФИО, телефоны, email, адреса, паспортные
> и платёжные данные, идентификаторы клиентов и сотрудников. Перед подтверждением
> вызова смотри на список колонок в запросе и отклоняй, если там есть ПДн. Полезно найти страницу источника данных в confluence - там есть статус ПДн каждой колонки.

## Установка

Нужен [uv](https://docs.astral.sh/uv/) и ветка с `pyproject.toml`. `uv run` ищет
проект в текущей папке — запускай из корня репозитория или указывай `--directory`,
иначе будет `failed to spawn: dwh-connections`.

```bash
cd <Путь к репозиторию>/work-opencode-skills
cp connections.local.yaml.example connections.local.yaml   # указать user
uv run dwh-connections set-password gp_prod                # пароль в keyring
uv run dwh-connections check gp_prod                       # проверка соединения
uv run dwh-connections set-password ch_prod                # пароль ClickHouse
uv run dwh-connections check ch_prod
```

Из любой папки: `uv run --directory <Путь к репозиторию>/work-opencode-skills dwh-connections check gp_prod`.

## Подключение к OpenCode

В директории конфига, поумолчанию `~/.config/opencode/opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "dwh": {
      "type": "local",
      "command": ["/Users/<you>/<Путь к репозиторию>/work-opencode-skills/.venv/bin/dwh-mcp"],
      "enabled": true
    }
  },
  "permission": {
    "dwh_gp_query_run": "ask",
    "dwh_ch_query_run": "ask"
  }
}
```

`"dwh_gp_query_run": "ask"` и `"dwh_ch_query_run": "ask"` — opencode спрашивает
подтверждение перед каждым выполнением запроса с выдачей данных; остальные
инструменты dwh работают без вопросов. Не меняй на `allow`: подтверждение —
место, где ты проверяешь, что в запросе нет персональных данных.

Путь — только **абсолютный**: opencode запускает команду без shell, `~` и `$HOME`
не раскрываются, и сервер падает с `MCP error -32000: Connection Closed`.
Получить путь: `echo "$PWD/.venv/bin/dwh-mcp"` в корне репозитория (venv создаётся
после первого `uv sync` / `uv run`).

Вариант через uv (подтягивает зависимости сам после `git pull`), тоже с абсолютными путями —
`uv` может отсутствовать в `PATH` процесса opencode:
`["/Users/<you>/.local/bin/uv", "run", "--directory", "/Users/<you>/.../work-opencode-skills", "dwh-mcp"]`.

Если сервер не поднимается — смотри логи opencode в `~/.local/share/opencode/log/`.

В OpenCode инструменты видны как `dwh_gp_table_ddl`, `dwh_gp_schema_tables`,
`dwh_gp_query_test`, `dwh_gp_query_run`, `dwh_gp_connections`, `dwh_ch_table_ddl`,
`dwh_ch_schema_tables`, `dwh_ch_query_test`, `dwh_ch_query_run`, `dwh_ch_connections`.
Проверка: перезапустить `opencode` и спросить, какие есть инструменты dwh.

Обновление = `git pull` + `uv sync`.

`connections.yaml` ищется по порядку: `$DWH_MCP_CONFIG_DIR`, корень репозитория,
`~/.config/opencode/`. Каталог можно задать через `"environment": {"DWH_MCP_CONFIG_DIR": "..."}`
в конфиге сервера.

## Добавление инструмента

Логика — отдельным модулем в `src/dwh_mcp/`, функция возвращает строку и
бросает `DwhError` с понятным текстом. Регистрация — `@mcp.tool()` в
`server.py`. Docstring инструмента — единственное, что модель видит постоянно,
поэтому пиши в нём и что инструмент делает, и когда его применять.
