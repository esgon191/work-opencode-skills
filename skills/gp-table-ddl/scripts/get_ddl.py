"""Схема таблицы Greenplum: колонки, ключ дистрибуции, партиции, индексы.

    python scripts/get_ddl.py <schema>.<table> [alias]
"""
import pathlib
import sys

for _d in pathlib.Path(__file__).resolve().parents:
    if (_d / "lib" / "dwhdb").is_dir():
        sys.path.insert(0, str(_d / "lib"))
        break
else:
    sys.exit("не найден lib/dwhdb — скил должен лежать внутри репозитория скилов")

import psycopg2  # noqa: E402

from dwhdb import connect  # noqa: E402

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

        # ключ дистрибуции (GP6+); на GP5 функции нет
        try:
            cur.execute("select pg_get_table_distributedby(%s::regclass);", (relname,))
            print(f"\n{cur.fetchone()[0]}")
        except psycopg2.Error:
            conn.rollback()
            print("\n-- distribution: не определена (проверь gp_distribution_policy)")

        cur.execute(PARTITIONS, (relname,))
        part = cur.fetchone()
        print(
            f"-- partitioned by {part[0]} on ({part[1]}), партиций: {part[2]}"
            if part else "-- not partitioned"
        )

        cur.execute(INDEXES, (relname,))
        for (definition,) in cur.fetchall():
            print(f"-- {definition}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
