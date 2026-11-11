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
    {"id": "r1", "purchased_on": "2026-11-01", "store": "REWE Markt GmbH", "total": 3.0, "uploaded_by": "Bibi", "paid_by": "Dad", "personal": True,
     "created_at": "2026-11-01T10:00:00Z", "updated_by": None, "updated_at": None,
     "items": [{"name": "BUTTER", "category": "Dairy", "price": 2.0, "quantity": 2}, {"name": "BRÖTCHEN", "category": "Bakery", "price": 1.0, "quantity": 1},
               {"name": "=HYPERLINK(\"x\")", "category": "Other", "price": -0.5}]},
    {"id": "r2", "purchased_on": "2026-11-01", "store": "Aldi", "total": None, "uploaded_by": "Dad",
     "created_at": "2026-11-01T12:00:00Z", "updated_by": "Bibi", "updated_at": "2026-11-02T09:00:00Z", "items": []},
]


SCHEMA = {"has_quantity": True, "has_paid_by": True}  # flip to simulate a database whose schema.sql wasn't re-run yet


@pytest.fixture
def supabase():
    log = []
    SCHEMA.update(has_quantity=True, has_paid_by=True)

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
            if u.path == "/rest/v1/items" and self.command == "GET":  # the quantity-column check
                return self._send([]) if SCHEMA["has_quantity"] else self._send({"message": "column items.quantity does not exist"}, 400)
            if u.path == "/rest/v1/item_lines":
                return self._send([LINE] * (1000 if q.get("offset") == ["0"] else 2))
            if u.path == "/rest/v1/receipts" and self.command == "GET":
                if q.get("select") == ["paid_by"] and not SCHEMA["has_paid_by"]:  # the paid_by-column check
                    return self._send({"message": "column receipts.paid_by does not exist"}, 400)
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
    db._has_column.clear()
    for f in (db.load_item_lines, db.load_receipts, db.find_duplicates):
        f.clear()
    with mock.patch.object(type(st.secrets), "__getitem__", lambda self, k: secrets[k]):
        yield log
    server.shutdown()
    db.client.clear()
    db._has_column.clear()


def test_load_item_lines_pages_past_1000_rows(supabase):
    df = db.load_item_lines()
    pages = [q for (_, path, q, _) in supabase if path == "/rest/v1/item_lines"]
    assert len(df) == 1002 and [p["offset"] for p in pages] == [["0"], ["1000"]]
    assert isinstance(df["purchased_on"].iloc[0], datetime.date) and df["price"].dtype.kind == "f"


def test_load_receipts_filters_month(supabase):
    db.load_receipts(datetime.date(2026, 11, 1), datetime.date(2026, 12, 1))
    q = next(q for (_, path, q, _) in supabase if path == "/rest/v1/receipts")
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
    assert rows[1][:7] == ["r1", "2026-11-01", "REWE Markt GmbH", "3.0", "Dad", "yes", "Bibi"], "paid by Dad, just for him, added by Bibi"
    assert rows[1][10:] == ["BUTTER", "Dairy", "2.0", "2"]
    assert rows[2][10] == "BRÖTCHEN"
    assert rows[3][10:] == ["'=HYPERLINK(\"x\")", "Other", "-0.5", "1"], "formula text escaped, negative price kept numeric"
    assert rows[4][:7] == ["r2", "2026-11-01", "Aldi", "", "Dad", "", "Dad"], "no paid_by: the uploader paid; shared by default"
    assert rows[4][8] == "Bibi" and rows[4][10:] == ["", "", "", ""]
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


def test_quantity_is_read_when_the_column_exists(supabase):
    df = db.load_item_lines()
    lines = [q for (_, path, q, _) in supabase if path == "/rest/v1/item_lines"]
    assert "quantity" in lines[0]["select"][0] and (df["quantity"] == 1.0).all()


def test_before_schema_update_quantity_defaults_to_one(supabase):
    SCHEMA["has_quantity"] = False
    df = db.load_item_lines()
    lines = [q for (_, path, q, _) in supabase if path == "/rest/v1/item_lines"]
    assert "quantity" not in lines[0]["select"][0], "doesn't ask for a column that isn't there yet"
    assert (df["quantity"] == 1.0).all()
    db.load_receipts(datetime.date(2026, 11, 1), datetime.date(2026, 12, 1))
    receipts_q = [q for (m, path, q, _) in supabase if path == "/rest/v1/receipts"][-1]
    assert "quantity" not in receipts_q["select"][0]


def test_paid_by_is_read_and_defaults_to_the_uploader(supabase):
    df = db.load_item_lines()
    lines = [q for (_, path, q, _) in supabase if path == "/rest/v1/item_lines"]
    assert "paid_by" in lines[0]["select"][0] and (df["paid_by"] == "Bibi").all(), "missing paid_by -> uploader"
    assert db.paid_by(RECEIPTS[0]) == "Dad" and db.paid_by(RECEIPTS[1]) == "Dad"


def test_before_schema_update_paid_by_is_not_requested(supabase):
    SCHEMA["has_paid_by"] = False
    df = db.load_item_lines()
    lines = [q for (_, path, q, _) in supabase if path == "/rest/v1/item_lines"]
    assert "paid_by" not in lines[0]["select"][0] and "quantity" in lines[0]["select"][0]
    assert (df["paid_by"] == df["uploaded_by"]).all()


def test_save_receipt_sends_paid_by(supabase):
    db.save_receipt({"purchased_on": datetime.date(2026, 11, 1), "store": "Lidl", "total": 1.0, "paid_by": "Dad"},
                    [], user="Bibi")
    assert json.loads(supabase[0][3])["p_receipt"]["paid_by"] == "Dad"


def test_personal_flag_defaults_to_shared_and_waits_for_the_column(supabase):
    df = db.load_item_lines()
    assert "personal" in [q for (_, path, q, _) in supabase if path == "/rest/v1/item_lines"][0]["select"][0]
    assert df["personal"].dtype == bool and not df["personal"].any(), "rows without it count as for the family"
    assert db.is_personal(RECEIPTS[0]) and not db.is_personal(RECEIPTS[1])
