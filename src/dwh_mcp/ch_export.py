"""Чанкованная выгрузка ClickHouse через query_rows_stream."""
import re

from clickhouse_connect.driver.exceptions import ClickHouseError

from .connections import DwhError, connect, resolve
from .exporter import DEFAULT_CHUNK_SIZE, batched, export_rows, prepare_export
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
    target = resolve(alias, "clickhouse")
    settings = {"max_execution_time": 300}
    if target.get("readonly"):
        settings["readonly"] = 1
    client = connect(alias, "clickhouse")
    try:
        # LIMIT 0 даёт имена и типы, не материализуя результат. Повторный запуск
        # потока после ошибки не делаем: это могло бы дать дубли или другой срез.
        meta = client.query(f"select * from ({sql}) limit 0", settings=settings)
        schema = (
            _arrow_schema(meta.column_names, meta.column_types)
            if options.format == "parquet"
            else None
        )
        with client.query_rows_stream(sql, settings=settings) as stream:
            chunks = batched(stream, options.chunk_size)
            return export_rows(meta.column_names, chunks, options, schema)
    except DwhError:
        raise
    except ClickHouseError as e:
        raise DwhError(f"ClickHouse: {e}; файл не создан") from e
    except Exception as e:
        raise DwhError(f"выгрузка ClickHouse не выполнена: {e}; файл не создан") from e
    finally:
        client.close()


def _arrow_schema(names, types):
    import pyarrow as pa

    return pa.schema([pa.field(str(name), _arrow_type(str(getattr(t, "name", t)), pa)) for name, t in zip(names, types)])


def _arrow_type(name: str, pa):
    """Преобразовать распространённые типы CH в Arrow, включая Nullable/Array."""
    name = name.strip()
    for wrapper in ("Nullable", "LowCardinality"):
        match = re.fullmatch(rf"{wrapper}\((.*)\)", name)
        if match:
            return _arrow_type(match.group(1), pa)
    simple = {
        "Bool": pa.bool_(), "String": pa.string(), "UUID": pa.string(),
        "IPv4": pa.string(), "IPv6": pa.string(), "JSON": pa.string(),
        "UInt8": pa.uint8(), "UInt16": pa.uint16(), "UInt32": pa.uint32(),
        "UInt64": pa.uint64(), "Int8": pa.int8(), "Int16": pa.int16(),
        "Int32": pa.int32(), "Int64": pa.int64(), "Float32": pa.float32(),
        "Float64": pa.float64(), "Date": pa.date32(), "Date32": pa.date32(),
        "Nothing": pa.null(),
    }
    if name in simple:
        return simple[name]
    match = re.fullmatch(r"(?:U?Int)(128|256)", name)
    if match:
        return pa.string()  # Arrow decimal не всегда вмещает эти значения
    match = re.fullmatch(r"Decimal\((\d+),\s*(\d+)\)", name)
    if match:
        precision, scale = int(match.group(1)), int(match.group(2))
        return pa.decimal128(precision, scale) if precision <= 38 else pa.decimal256(precision, scale)
    match = re.fullmatch(r"DateTime(?:64\((\d+)(?:,\s*'([^']+)')?\))?(?:\('([^']+)'\))?", name)
    if match:
        precision = int(match.group(1) or 0)
        unit = {0: "s", 3: "ms", 6: "us", 9: "ns"}.get(precision, "us")
        return pa.timestamp(unit, tz=match.group(2) or match.group(3))
    match = re.fullmatch(r"Array\((.*)\)", name)
    if match:
        return pa.list_(_arrow_type(match.group(1), pa))
    match = re.fullmatch(r"FixedString\(\d+\)", name)
    if match:
        return pa.string()
    return pa.string()
