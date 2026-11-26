"""Проверка SQL-запроса: синтаксис, существование объектов, план.

По умолчанию только EXPLAIN. С run=True выполняет в read-only транзакции
и возвращает первые строки.
"""
import psycopg2, sqlparse

from .connections import DwhError, connect

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
            raise DwhError(f"запрос меняет данные ({kw.normalized}), тестировать нельзя")


def precheck_export(sql: str) -> None:
    """Для выгрузки разрешён ровно один SELECT/WITH; read-only остаётся основной защитой."""
    precheck(sql)
    statements = [st for st in sqlparse.split(sql) if st.strip()]
    if len(statements) != 1:
        raise DwhError("для выгрузки нужен ровно один SELECT-запрос")
    parsed = sqlparse.parse(statements[0])
    kw = parsed[0].token_first(skip_cm=True) if parsed else None
    if not kw or kw.normalized.upper() not in {"SELECT", "WITH"}:
        raise DwhError("выгружать можно только SELECT-запрос, можно с CTE")


def test_query(sql: str, alias: str | None = None, run: bool = False) -> str:
    sql = sql.strip().rstrip(";")
    precheck(sql)

    out = []
    conn = connect(alias, "greenplum")
    conn.set_session(readonly=True, autocommit=False)
    try:
        with conn.cursor() as cur:
            cur.execute("set local statement_timeout = '300s'")
            cur.execute("set local lock_timeout = '15s'")

            cur.execute(f"explain {sql}")
            plan = [r[0] for r in cur.fetchall()]
            out.append("-- OK, план построен")
            out.extend(plan)
            for line in plan:
                if "Broadcast Motion" in line or "Redistribute Motion" in line:
                    out.append(f"-- ВНИМАНИЕ: {line.strip()}")

            if run:
                cur.execute(f"select * from ({sql}) t limit {LIMIT}")
                cols = [c.name for c in cur.description]
                rows = cur.fetchall()
                out.append(f"\n-- {len(rows)} строк (лимит {LIMIT})")
                out.append(" | ".join(cols))
                for r in rows:
                    out.append(" | ".join(str(v) for v in r))
    except psycopg2.Error as e:
        msg = f"-- ОШИБКА {e.pgcode}: {e.diag.message_primary or e}"
        if e.diag.message_hint:
            msg += f"\n-- подсказка: {e.diag.message_hint}"
        if e.pgcode in ("42P01", "3F000"):  # undefined_table, invalid_schema_name
            msg += "\n-- возможна опечатка в имени: проверь через gp_schema_tables"
        raise DwhError(msg) from e
    finally:
        conn.rollback()
        conn.close()
    return "\n".join(out)
