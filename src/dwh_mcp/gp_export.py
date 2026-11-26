"""Чанкованная выгрузка Greenplum через server-side cursor."""
import uuid

import psycopg2

from .connections import DwhError, connect
from .exporter import DEFAULT_CHUNK_SIZE, export_rows, prepare_export
from .query import precheck_export


def export_query(
    sql: str,
    output_path: str,
    format: str = "csv",
    alias: str | None = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    delimiter: str = ",",
) -> str:
    options = prepare_export(output_path, format, chunk_size, delimiter)
    sql = sql.strip().rstrip(";")
    precheck_export(sql)
    conn = connect(alias, "greenplum")
    conn.set_session(readonly=True, autocommit=False)
    try:
        with conn.cursor() as setup:
            setup.execute("set local statement_timeout = '300s'")
            setup.execute("set local lock_timeout = '15s'")
        with conn.cursor(name=f"gp_export_{uuid.uuid4().hex}") as cur:
            cur.itersize = options.chunk_size
            cur.execute(sql)
            columns = [c.name for c in cur.description]
            schema = _arrow_schema(cur.description) if options.format == "parquet" else None
            chunks = iter(lambda: cur.fetchmany(options.chunk_size), [])
            return export_rows(columns, chunks, options, schema)
    except DwhError:
        raise
    except psycopg2.Error as e:
        message = e.diag.message_primary if e.diag else None
        raise DwhError(f"Greenplum: {message or e}; файл не создан") from e
    except Exception as e:
        raise DwhError(f"выгрузка Greenplum не выполнена: {e}; файл не создан") from e
    finally:
        conn.rollback()
        conn.close()


def _arrow_schema(description):
    """Сохранить основные типы GP; редкие типы безопасно писать строками."""
    import pyarrow as pa

    basic = {
        16: pa.bool_(), 17: pa.binary(), 20: pa.int64(), 21: pa.int16(),
        23: pa.int32(), 26: pa.int64(), 700: pa.float32(), 701: pa.float64(),
        1042: pa.string(), 1043: pa.string(), 1082: pa.date32(),
        1083: pa.time64("us"), 1114: pa.timestamp("us"),
        1184: pa.timestamp("us", tz="UTC"), 2950: pa.string(),
    }
    fields = []
    for col in description:
        if col.type_code == 1700:  # NUMERIC: точный decimal, если GP сообщил параметры
            if col.precision and col.scale is not None and col.precision <= 38:
                dtype = pa.decimal128(col.precision, col.scale)
            else:
                dtype = pa.string()
        else:
            dtype = basic.get(col.type_code, pa.string())
        fields.append(pa.field(col.name, dtype))
    return pa.schema(fields)
