"""Общая чанкованная запись результатов SQL в CSV, Parquet и Excel."""
import csv
import json
import os
import pathlib
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Iterator, Sequence

from .connections import DwhError

MAX_ROWS = 1_000_000
DEFAULT_CHUNK_SIZE = 10_000
MAX_CHUNK_SIZE = 100_000
FORMATS = {"csv": ".csv", "parquet": ".parquet", "excel": ".xlsx"}


@dataclass(frozen=True)
class ExportOptions:
    path: pathlib.Path
    format: str
    chunk_size: int
    delimiter: str = ","


def prepare_export(
    output_path: str,
    format: str = "csv",
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    delimiter: str = ",",
) -> ExportOptions:
    """Проверить параметры до подключения к БД."""
    fmt = format.strip().lower()
    if fmt == "xlsx":
        fmt = "excel"
    if fmt not in FORMATS:
        raise DwhError("format должен быть csv, parquet или excel")
    if not isinstance(chunk_size, int) or isinstance(chunk_size, bool):
        raise DwhError("chunk_size должен быть целым числом")
    if not 1 <= chunk_size <= MAX_CHUNK_SIZE:
        raise DwhError(f"chunk_size должен быть от 1 до {MAX_CHUNK_SIZE}")
    if len(delimiter) != 1 or delimiter in {'\r', '\n', '"'}:
        raise DwhError("delimiter должен быть одним символом, кроме кавычки и перевода строки")
    if not output_path or not output_path.strip():
        raise DwhError("укажи абсолютный output_path")
    path = pathlib.Path(output_path).expanduser()
    if not path.is_absolute():
        raise DwhError("output_path должен быть абсолютным путём")
    if path.suffix.lower() != FORMATS[fmt]:
        raise DwhError(f"для {fmt} output_path должен заканчиваться на {FORMATS[fmt]}")
    if path.exists():
        raise DwhError(f"файл уже существует, перезапись запрещена: {path}")
    if not path.parent.is_dir():
        raise DwhError(f"каталог не существует: {path.parent}")
    return ExportOptions(path, fmt, chunk_size, delimiter)


def batched(rows: Iterable[Sequence], chunk_size: int) -> Iterator[list]:
    """Собрать поток строк в списки ограниченного размера."""
    chunk = []
    for row in rows:
        chunk.append(tuple(row))
        if len(chunk) >= chunk_size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def export_rows(
    columns: Sequence[str],
    chunks: Iterable[Sequence[Sequence]],
    options: ExportOptions,
    arrow_schema=None,
) -> str:
    """Записать чанки атомарно и удалить временный файл при любой ошибке."""
    columns = [str(c) for c in columns]
    if not columns:
        raise DwhError("запрос не вернул колонок")
    if options.format == "parquet" and len(set(columns)) != len(columns):
        raise DwhError("для Parquet имена колонок должны быть уникальными; добавь алиасы в SQL")
    temp = options.path.with_name(f".{options.path.name}.{uuid.uuid4().hex}.tmp")
    try:
        if options.format == "csv":
            total = _write_csv(temp, columns, chunks, options.delimiter)
        elif options.format == "parquet":
            total = _write_parquet(temp, columns, chunks, arrow_schema)
        else:
            total = _write_excel(temp, columns, chunks)
        # link + unlink: атомарная публикация без перезаписи файла, созданного
        # другим процессом после prepare_export.
        os.link(temp, options.path)
        temp.unlink()
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    return json.dumps(
        {
            "status": "ok",
            "path": str(options.path),
            "format": options.format,
            "rows": total,
            "columns": len(columns),
            "chunk_size": options.chunk_size,
            "bytes": options.path.stat().st_size,
            "max_rows": MAX_ROWS,
        },
        ensure_ascii=False,
    )


def _next_count(total: int, rows: Sequence) -> int:
    if total + len(rows) > MAX_ROWS:
        raise DwhError(
            f"результат больше {MAX_ROWS} строк; выгрузка отменена, файл не создан. "
            "Уточни фильтры или разбей запрос на непересекающиеся части"
        )
    return total + len(rows)


def _check_row(columns: Sequence[str], row: Sequence) -> None:
    if len(row) != len(columns):
        raise DwhError("драйвер вернул строку с числом значений, отличным от числа колонок")


def _write_csv(path, columns, chunks, delimiter) -> int:
    total = 0
    with path.open("x", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=delimiter)
        writer.writerow(columns)
        for rows in chunks:
            total = _next_count(total, rows)
            for row in rows:
                _check_row(columns, row)
                writer.writerow(row)
    return total


def _write_parquet(path, columns, chunks, schema) -> int:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as e:
        raise DwhError("для Parquet нужен pyarrow; выполни uv sync в work-opencode-skills") from e

    total = 0
    writer = None
    stringify = (
        [pa.types.is_string(schema.field(name).type) for name in columns]
        if schema else [None] * len(columns)
    )
    try:
        for rows in chunks:
            if not rows:
                continue
            for row in rows:
                _check_row(columns, row)
            total = _next_count(total, rows)
            records = [
                {
                    name: _arrow_value(value, as_string)
                    for name, value, as_string in zip(columns, row, stringify)
                }
                for row in rows
            ]
            table = pa.Table.from_pylist(records, schema=schema)
            if writer is None:
                writer = pq.ParquetWriter(str(path), table.schema, compression="zstd")
            writer.write_table(table, row_group_size=len(rows))
        if writer is None:
            schema = schema or pa.schema([(name, pa.string()) for name in columns])
            writer = pq.ParquetWriter(str(path), schema, compression="zstd")
    finally:
        if writer is not None:
            writer.close()
    return total


def _arrow_value(value, as_string=None):
    if value is None:
        return None
    if isinstance(value, (dict, list, tuple)) and as_string is not False:
        return json.dumps(value, ensure_ascii=False, default=str)
    if as_string and not isinstance(value, str):
        return str(value)
    return value


def _write_excel(path, columns, chunks) -> int:
    try:
        from openpyxl import Workbook
    except ImportError as e:
        raise DwhError("для Excel нужен openpyxl; выполни uv sync в work-opencode-skills") from e

    total = 0
    book = Workbook(write_only=True)
    sheet = book.create_sheet("export")
    sheet.append(columns)
    for rows in chunks:
        total = _next_count(total, rows)
        for row in rows:
            _check_row(columns, row)
            sheet.append([_excel_value(v) for v in row])
    book.save(path)
    return total


def _excel_value(value):
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.isoformat()
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, default=str)
    if isinstance(value, bytes):
        return value.hex()
    return value
