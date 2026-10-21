"""Список таблиц схемы Greenplum (без дочерних партиций)."""
import difflib

from .connections import DwhError, connect

KINDS = {"r": "table", "p": "table", "v": "view", "m": "matview", "f": "foreign"}

TABLES = """
select c.relname, c.relkind
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = %s
  and c.relkind in ('r', 'p', 'v', 'm', 'f')
  and c.relname !~ '_[0-9]+_prt_'
order by c.relname;
"""

SCHEMAS = """
select nspname
from pg_namespace
where nspname !~ '^(pg_|gp_toolkit$|information_schema$)';
"""


def schema_tables(schema: str, name: str | None = None, alias: str | None = None) -> str:
    schema = schema.strip().lower()
    with connect(alias, "greenplum") as conn, conn.cursor() as cur:
        cur.execute(TABLES, (schema,))
        rows = cur.fetchall()
        if not rows:
            cur.execute(SCHEMAS)
            schemas = [r[0] for r in cur.fetchall()]
            if schema in schemas:
                return f"-- схема {schema} пуста"
            similar = difflib.get_close_matches(schema, schemas, n=5, cutoff=0.6)
            msg = f"схема {schema} не найдена"
            if similar:
                msg += f"; похожие: {', '.join(similar)}"
            raise DwhError(msg)

    if name:
        names = [r[0] for r in rows]
        name = name.strip().lower().split(".")[-1]
        close = difflib.get_close_matches(name, names, n=10, cutoff=0.5)
        close += [n for n in names if name in n and n not in close]
        kinds = dict(rows)
        if not close:
            return f"-- в {schema} нет таблиц, похожих на {name} (всего {len(rows)})"
        return "\n".join(
            [f"-- {schema}: похожие на {name}"]
            + [f"  {schema}.{n}  ({KINDS[kinds[n]]})" for n in close]
        )

    out = [f"-- {schema}: {len(rows)} объектов"]
    out += [f"  {rel}" + ("" if kind in "rp" else f"  ({KINDS[kind]})") for rel, kind in rows]
    return "\n".join(out)
