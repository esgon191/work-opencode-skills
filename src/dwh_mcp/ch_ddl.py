"""Схема таблицы ClickHouse: движок, ключи, колонки, default, комментарии."""
from .connections import DwhError, connect

TABLE_INFO = """
select engine, partition_key, sorting_key, comment
from system.tables
where database = {database:String} and name = {table:String};
"""

COLUMNS = """
select name, type, default_kind, default_expression, comment
from system.columns
where database = {database:String} and table = {table:String}
order by position;
"""


def get_ddl(table: str, alias: str | None = None) -> str:
    not_found = DwhError(
        f"таблица {table} не найдена — возможна опечатка, "
        f"проверь имя через ch_schema_tables"
    )
    client = connect(alias, "clickhouse")
    try:
        database, _, rel = table.strip().partition(".")
        if not rel:
            database, rel = client.database, database
        info = client.query(
            TABLE_INFO, parameters={"database": database, "table": rel}
        ).result_rows
        cols = client.query(
            COLUMNS, parameters={"database": database, "table": rel}
        ).result_rows
    finally:
        client.close()
    if not info or not cols:
        raise not_found

    engine, partition, sorting, tbl_comment = info[0]
    out = [f"-- {database}.{rel}  {engine}"]
    if partition:
        out.append(f"-- partition by {partition}")
    if sorting:
        out.append(f"-- order by {sorting}")
    if tbl_comment:
        out.append(f"-- {tbl_comment}")
    for name, typ, dkind, dexpr, comment in cols:
        line = f"  {name:<40} {typ}"
        if dexpr:
            line += f" {dkind.lower()} {dexpr}"
        if comment:
            line += f"  -- {comment}"
        out.append(line)
    return "\n".join(out)
