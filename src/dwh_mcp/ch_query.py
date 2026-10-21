"""Проверка и выполнение SQL-запроса в ClickHouse.

По умолчанию только EXPLAIN. С run=True выполняет запрос с лимитом строк
и возвращает первые строки.
"""
import logging
import re

from clickhouse_connect.driver.exceptions import ClickHouseError

from .connections import DwhError, connect, resolve
from .query import precheck

LIMIT = 100
ATTEMPTS = 5
ESTIMATE_WARN_ROWS = 1_000_000_000
SERVER_ERROR = re.compile(r"Code: \d+")


def test_query(sql: str, alias: str | None = None, run: bool = False) -> str:
    sql = sql.strip().rstrip(";")
    precheck(sql)
    return _with_retry(lambda: _execute(sql, alias, run))


def _with_retry(fn):
    """До 5 попыток на транспортные сбои — как в продовом коде чтения из CH.

    Ошибки запроса (уже обёрнутые в DwhError) и ошибки кода не повторяются.
    """
    last_err = None
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return fn()
        except (AttributeError, DwhError):
            raise
        except Exception as e:
            last_err = e
            logging.warning(f"ClickHouse: попытка {attempt}/{ATTEMPTS} не удалась: {e}")
    raise DwhError(
        f"ClickHouse: не удалось выполнить запрос за {ATTEMPTS} попыток"
    ) from last_err


def _execute(sql: str, alias: str | None, run: bool) -> str:
    d = resolve(alias, "clickhouse")
    settings = {"max_execution_time": 300}
    if d.get("readonly"):
        settings["readonly"] = 1

    client = connect(alias, "clickhouse")
    out = []
    try:
        plan = client.query(f"explain plan {sql}", settings=settings)
        out.append("-- OK, план построен")
        out.extend(r[0] for r in plan.result_rows)
        _add_estimate(client, sql, settings, out)

        if run:
            result = client.query(
                f"select * from ({sql}) limit {LIMIT}", settings=settings
            )
            rows = result.result_rows[:LIMIT]
            out.append(f"\n-- {len(rows)} строк (лимит {LIMIT})")
            out.append(" | ".join(result.column_names))
            for r in rows:
                out.append(" | ".join(str(v) for v in r))
    except ClickHouseError as e:
        if not SERVER_ERROR.search(str(e)):
            raise  # транспортный сбой — повторится в _with_retry
        msg = f"-- ОШИБКА: {e}"
        if "does not exist" in str(e).lower():
            msg += "\n-- возможна опечатка в имени: проверь через ch_schema_tables"
        raise DwhError(msg) from e
    finally:
        try:
            client.close()
        except Exception:
            pass
    return "\n".join(out)


def _add_estimate(client, sql: str, settings: dict, out: list) -> None:
    """Оценка объёма чтения. EXPLAIN ESTIMATE есть не для всех движков и
    версий — ошибки молча пропускаем."""
    try:
        rows = client.query(f"explain estimate {sql}", settings=settings).result_rows
    except Exception:
        return
    total = sum(int(r[3]) for r in rows if len(r) > 3 and r[3] is not None)
    if total > ESTIMATE_WARN_ROWS:
        out.append(
            f"-- ВНИМАНИЕ: примерный объём чтения ~{total:,}".replace(",", " ")
            + " строк — на контуре запрос может быть тяжёлым"
        )
