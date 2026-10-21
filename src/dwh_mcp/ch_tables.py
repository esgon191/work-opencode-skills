"""Список таблиц базы ClickHouse (без внутренних таблиц .inner%)."""
import difflib

from .connections import DwhError, connect

KINDS = {
    "View": "view",
    "MaterializedView": "matview",
    "WindowView": "window view",
    "LiveView": "live view",
    "Dictionary": "dictionary",
}

TABLES = """
select name, engine
from system.tables
where database = {database:String}
  and name not like '.inner%'
order by name;
"""

DATABASES = """
select name
from system.databases
where name not in ('system', 'INFORMATION_SCHEMA', 'information_schema')
order by name;
"""


def schema_tables(schema: str, name: str | None = None, alias: str | None = None) -> str:
    schema = schema.strip()
    client = connect(alias, "clickhouse")
    try:
        rows = client.query(TABLES, parameters={"database": schema}).result_rows
        if not rows:
            databases = [r[0] for r in client.query(DATABASES).result_rows]
            if schema in databases:
                return f"-- база {schema} пуста"
            similar = difflib.get_close_matches(schema, databases, n=5, cutoff=0.6)
            msg = f"база {schema} не найдена"
            if similar:
                msg += f"; похожие: {', '.join(similar)}"
            raise DwhError(msg)
    finally:
        client.close()

    if name:
        names = [r[0] for r in rows]
        name = name.strip().split(".")[-1]
        close = difflib.get_close_matches(name, names, n=10, cutoff=0.5)
        close += [n for n in names if name in n and n not in close]
        engines = dict(rows)
        if not close:
            return f"-- в {schema} нет таблиц, похожих на {name} (всего {len(rows)})"
        return "\n".join(
            [f"-- {schema}: похожие на {name}"]
            + [
                f"  {schema}.{n}" + (f"  ({KINDS[engines[n]]})" if engines[n] in KINDS else "")
                for n in close
            ]
        )

    out = [f"-- {schema}: {len(rows)} объектов"]
    out += [
        f"  {n}" + (f"  ({KINDS[e]})" if e in KINDS else "")
        for n, e in rows
    ]
    return "\n".join(out)
