"""MCP-сервер (stdio) для работы с DWH Greenplum."""
import anyio
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from . import ch_ddl, ch_query, ch_tables, connections, ddl, query, tables

INSTRUCTIONS = """\
Инструменты для работы с DWH Greenplum (gp_) и ClickHouse (ch_).

- Схему таблиц не угадывай: перед написанием запроса к таблице, структура
  которой не подтверждена в этой сессии, вызови gp_table_ddl / ch_table_ddl.
- Таблица не найдена — проверь имя на опечатку через gp_schema_tables /
  ch_schema_tables.
- Нетривиальный запрос перед выдачей пользователю проверь через
  gp_query_test / ch_query_test.
- gp_query_run и ch_query_run возвращают данные — только по явной просьбе
  пользователя и никогда для персональных данных (ФИО, контакты, документы,
  id клиентов).
- Контуры с readonly — только SELECT и чтение каталога. DDL и DML не выполняй
  и не предлагай пользователю «просто выполнить напрямую».
- Пароль не спрашивай в чат и никуда не передавай. Если инструмент сообщает,
  что пароля нет в keyring — передай пользователю команду из сообщения,
  он выполнит её сам.
- Если инструмент вернул ошибку подключения — сообщи её пользователю и не
  пытайся без прямого указания разбираться в причинах и исходниках сервера.
"""

mcp = FastMCP("dwh", instructions=INSTRUCTIONS)


async def _call(fn, *args) -> str:
    """psycopg2 блокирующий — выполняем в потоке, ошибки отдаём текстом."""
    try:
        return await anyio.to_thread.run_sync(fn, *args)
    except connections.DwhError as e:
        raise ToolError(str(e)) from e


@mcp.tool()
async def gp_connections() -> str:
    """Список контуров DWH (Greenplum): база, RO/RW, логин, сохранён ли пароль, контур по умолчанию."""
    return await _call(connections.describe, "greenplum")


@mcp.tool()
async def gp_table_ddl(table: str, alias: str | None = None) -> str:
    """Получить схему таблицы Greenplum: колонки с типами, not null, default,
    комментарии. Использовать перед написанием любого запроса к таблице,
    структура которой не подтверждена в этой сессии.

    Args:
        table: имя в виде <schema>.<table>. Если схема неизвестна — спроси
            пользователя, не подставляй public. Для партиционированных таблиц
            указывай родительскую таблицу, а не *_1_prt_*.
        alias: контур из connections.yaml; по умолчанию — default.

    Вывод показывай пользователю компактно, не вставляй полотно в чат.
    """
    return await _call(ddl.get_ddl, table, alias)


@mcp.tool()
async def gp_schema_tables(schema: str, name: str | None = None, alias: str | None = None) -> str:
    """Список таблиц и представлений схемы Greenplum (без дочерних партиций
    *_N_prt_*).

    Использовать, когда таблицу не удалось найти в схеме (gp_table_ddl или
    gp_query_test вернули «не найдена» / «does not exist»), чтобы исправить
    возможную опечатку в имени. Передай name — получишь только похожие имена.
    Если не найдена сама схема — в ошибке будут похожие схемы.

    Найденное исправление не применяй молча: назови пользователю, какое имя
    было и какое ты взял, а при нескольких похожих вариантах — спроси.

    Args:
        schema: имя схемы.
        name: имя таблицы с возможной опечаткой (можно с префиксом схемы);
            без него — полный список схемы.
        alias: контур из connections.yaml; по умолчанию — default.
    """
    return await _call(tables.schema_tables, schema, name, alias)


@mcp.tool()
async def gp_query_test(sql: str, alias: str | None = None) -> str:
    """Проверить SQL-запрос к Greenplum перед тем, как отдавать его
    пользователю: синтаксис, существование таблиц и колонок, план выполнения
    (EXPLAIN), наличие motion. Данные не читает. Использовать после написания
    любого нетривиального запроса.

    Только читающие запросы: DML/DDL отклоняются, а соединение открывается
    в read-only транзакции — не пытайся это обойти. Если просят проверить
    INSERT/UPDATE — объясни, что тестовый прогон невозможен.

    При ошибке читай SQLSTATE и подсказку, правь запрос и повторяй.
    Broadcast Motion или Redistribute Motion над большим набором — скажи
    об этом пользователю, это обычно узкое место.

    Args:
        sql: текст запроса (один SELECT, можно с CTE).
        alias: контур из connections.yaml; по умолчанию — default.
    """
    return await _call(query.test_query, sql, alias, False)


@mcp.tool()
async def gp_query_run(sql: str, alias: str | None = None) -> str:
    """Выполнить читающий SQL-запрос к Greenplum и вернуть план и первые
    20 строк результата (read-only транзакция, откатывается).

    Вызывать только когда пользователь явно хочет увидеть данные; для
    проверки запроса хватает gp_query_test.

    ПЕРСОНАЛЬНЫЕ ДАННЫЕ ЗАПРАШИВАТЬ НЕЛЬЗЯ: ФИО, телефоны, email, адреса,
    паспортные и платёжные данные, идентификаторы клиентов и сотрудников
    и т.п. Если результат может их содержать — не выполняй запрос: исключи
    такие колонки, замени агрегатами (count, min/max по датам и суммам)
    или спроси пользователя.

    Args:
        sql: текст запроса (один SELECT, можно с CTE), без персональных данных.
        alias: контур из connections.yaml; по умолчанию — default.
    """
    return await _call(query.test_query, sql, alias, True)


@mcp.tool()
async def ch_connections() -> str:
    """Список контуров ClickHouse: база, RO/RW, логин, сохранён ли пароль, контур по умолчанию."""
    return await _call(connections.describe, "clickhouse")


@mcp.tool()
async def ch_table_ddl(table: str, alias: str | None = None) -> str:
    """Получить схему таблицы ClickHouse: движок, ключи партиционирования и
    сортировки, колонки с типами, default, комментарии. Использовать перед
    написанием любого запроса к таблице, структура которой не подтверждена
    в этой сессии.

    Args:
        table: имя в виде <database>.<table>. Без базы берётся дефолтная база
            контура. Если база неизвестна — спроси пользователя.
        alias: контур из connections.yaml; по умолчанию — default.

    Вывод показывай пользователю компактно, не вставляй полотно в чат.
    """
    return await _call(ch_ddl.get_ddl, table, alias)


@mcp.tool()
async def ch_schema_tables(schema: str, name: str | None = None, alias: str | None = None) -> str:
    """Список таблиц и представлений базы (schema) ClickHouse.

    Использовать, когда таблицу не удалось найти в базе (ch_table_ddl или
    ch_query_test вернули «не найдена» / «does not exist»), чтобы исправить
    возможную опечатку в имени. Передай name — получишь только похожие имена.
    Если не найдена сама база — в ошибке будут похожие базы.

    Найденное исправление не применяй молча: назови пользователю, какое имя
    было и какое ты взял, а при нескольких похожих вариантах — спроси.

    Args:
        schema: имя базы данных ClickHouse.
        name: имя таблицы с возможной опечаткой (можно с префиксом базы);
            без него — полный список базы.
        alias: контур из connections.yaml; по умолчанию — default.
    """
    return await _call(ch_tables.schema_tables, schema, name, alias)


@mcp.tool()
async def ch_query_test(sql: str, alias: str | None = None) -> str:
    """Проверить SQL-запрос к ClickHouse перед тем, как отдавать его
    пользователю: синтаксис, существование таблиц и колонок, план выполнения
    (EXPLAIN PLAN), примерный объём чтения (EXPLAIN ESTIMATE). Данные не читает.
    Использовать после написания любого нетривиального запроса.

    Только читающие запросы: DML/DDL отклоняются, а на readonly-контурах
    сервер не даст изменить данные — не пытайся это обойти. Если просят
    проверить INSERT/UPDATE — объясни, что тестовый прогон невозможен.

    При ошибке читай Code из сообщения, правь запрос и повторяй.
    Большой оценочный объём чтения — скажи об этом пользователю, это обычно
    узкое место.

    Args:
        sql: текст запроса (один SELECT, можно с CTE).
        alias: контур из connections.yaml; по умолчанию — default.
    """
    return await _call(ch_query.test_query, sql, alias, False)


@mcp.tool()
async def ch_query_run(sql: str, alias: str | None = None) -> str:
    """Выполнить читающий SQL-запрос к ClickHouse и вернуть план и первые
    100 строк результата.

    Вызывать только когда пользователь явно хочет увидеть данные; для
    проверки запроса хватает ch_query_test.

    ПЕРСОНАЛЬНЫЕ ДАННЫЕ ЗАПРАШИВАТЬ НЕЛЬЗЯ: ФИО, телефоны, email, адреса,
    паспортные и платёжные данные, идентификаторы клиентов и сотрудников
    и т.п. Если результат может их содержать — не выполняй запрос: исключи
    такие колонки, замени агрегатами (count, min/max по датам и суммам)
    или спроси пользователя.

    Args:
        sql: текст запроса (один SELECT, можно с CTE), без персональных данных.
        alias: контур из connections.yaml; по умолчанию — default.
    """
    return await _call(ch_query.test_query, sql, alias, True)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
