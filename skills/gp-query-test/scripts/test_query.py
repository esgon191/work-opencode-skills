"""Проверка SQL-запроса: синтаксис, существование объектов, план.

    python3 test_query.py query.sql [alias] [--run]

По умолчанию только EXPLAIN. С --run выполняет в read-only транзакции
и возвращает первые строки.
"""
import pathlib, sys
import psycopg2, sqlparse

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "utils"))

from dwhdb.connections import connect

WRITE = {"INSERT", "UPDATE", "DELETE", "TRUNCATE", "CREATE", "DROP",
         "ALTER", "GRANT", "REVOKE", "COPY", "MERGE", "VACUUM", "ANALYZE"}
LIMIT = 20


def precheck(sql: str) -> None:
    """Ранняя понятная ошибка. НЕ защита — она на слое read-only."""
    for st in sqlparse.split(sql):
        if not st.strip():
            continue
        kw = sqlparse.parse(st)[0].token_first(skip_cm=True)
        if kw and kw.normalized.upper() in WRITE:
            sys.exit(f"запрос меняет данные ({kw.normalized}), тестировать нельзя")


def main(path: str, alias: str | None = None, run: bool = False) -> None:
    sql = pathlib.Path(path).read_text(encoding="utf-8").strip().rstrip(";")
    precheck(sql)

    conn = connect(alias)
    conn.set_session(readonly=True, autocommit=False)
    try:
        with conn.cursor() as cur:
            cur.execute("set local statement_timeout = '300s'")
            cur.execute("set local lock_timeout = '15s'")

            cur.execute(f"explain {sql}")
            plan = [r[0] for r in cur.fetchall()]
            print("-- OK, план построен")
            for line in plan:
                print(line)
            for line in plan:
                if "Broadcast Motion" in line or "Redistribute Motion" in line:
                    print(f"-- ВНИМАНИЕ: {line.strip()}")

            if run:
                cur.execute(f"select * from ({sql}) t limit {LIMIT}")
                cols = [c.name for c in cur.description]
                rows = cur.fetchall()
                print(f"\n-- {len(rows)} строк (лимит {LIMIT})")
                print(" | ".join(cols))
                for r in rows:
                    print(" | ".join(str(v) for v in r))
    except psycopg2.Error as e:
        print(f"-- ОШИБКА {e.pgcode}: {e.diag.message_primary}", file=sys.stderr)
        if e.diag.message_hint:
            print(f"-- подсказка: {e.diag.message_hint}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.rollback()
        conn.close()


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--run"]
    main(args[0], args[1] if len(args) > 1 else None, "--run" in sys.argv)
