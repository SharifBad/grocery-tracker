"""Shared fixtures. Tests never touch the real Supabase project or Gemini."""
import datetime
import sys
import uuid
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture
def store(monkeypatch):
    """In-memory stand-in for grocery.db. Returns the dict of saved receipts (id -> receipt)."""
    from grocery import db
    from grocery.utils import looks_like_duplicate

    receipts = {}

    def save_receipt(receipt, items, user, receipt_id=None):
        assert set(receipt) == {"purchased_on", "store", "total"}, receipt
        rid = receipt_id or str(uuid.uuid4())
        old = receipts.get(rid, {"uploaded_by": user, "created_at": f"{len(receipts):04d}"})
        receipts[rid] = {
            **old, "id": rid, "purchased_on": receipt["purchased_on"].isoformat(),
            "store": receipt["store"] or "Unknown Store", "total": receipt["total"],
            "items": [dict(i, id=str(uuid.uuid4())) for i in items],
            "updated_by": user if receipt_id else None,
        }
        return rid

    def load_item_lines():
        rows = [
            {"item_id": i["id"], "receipt_id": r["id"], "purchased_on": datetime.date.fromisoformat(r["purchased_on"]),
             "store": r["store"], "uploaded_by": r["uploaded_by"], **{k: i[k] for k in ("name", "category", "price")}}
            for r in receipts.values() for i in r["items"]
        ]
        return pd.DataFrame(rows, columns=db.ITEM_COLUMNS)

    def load_receipts(start, end):
        found = [r for r in receipts.values() if start.isoformat() <= r["purchased_on"] < end.isoformat()]
        return sorted(found, key=lambda r: (r["purchased_on"], r["created_at"]), reverse=True)

    def find_duplicates(purchased_on, store, total):
        return [r for r in receipts.values()
                if r["purchased_on"] == purchased_on.isoformat() and looks_like_duplicate(r, store, total)]

    monkeypatch.setattr(db, "save_receipt", save_receipt)
    monkeypatch.setattr(db, "load_item_lines", load_item_lines)
    monkeypatch.setattr(db, "load_receipts", load_receipts)
    monkeypatch.setattr(db, "find_duplicates", find_duplicates)
    monkeypatch.setattr(db, "delete_receipt", lambda rid: receipts.pop(rid))
    monkeypatch.setattr(db, "export_csv", lambda: b"receipt_id\n")

    memory = {}
    monkeypatch.setattr(db, "load_category_memory", lambda: dict(memory))
    monkeypatch.setattr(db, "remember_categories", lambda corrections, user: memory.update(corrections))
    receipts_fixture_extras.update(memory=memory)
    return receipts


receipts_fixture_extras = {}  # the store fixture's category memory, for tests to inspect
