# CLAUDE.md

"Bibi's Grocery Tracker" is a Streamlit app for a family. Family members sign in by typing their name, upload a receipt, Gemini extracts and categorizes the items, and the uploader reviews and edits the result before saving it to Supabase. Dashboards show spending by month, and the history page lets anyone browse, edit or delete past receipts. The app is deployed on Streamlit Community Cloud; a QR code on the fridge links to it.

## Layout

- `app.py`: entry point. Sets page config, runs the sign-in gate (`require_family_member`), then `st.navigation` over `views/`.
- `views/`: one script per page. They are **not** in `pages/`, so Streamlit's automatic page discovery doesn't apply.
  - `upload.py`: step 1 uploads the receipt and runs Gemini, or starts manual entry. Step 2 is the review editor, then Save. The draft lives in `st.session_state["draft"]`.
  - `dashboard.py`: month picker, metrics compared with the previous month, breakdowns by category, week and family member, and a 12-month trend.
  - `history.py`: table of receipts for a month. Selecting a row opens the editor (save or delete).
  - `qr.py`: QR code for the fridge.
- `grocery/`: the package the pages import.
  - `config.py`: constants (`CATEGORIES`, `GEMINI_MODEL`, retry settings, bucket name). Does not import Streamlit.
  - `utils.py`: pure helpers (`to_money`, `normalize_category`, month and week labels). Does not import Streamlit, so `scripts/` can use it.
  - `auth.py`: name-only sign-in. The typed name must match one in `st.secrets["FAMILY"]` (case-insensitive). The canonical name is stored in `st.session_state["user"]`; `current_user()` returns it.
  - `extract.py`: Gemini call with a pydantic `response_schema`, so categories are always a valid enum. Retries are capped.
  - `db.py`: **the only module that talks to Supabase.** Reads are cached with `st.cache_data`; every write calls `_invalidate()`.
  - `ui.py`: shared widgets (`receipt_editor`, `month_picker`, `flash`, `euro`).
- `supabase/schema.sql`: tables, the `item_lines` view, the `save_receipt()` function and the storage bucket. It is safe to re-run.
- `scripts/import_sheet.py`: one-off migration from the old Google Sheet. It is a dry run unless you pass `--commit`.

## Data model (Supabase Postgres)

- `receipts`: id, purchased_on, store, total (nullable), uploaded_by (family member's name), image_path, created_at, updated_by, updated_at.
- `items`: id, receipt_id → receipts (on delete cascade), name, category, price. Price may be negative for discounts.
- `item_lines` view: items joined with their receipt's date, store and uploader. The dashboard reads this.
- **All writes go through `save_receipt(p_receipt, p_items, p_user, p_id)`.** It creates the receipt, or updates it and replaces its items, in one transaction. Don't insert into the tables separately.
- Week and month are computed in Python from `purchased_on`, not stored. Weeks use the ISO year (`week_label`).
- Receipt files are stored in the private `receipts` storage bucket at `YYYY/MM/<uuid>.<ext>`.

## Security model

- Streamlit connects with the Supabase **service_role** key, which never leaves the server. RLS is on with no policies, and anon/authenticated have their privileges revoked, so the public anon key can do nothing.
- Access control is entirely `grocery/auth.py`, and it is deliberately weak: there's **no password**, just a name that must be in `FAMILY`. Anyone with the URL who knows a family name can get in. The owner chose this for convenience. Don't add OAuth or passwords unless asked; a shared family code would be the smallest step up.
- Sign-in lasts for the browser session only, so a page reload asks for the name again.
- Any new page must be routed through `app.py` so it stays behind the sign-in gate.

## Running locally

```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # fill in; gitignored
streamlit run app.py
```

Run `supabase/schema.sql` once in the Supabase SQL editor.

## Testing

There is no test suite in the repo yet. What has worked so far:

- **App flows:** `streamlit.testing.v1.AppTest` on `app.py`, with `grocery.db.*` patched to an in-memory fake. Set `at.secrets["FAMILY"]`, and set `at.session_state["user"]` to skip the sign-in form. AppTest can't drive `file_uploader`, so to test the review step, put a `draft` straight into `at.session_state`. Change pages with `at.switch_page("views/...")`.
- **SQL:** `supabase/schema.sql` runs in PGlite (`@electric-sql/pglite`). Create the roles `anon`, `authenticated` and `service_role` and a stub `storage.buckets` table first.
- Never test against the production Supabase project; it holds the family's live data.

## Conventions and gotchas

- Streamlit reruns the whole page on every interaction. Keep network calls in cached functions in `db.py`.
- `st.data_editor` keeps edits only while its input data and key stay the same. To reset an editor, change its key (`draft_no`, `history_rev`).
- `CATEGORIES` feeds the Gemini schema, the prompt and the editor dropdowns. Changing it doesn't touch existing rows, because the database stores plain text.
- PostgREST returns at most 1000 rows per request; `db._fetch_all` pages through larger results.
- UI copy uses emoji and € formatting. Keep that style.
