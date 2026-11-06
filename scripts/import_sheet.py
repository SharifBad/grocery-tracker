"""One-off: copy the old Google Sheet's rows into Supabase.

Run from the repo root after creating the schema (supabase/schema.sql):

    pip install gspread google-auth
    python scripts/import_sheet.py            # dry run: prints what would be imported
    python scripts/import_sheet.py --commit   # writes to Supabase

Reads .streamlit/secrets.toml for gcp_service_account, SUPABASE_URL and SUPABASE_SERVICE_KEY.
Consecutive sheet rows with the same date, store and receipt total become one receipt
(scanned receipts were appended together). Imported receipts get uploaded_by = "sheet-import".
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

from grocery.utils import normalize_category, to_money  # noqa: E402

SHEET_URL = "https://docs.google.com/spreadsheets/d/1xTZYrQlT9lVTfv6IMMCSE5zViVq-O7PhYd4zFBX0scE/edit"
IMPORT_USER = "sheet-import"


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
        rows.append(
            {
                "purchased_on": purchased_on,
                "store": store or "Unknown Store",
                "total": to_money(total) if total else None,
                "item": {"name": item or "Item", "category": normalize_category(category), "price": to_money(price)},
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
    existing = sb.table("receipts").select("id", count="exact").eq("uploaded_by", IMPORT_USER).limit(1).execute()
    if existing.count:
        sys.exit(f"Aborting: {existing.count} receipts from a previous import already exist.")

    for receipt, items in receipts:
        payload = {**receipt, "purchased_on": receipt["purchased_on"].isoformat()}
        sb.rpc("save_receipt", {"p_receipt": payload, "p_items": items, "p_user": IMPORT_USER, "p_id": None}).execute()
    print("Imported.")


if __name__ == "__main__":
    main()
