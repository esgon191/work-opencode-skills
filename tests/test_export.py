import csv
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq
from openpyxl import load_workbook

from dwh_mcp import ch_export, exporter, gp_export
from dwh_mcp.connections import DwhError
from dwh_mcp.query import precheck_export


class ExportTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=pathlib.Path.cwd())
        self.root = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def options(self, name, fmt, chunk_size=2):
        return exporter.prepare_export(str(self.root / name), fmt, chunk_size)

    def test_csv_roundtrip_and_bom(self):
        result = json.loads(exporter.export_rows(
            ["id", "text"], [[(1, "а"), (2, 'б,в')]], self.options("data.csv", "csv")
        ))
        raw = (self.root / "data.csv").read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        with (self.root / "data.csv").open(encoding="utf-8-sig", newline="") as f:
            self.assertEqual(list(csv.reader(f)), [["id", "text"], ["1", "а"], ["2", "б,в"]])
        self.assertEqual(result["rows"], 2)

    def test_parquet_roundtrip_with_chunks_and_string_conversion(self):
        schema = pa.schema([pa.field("id", pa.int64()), pa.field("value", pa.string())])
        result = json.loads(exporter.export_rows(
            ["id", "value"], [[(1, None)], [(2, 123), (3, {"x": 1})]],
            self.options("data.parquet", "parquet"), schema,
        ))
        table = pq.read_table(self.root / "data.parquet")
        self.assertEqual(table.to_pylist(), [
            {"id": 1, "value": None}, {"id": 2, "value": "123"}, {"id": 3, "value": '{"x": 1}'},
        ])
        self.assertEqual(result["rows"], 3)
        self.assertGreaterEqual(pq.ParquetFile(self.root / "data.parquet").num_row_groups, 2)

    def test_excel_roundtrip(self):
        result = json.loads(exporter.export_rows(
            ["id", "value"], [[(1, "x"), (2, None)]], self.options("data.xlsx", "excel")
        ))
        book = load_workbook(self.root / "data.xlsx", read_only=True)
        rows = list(book["export"].values)
        self.assertEqual(rows[:2], [("id", "value"), (1, "x")])
        self.assertEqual(rows[2][0], 2)  # read_only OpenPyXL не возвращает хвостовую пустую ячейку
        self.assertEqual(result["rows"], 2)

    def test_exact_limit_succeeds_and_overflow_removes_file(self):
        with patch.object(exporter, "MAX_ROWS", 3):
            result = json.loads(exporter.export_rows(
                ["id"], [[(1,), (2,)], [(3,)]], self.options("exact.csv", "csv")
            ))
            self.assertEqual(result["rows"], 3)
            with self.assertRaisesRegex(DwhError, "больше 3 строк"):
                exporter.export_rows(["id"], [[(1,), (2,)], [(3,), (4,)]], self.options("overflow.csv", "csv"))
        self.assertFalse((self.root / "overflow.csv").exists())
        self.assertEqual(list(self.root.glob(".*.tmp")), [])

    def test_existing_file_and_bad_arguments_are_rejected(self):
        existing = self.root / "existing.csv"
        existing.write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(DwhError, "перезапись запрещена"):
            exporter.prepare_export(str(existing))
        with self.assertRaisesRegex(DwhError, "абсолютным"):
            exporter.prepare_export("relative.csv")
        with self.assertRaisesRegex(DwhError, "chunk_size"):
            exporter.prepare_export(str(self.root / "bad.csv"), chunk_size=100_001)
        with self.assertRaisesRegex(DwhError, "меняет данные"):
            precheck_export("delete from t")
        with self.assertRaisesRegex(DwhError, "ровно один"):
            precheck_export("select 1; select 2")
        self.assertEqual(existing.read_text(encoding="utf-8"), "keep")


class Cursor:
    def __init__(self, rows=(), description=()):
        self.rows = list(rows)
        self.description = description
        self.itersize = None
        self.fetch_sizes = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, sql):
        self.sql = sql

    def fetchmany(self, size):
        self.fetch_sizes.append(size)
        result, self.rows = self.rows[:size], self.rows[size:]
        return result


class Connection:
    def __init__(self):
        self.data = Cursor([(i,) for i in range(5)], [type("Col", (), {"name": "id"})()])
        self.setup = Cursor()
        self.readonly = False

    def set_session(self, readonly, autocommit):
        self.readonly = readonly
        self.autocommit = autocommit

    def cursor(self, name=None):
        return self.data if name else self.setup

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class Stream:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return iter(self.rows)

    def __exit__(self, *args):
        return None


class Client:
    def __init__(self):
        self.meta = type("Meta", (), {"column_names": ["id"], "column_types": [type("Type", (), {"name": "UInt64"})()]})()

    def query(self, sql, settings):
        self.settings = settings
        return self.meta

    def query_rows_stream(self, sql, settings):
        return Stream([(i,) for i in range(5)])

    def close(self):
        self.closed = True


class DriverTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=pathlib.Path.cwd())
        self.root = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_gp_uses_readonly_server_cursor_and_chunks(self):
        conn = Connection()
        with patch.object(gp_export, "connect", return_value=conn):
            result = json.loads(gp_export.export_query(
                "select id from t", str(self.root / "gp.csv"), chunk_size=2
            ))
        self.assertEqual(result["rows"], 5)
        self.assertTrue(conn.readonly)
        self.assertFalse(conn.autocommit)
        self.assertTrue(conn.rolled_back)
        self.assertTrue(conn.closed)
        self.assertEqual(conn.data.itersize, 2)
        self.assertTrue(all(size == 2 for size in conn.data.fetch_sizes))

    def test_ch_uses_stream_and_readonly_setting(self):
        client = Client()
        with patch.object(ch_export, "connect", return_value=client), patch.object(
            ch_export, "resolve", return_value={"readonly": True}
        ):
            result = json.loads(ch_export.export_query(
                "select id from t", str(self.root / "ch.csv"), chunk_size=2
            ))
        self.assertEqual(result["rows"], 5)
        self.assertEqual(client.settings["readonly"], 1)
        self.assertTrue(client.closed)

    def test_clickhouse_type_mapping(self):
        cases = {
            "Nullable(String)": pa.string(),
            "Array(UInt32)": pa.list_(pa.uint32()),
            "Decimal(20, 4)": pa.decimal128(20, 4),
            "DateTime64(3)": pa.timestamp("ms"),
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(ch_export._arrow_type(source, pa), expected)


if __name__ == "__main__":
    unittest.main()
