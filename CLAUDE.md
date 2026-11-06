# CLAUDE.md

"Bibi's Grocery Tracker" is a Streamlit app for a family. Family members sign in by typing their name, upload a receipt, Gemini extracts and categorizes the items, and the uploader reviews and edits the result before saving it to Supabase. Dashboards show spending by month, and the history page lets anyone browse, edit or delete past receipts. The app is deployed on Streamlit Community Cloud; a QR code on the fridge links to it.

## Layout

- `app.py`: entry point. Sets page config, runs the sign-in gate (`require_family_member`), then `st.navigation` over `views/`.
- `views/`: one script per page. They are **not** in `pages/`, so Streamlit's automatic page discovery doesn't apply.
  - `upload.py`: step 1 is the photo (upload, then `photo_editor`) and "Read with Gemini", or manual entry. Step 2 is the review editor, then Save. The draft lives in `st.session_state["draft"]`. While a draft exists, the photo controls stay in a collapsed expander so the receipt can be read again.
  - `dashboard.py`: month picker, metrics compared with the previous month, breakdowns by category, week and family member, and a 12-month trend.
  - `history.py`: table of receipts for a month. Selecting a row opens the editor (save or delete).
  - `qr.py`: QR code for the fridge.
- `grocery/`: the package the pages import.
  - `config.py`: constants (`CATEGORIES`, `GEMINI_MODEL`, retry settings). Does not import Streamlit.
  - `utils.py`: pure helpers (`to_money`, `normalize_category`, month and week labels). Does not import Streamlit, so `scripts/` can use it.
  - `auth.py`: name-only sign-in. The typed name must match one in `st.secrets["FAMILY"]` (case-insensitive). The canonical name is stored in `st.session_state["user"]`; `current_user()` returns it.
  - `imaging.py`: pure PIL/numpy. EXIF fix, rotate and tilt, auto-detected crop box (Otsu threshold), and `prepare_for_gemini` (crop, grayscale, shrink so the short side is 700 px, JPEG q80).
  - `photo_editor.py`: the photo UI. ↺/↻ buttons, a tilt slider (±15°), a crop box (`streamlit-cropper`), and a preview of what Gemini will see. State lives in `st.session_state["photo"]`.
  - `extract.py`: Gemini call with a pydantic `response_schema` (categories are always a valid enum), low-token settings, the add-up check with one re-read, and capped busy-retries.
  - `db.py`: **the only module that talks to Supabase.** Reads are cached with `st.cache_data`; every write calls `_invalidate()`.
  - `ui.py`: shared widgets (`receipt_editor`, `month_picker`, `flash`, `euro`).
- `supabase/schema.sql`: tables, the `item_lines` view and the `save_receipt()` function. It is safe to re-run.
- `scripts/import_sheet.py`: one-off migration from the old Google Sheet. It is a dry run unless you pass `--commit`.

## Data model (Supabase Postgres)

- `receipts`: id, purchased_on, store, total (nullable), uploaded_by (family member's name), created_at, updated_by, updated_at.
- `items`: id, receipt_id → receipts (on delete cascade), name, category, price. Price may be negative for discounts.
- `item_lines` view: items joined with their receipt's date, store and uploader. The dashboard reads this.
- **All writes go through `save_receipt(p_receipt, p_items, p_user, p_id)`.** It creates the receipt, or updates it and replaces its items, in one transaction. Don't insert into the tables separately.
- Week and month are computed in Python from `purchased_on`, not stored. Weeks use the ISO year (`week_label`).
- **Receipt photos are never stored.** Gemini reads the cropped, shrunk JPEG, and the review step previews it from memory (`st.session_state["draft"]`). Only the extracted data and the uploader's name are saved. This was the owner's choice, to save space; don't add image storage back unless asked.

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

- **App flows:** `streamlit.testing.v1.AppTest` on `app.py`, with `grocery.db.*` patched to an in-memory fake. Set `at.secrets["FAMILY"]`, and set `at.session_state["user"]` to skip the sign-in form. To jump straight to the review step, put a `draft` into `at.session_state`. Change pages with `at.switch_page("views/...")`. Photos can be uploaded with `at.file_uploader[0].set_value((name, bytes, mime))`. The cropper is a custom component, so under AppTest it returns its default box.
- **Crop UI in a real browser:** Playwright with Chromium at phone size (390×844), against a copy of the app with fake secrets. AppTest can't exercise the custom component.
- **SQL:** `supabase/schema.sql` runs in PGlite (`@electric-sql/pglite`). Create the roles `anon`, `authenticated` and `service_role` first.
- Never test against the production Supabase project; it holds the family's live data.

## Gemini token use

Measured 2026-11-06 with gemini-3.8-flash on simulated phone photos of 25- and 40-item thermal receipts (sharp and blurry). Settings live in `config.py`; the reasoning is in the docstring of `extract.py`.

- **Thinking is the main cost.** At the default level, a 40-item receipt used ~9,000 hidden thinking tokens on top of a ~1,500-token answer. `GEMINI_THINKING_LEVEL = "LOW"` brings thinking to ~0, with the same accuracy and 2–8× faster reads. `MINIMAL` is rejected by this model.
- **Image detail:** `media_resolution` LOW costs ~550 input tokens per image, against ~800 at MEDIUM and ~1,350 at HIGH. LOW reads sharp photos perfectly but sometimes misreads blurry ones.
- **Add-up check:** if the items don't sum to the printed total (±€0.05), `extract_receipt` reads once more at MEDIUM and keeps whichever read is closer. In testing this check flagged every misread and never fired on a correct read.
- **Compact output:** the pydantic models use one-letter aliases (`n`, `c`, `p`, …), and names are copied as printed rather than expanded. The Python code still uses the full field names.
- **Result:** ~1,420 billed tokens and ~8 s for a 40-item receipt, against ~11,400 tokens and ~68 s before.
- **Pixel size doesn't change tokens.** Gemini billed the same at every size from 250 px to full resolution. The fixed shrink to `OCR_SHORT_SIDE = 700` px is only for upload speed and memory (everything was read correctly down to 250 px). The phone still uploads the full photo to the Streamlit server.
- `extract_receipt` returns `tokens`, and the upload page shows it once a read finishes.

## Conventions and gotchas

- `streamlit-cropper` (pinned 0.3.1) uses a fabric.js canvas. The first tap selects the box, and only then do the corner handles appear. A drag without a tap first moves the box instead of resizing it. The UI caption says so.
- The cropper reads its starting box only when created. `photo_editor` therefore keeps `crop_start` fixed for each cropper key; the key changes on rotate or tilt. Passing a new start box on every run could make it jump while being dragged.
- `st.columns` stacks on phones. Use `st.container(horizontal=True)` for button rows that should stay on one line.

- Streamlit reruns the whole page on every interaction. Keep network calls in cached functions in `db.py`.
- `st.data_editor` keeps edits only while its input data and key stay the same. To reset an editor, change its key (`draft_no`, `history_rev`).
- `CATEGORIES` feeds the Gemini schema, the prompt and the editor dropdowns. Changing it doesn't touch existing rows, because the database stores plain text.
- PostgREST returns at most 1000 rows per request; `db._fetch_all` pages through larger results.
- UI copy uses emoji and € formatting. Keep that style.
