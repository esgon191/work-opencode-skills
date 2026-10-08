# dwh-mcp

Локальный MCP-сервер OpenCode для работы с DWH (Greenplum).

```
├── connections.yaml                 контуры БД (хост, порт, база) — в git
├── connections.local.yaml           логин — локально, в .gitignore
├── pyproject.toml
└── src/dwh_mcp/
    ├── server.py                    MCP-сервер (stdio), описания инструментов
    ├── connections.py               подключение к БД + CLI dwh-connections
    ├── ddl.py                       gp_table_ddl
    └── query.py                     gp_query_test
```

## Инструменты

| Инструмент       | Что делает |
|------------------|------------|
| `gp_connections` | список контуров, логин, сохранён ли пароль |
| `gp_table_ddl`   | колонки таблицы: типы, not null, default, комментарии |
| `gp_query_test`  | EXPLAIN запроса + предупреждения о motion; `run=true` — первые 20 строк в read-only транзакции. DML/DDL не принимает |

## Установка

Нужен [uv](https://docs.astral.sh/uv/) и ветка с `pyproject.toml`. `uv run` ищет
проект в текущей папке — запускай из корня репозитория или указывай `--directory`,
иначе будет `failed to spawn: dwh-connections`.

```bash
cd <Путь к репозиторию>/work-opencode-skills
cp connections.local.yaml.example connections.local.yaml   # указать user
uv run dwh-connections set-password gp_prod                # пароль в keyring
uv run dwh-connections check gp_prod                       # проверка соединения
```

Из любой папки: `uv run --directory <Путь к репозиторию>/work-opencode-skills dwh-connections check gp_prod`.

## Подключение к OpenCode

В `~/.config/opencode/opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "dwh": {
      "type": "local",
      "command": ["uv", "run", "--directory", "<Путь к репозиторию>/work-opencode-skills", "dwh-mcp"],
      "enabled": true
    }
  }
}
```

В OpenCode инструменты видны как `dwh_gp_table_ddl`, `dwh_gp_query_test`, `dwh_gp_connections`.
Проверка: перезапустить `opencode` и спросить, какие есть инструменты dwh.

Обновление = `git pull` (зависимости `uv` подтянет сам при следующем запуске).

`connections.yaml` ищется по порядку: `$DWH_MCP_CONFIG_DIR`, корень репозитория,
`~/.config/opencode/`. Каталог можно задать через `"environment": {"DWH_MCP_CONFIG_DIR": "..."}`
в конфиге сервера.

## Добавление инструмента

Логика — отдельным модулем в `src/dwh_mcp/`, функция возвращает строку и
бросает `DwhError` с понятным текстом. Регистрация — `@mcp.tool()` в
`server.py`. Docstring инструмента — единственное, что модель видит постоянно,
поэтому пиши в нём и что инструмент делает, и когда его применять.
