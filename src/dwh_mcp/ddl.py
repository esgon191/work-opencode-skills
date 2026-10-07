"""Схема таблицы Greenplum: колонки, типы, not null, default, комментарии."""
from .connections import DwhError, connect

COLUMNS = """
select a.attname,
       format_type(a.atttypid, a.atttypmod),
       a.attnotnull,
       pg_get_expr(d.adbin, d.adrelid),
       col_description(a.attrelid, a.attnum)
from pg_attribute a
left join pg_attrdef d on d.adrelid = a.attrelid and d.adnum = a.attnum
where a.attrelid = %s::regclass
  and a.attnum > 0
  and not a.attisdropped
order by a.attnum;
"""


def get_ddl(relname: str, alias: str | None = None) -> str:
    with connect(alias) as conn, conn.cursor() as cur:
        cur.execute(COLUMNS, (relname,))
        rows = cur.fetchall()
        if not rows:
            raise DwhError(f"таблица {relname} не найдена")

        out = [f"-- {relname}"]
        for name, typ, notnull, default, comment in rows:
            line = f"  {name:<40} {typ}"
            if notnull:
                line += " not null"
            if default:
                line += f" default {default}"
            if comment:
                line += f"  -- {comment}"
            out.append(line)
        return "\n".join(out)
