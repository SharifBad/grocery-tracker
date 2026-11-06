"""grocery.db with the real supabase client against a local fake Supabase HTTP server."""
import csv
import datetime
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock
from urllib.parse import parse_qs, urlparse

import pytest
import streamlit as st

from grocery import db

LINE = {"item_id": "i", "receipt_id": "r", "purchased_on": "2026-11-01", "store": "Lidl",
        "uploaded_by": "Bibi", "name": "Milk", "category": "Dairy", "price": 1.5}
RECEIPTS = [
    {"id": "r1", "purchased_on": "2026-11-01", "store": "REWE Markt GmbH", "total": 3.0, "uploaded_by": "Bibi",
     "created_at": "2026-11-01T10:00:00Z", "updated_by": None, "updated_at": None,
     "items": [{"name": "BUTTER", "category": "Dairy", "price": 2.0}, {"name": "BRÖTCHEN", "category": "Bakery", "price": 1.0},
               {"name": "=HYPERLINK(\"x\")", "category": "Other", "price": -0.5}]},
    {"id": "r2", "purchased_on": "2026-11-01", "store": "Aldi", "total": None, "uploaded_by": "Dad",
     "created_at": "2026-11-01T12:00:00Z", "updated_by": "Bibi", "updated_at": "2026-11-02T09:00:00Z", "items": []},
]


@pytest.fixture
def supabase():
    log = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, obj, status=200):
            data = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def handle_any(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            n = int(self.headers.get("content-length") or 0)
            body = self.rfile.read(n) if n else b""
            log.append((self.command, u.path, q, body))
            if u.path == "/rest/v1/item_lines":
                return self._send([LINE] * (1000 if q.get("offset") == ["0"] else 2))
            if u.path == "/rest/v1/receipts" and self.command == "GET":
                return self._send(RECEIPTS)
            if u.path == "/rest/v1/receipts" and self.command == "DELETE":
                return self._send([], 200)
            if u.path == "/rest/v1/rpc/save_receipt":
                return self._send("11111111-1111-1111-1111-111111111111")
            self._send({"message": "unexpected"}, 404)

        do_GET = do_POST = do_DELETE = handle_any

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    secrets = {"SUPABASE_URL": f"http://127.0.0.1:{server.server_port}", "SUPABASE_SERVICE_KEY": "sb_secret_test"}
    db.client.clear()
    for f in (db.load_item_lines, db.load_receipts, db.find_duplicates):
        f.clear()
    with mock.patch.object(type(st.secrets), "__getitem__", lambda self, k: secrets[k]):
        yield log
    server.shutdown()
    db.client.clear()


def test_load_item_lines_pages_past_1000_rows(supabase):
    df = db.load_item_lines()
    pages = [q for (_, path, q, _) in supabase if path == "/rest/v1/item_lines"]
    assert len(df) == 1002 and [p["offset"] for p in pages] == [["0"], ["1000"]]
    assert isinstance(df["purchased_on"].iloc[0], datetime.date) and df["price"].dtype.kind == "f"


def test_load_receipts_filters_month(supabase):
    db.load_receipts(datetime.date(2026, 11, 1), datetime.date(2026, 12, 1))
    q = supabase[0][2]
    assert q["purchased_on"] == ["gte.2026-11-01", "lt.2026-12-01"] and "items(" in q["select"][0]


def test_find_duplicates_uses_loose_matching(supabase):
    found = db.find_duplicates(datetime.date(2026, 11, 1), "REWE", 3.0)
    assert [r["id"] for r in found] == ["r1"]
    assert supabase[0][2]["purchased_on"] == ["eq.2026-11-01"]
    assert [r["id"] for r in db.find_duplicates(datetime.date(2026, 11, 1), "ALDI SÜD", None)] == ["r2"]
    assert db.find_duplicates(datetime.date(2026, 11, 1), "Lidl", 9.99) == []


def test_save_receipt_calls_rpc_with_iso_date(supabase):
    rid = db.save_receipt({"purchased_on": datetime.date(2026, 11, 1), "store": "Lidl", "total": None},
                          [{"name": "Milk", "category": "Dairy", "price": 1.99}], user="Bibi")
    method, path, _, body = supabase[0]
    assert path == "/rest/v1/rpc/save_receipt" and rid.startswith("1111")
    assert json.loads(body) == {"p_receipt": {"purchased_on": "2026-11-01", "store": "Lidl", "total": None},
                                "p_items": [{"name": "Milk", "category": "Dairy", "price": 1.99}], "p_user": "Bibi", "p_id": None}


def test_delete_receipt(supabase):
    db.delete_receipt("r1")
    assert [(m, p, q["id"]) for (m, p, q, _) in supabase] == [("DELETE", "/rest/v1/receipts", ["eq.r1"])]


def test_export_csv_one_row_per_item_with_bom(supabase):
    data = db.export_csv()
    assert data.startswith("﻿".encode())
    rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
    assert rows[0] == db.EXPORT_COLUMNS
    assert rows[1][:3] == ["r1", "2026-11-01", "REWE Markt GmbH"] and rows[1][8:] == ["BUTTER", "Dairy", "2.0"]
    assert rows[2][8] == "BRÖTCHEN"
    assert rows[3][8:] == ["'=HYPERLINK(\"x\")", "Other", "-0.5"], "formula text escaped, negative price kept numeric"
    assert rows[4][:4] == ["r2", "2026-11-01", "Aldi", ""] and rows[4][6] == "Bibi" and rows[4][8:] == ["", "", ""]
    assert len(rows) == 5


def test_failed_save_still_refreshes_cached_reads(supabase, monkeypatch):
    calls = []
    monkeypatch.setattr(db, "_invalidate", lambda: calls.append(1))
    monkeypatch.setattr(db, "client", lambda: (_ for _ in ()).throw(ConnectionError("network down")))
    with pytest.raises(ConnectionError):
        db.save_receipt({"purchased_on": datetime.date(2026, 11, 1), "store": "X", "total": 1.0}, [], user="Bibi")
    with pytest.raises(ConnectionError):
        db.delete_receipt("r1")
    assert len(calls) == 2
