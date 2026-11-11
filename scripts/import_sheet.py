"""One-off: copy the old Google Sheet's rows into Supabase.

Run from the repo root after creating the schema (supabase/schema.sql):

    pip install gspread google-auth
    python scripts/import_sheet.py            # dry run: prints what would be imported
    python scripts/import_sheet.py --commit   # writes to Supabase

Reads .streamlit/secrets.toml for gcp_service_account, SUPABASE_URL and SUPABASE_SERVICE_KEY.
Consecutive sheet rows with the same date, store and receipt total become one receipt
(scanned receipts were appended together). Imported receipts get uploaded_by = "sheet-import".

Safe to re-run: receipts that were already imported (same date, store, total and number of
items) are skipped, so an interrupted import can simply be started again.
"""
import argparse
import datetime
import itertools
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from supabase import create_client  # noqa: E402

from grocery.utils import canonical_store, normalize_category, parse_money  # noqa: E402

SHEET_URL = "https://docs.google.com/spreadsheets/d/1xTZYrQlT9lVTfv6IMMCSE5zViVq-O7PhYd4zFBX0scE/edit"
from grocery.config import IMPORT_USER  # noqa: E402,F401  (receipts imported here get this uploader)


def read_sheet(secrets):
    import gspread
    from google.oauth2.service_account import Credentials

    creds = Credentials.from_service_account_info(
        secrets["gcp_service_account"],
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ],
    )
    return gspread.authorize(creds).open_by_url(SHEET_URL).sheet1.get_all_values()


def parse_rows(values):
    rows = []
    for raw in values[1:]:
        # Old rows were sometimes shifted right; realign to the first non-empty cell.
        first = next((i for i, c in enumerate(raw) if c.strip()), None)
        if first is None:
            continue
        date_s, store, item, category, price, _week, _month, total = (c.strip() for c in (raw[first:] + [""] * 8)[:8])
        if item.lower() == "total" or date_s.lower() == "total":
            continue
        try:
            purchased_on = datetime.date.fromisoformat(date_s)
        except ValueError:
            print(f"  skipping row with bad date: {raw}")
            continue
        price_value, total_value = parse_money(price), parse_money(total) if total else None
        if price_value is None:
            print(f"  WARNING: unreadable price {price!r} for {item!r} on {date_s}; imported as 0.00, fix it in History")
        if total and total_value is None:
            print(f"  WARNING: unreadable receipt total {total!r} on {date_s}; imported without a total")
        rows.append(
            {
                "purchased_on": purchased_on,
                "store": canonical_store(store) or "Unknown Store",
                "total": total_value,
                "item": {"name": item or "Item", "category": normalize_category(category), "price": price_value or 0.0},
            }
        )
    return rows


def group_receipts(rows):
    key = lambda r: (r["purchased_on"], r["store"], r["total"])  # noqa: E731
    return [
        ({"purchased_on": k[0], "store": k[1], "total": k[2]}, [r["item"] for r in grp])
        for k, grp in itertools.groupby(rows, key=key)
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--commit", action="store_true", help="actually write to Supabase")
    args = parser.parse_args()

    secrets = tomllib.loads((ROOT / ".streamlit" / "secrets.toml").read_text())
    receipts = group_receipts(parse_rows(read_sheet(secrets)))
    n_items = sum(len(items) for _, items in receipts)
    for receipt, items in receipts:
        print(f"  {receipt['purchased_on']}  {receipt['store']:<25} total={receipt['total']}  items={len(items)}")
    print(f"\n{len(receipts)} receipts, {n_items} items")

    if not args.commit:
        print("Dry run. Re-run with --commit to import.")
        return

    sb = create_client(secrets["SUPABASE_URL"], secrets["SUPABASE_SERVICE_KEY"])
    already = {fingerprint(r) for r in existing_imports(sb)}
    imported = skipped = 0
    for receipt, items in receipts:
        if fingerprint({**receipt, "items": items}) in already:
            skipped += 1
            continue
        payload = {**receipt, "purchased_on": receipt["purchased_on"].isoformat()}
        sb.rpc("save_receipt", {"p_receipt": payload, "p_items": items, "p_user": IMPORT_USER, "p_id": None}).execute()
        imported += 1
    print(f"Imported {imported} receipts; skipped {skipped} already imported.")


def fingerprint(receipt):
    """What identifies an imported receipt: date, store, total and number of items."""
    total = None if receipt["total"] is None else round(float(receipt["total"]), 2)
    return (str(receipt["purchased_on"]), receipt["store"], total, len(receipt["items"]))


def existing_imports(sb):
    rows, start = [], 0
    while True:
        batch = (sb.table("receipts").select("purchased_on, store, total, items(id)").eq("uploaded_by", IMPORT_USER)
                 .order("id").range(start, start + 999).execute().data)
        rows.extend(batch)
        if len(batch) < 1000:
            return rows
        start += 1000


if __name__ == "__main__":
    main()
