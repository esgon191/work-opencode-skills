"""Схема таблицы Greenplum: колонки, ключ дистрибуции, партиции, индексы.

    python scripts/get_ddl.py <schema>.<table> [alias]
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "utils"))

import psycopg2  # noqa: E402

from dwhdb.connections import connect  # noqa: E402

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

PARTITIONS = """
select partitiontype, columnname, count(*) over ()
from pg_partitions
where schemaname || '.' || tablename = %s
limit 1;
"""

INDEXES = """
select indexdef
from pg_indexes
where schemaname || '.' || tablename = %s;
"""


def main(relname: str, alias: str | None = None) -> None:
    with connect(alias) as conn, conn.cursor() as cur:
        cur.execute(COLUMNS, (relname,))
        rows = cur.fetchall()
        if not rows:
            sys.exit(f"таблица {relname} не найдена")

        print(f"-- {relname}")
        for name, typ, notnull, default, comment in rows:
            line = f"  {name:<40} {typ}"
            if notnull:
                line += " not null"
            if default:
                line += f" default {default}"
            if comment:
                line += f"  -- {comment}"
            print(line)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
