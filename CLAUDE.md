# CLAUDE.md

"Bibi's Grocery Tracker" is a Streamlit app for a family. Family members sign in by typing their name, upload a receipt, Gemini extracts and categorizes the items, and the uploader reviews and edits the result before saving it to Supabase. Dashboards show spending by month, and the history page lets anyone browse, edit or delete past receipts. The app is deployed on Streamlit Community Cloud; a QR code on the fridge links to it.

## Layout

- `app.py`: entry point. Sets page config and runs the sign-in gate (`require_family_member`). Navigation is `st.navigation(position="hidden")` plus a row of `st.page_link`s and a 👤 popover (backup, sign out) at the top of every page; the mobile sidebar stayed open over the page after each navigation. It also sets `st.session_state["page_changed"]` so pages can restore state after a visit elsewhere.
- `views/`: one script per page. They are **not** in `pages/`, so Streamlit's automatic page discovery doesn't apply.
  - `upload.py`: two modes that are never on screen together. The **photo step** (upload, `photo_editor`, "Read with Gemini", or manual entry) and, once a draft exists, the **review step** (editor, Save). "📷 Change the crop or read again" sets `photo_open` to go back. The draft lives in `st.session_state["draft"]`. Don't put the cropper in a collapsed expander: it sizes itself to 0 px.
  - `dashboard.py`: month picker, metrics compared with the previous month, breakdowns by category, week and family member, and a 12-month trend.
  - `history.py`: table of receipts for a month. Selecting a row opens the editor (save or delete). The selection is remembered **by receipt id** (`history_selected`), the table key includes a hash of the listed ids, and Save/Delete buttons are keyed by id. Other family members add and delete receipts concurrently, and a row index can silently point at a different receipt.
  - `qr.py`: QR code for the fridge.
- `grocery/`: the package the pages import.
  - `config.py`: constants (`CATEGORIES`, `GEMINI_MODEL`, retry settings). Does not import Streamlit.
  - `utils.py`: pure helpers (`to_money`, `normalize_category`, month and week labels). Does not import Streamlit, so `scripts/` can use it.
  - `auth.py`: sign-in. The typed name must match one in `st.secrets["FAMILY"]` (case-insensitive), and the shared `FAMILY_CODE` must match (case and surrounding spaces ignored). The canonical name goes in `st.session_state["user"]` and a fingerprint of the code in `"code_fingerprint"`; `current_user()` returns the name.
  - `imaging.py`: pure PIL/numpy. EXIF fix, rotate and tilt, auto-detected crop box (Otsu threshold), and `prepare_for_gemini` (crop, grayscale, shrink so the short side is 700 px, JPEG q80).
  - `photo_editor.py`: the photo UI. ↺/↻ buttons, a tilt slider (±15°), a crop box (`streamlit-cropper`), and a preview of what Gemini will see. The photo and its adjustments live in `st.session_state["photo"]`, not in the file uploader, so they survive page switches and the review step; `sync_upload` loads new files and forgets the photo when it's removed with ✕. `remount()` makes the cropper restart from the last crop when it comes back on screen.
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
- Access control is entirely `grocery/auth.py`: a family member's name plus the shared `FAMILY_CODE`. Changing `FAMILY_CODE` signs everyone out on their next click, because the stored fingerprint no longer matches. Wrong attempts sleep 1 s, rising to 10 s with many failures across all sessions in the last 10 min (a slowdown, never a lockout). Sign out clears the whole session, so a half-finished receipt can't be saved under the next person's name. There are no per-person passwords and no OAuth: the owner chose this for convenience, so don't add them unless asked.
- Sign-in lasts for the browser session only, so a page reload asks again.
- Any new page must be routed through `app.py` so it stays behind the sign-in gate.

## Running locally

```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # fill in; gitignored
streamlit run app.py
```

Run `supabase/schema.sql` once in the Supabase SQL editor.

## Testing

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest                              # Python: unit + AppTest page flows (no network, no secrets)
cd tests/sql && npm ci && npm test  # SQL: supabase/schema.sql in PGlite (real Postgres in WASM)
```

GitHub Actions (`.github/workflows/tests.yml`) runs both on every push.

- `tests/helpers.make_app(user=...)` builds an `AppTest` with test secrets, and `user` skips sign-in. It always sets a dummy key: with no secrets at all, Streamlit falls back to reading the real `.streamlit/secrets.toml` from the working directory. It also sets `client.showErrorDetails` to full via `config.set_option`; the environment variable doesn't override the repo's `config.toml`.
- The `store` fixture (`tests/conftest.py`) replaces `grocery.db` with an in-memory fake. `tests/test_db.py` runs the real supabase client against a local fake HTTP server instead.
- `tests/receipts.py` renders synthetic thermal receipts and "phone photos". It falls back to Pillow's built-in font where DejaVu or Menlo is missing.
- AppTest tips: change pages with `at.switch_page("views/...")`; upload with `at.file_uploader[0].set_value((name, bytes, mime))`; to jump to the review step, put a `draft` in `at.session_state`. The cropper is a custom component, so under AppTest it returns its default box.
- `tests/sql/schema_v1.sql` is the first released schema. The SQL test upgrades from it to check that re-running `schema.sql` on an existing database works.
- The crop box and the backup download were checked by hand-run Playwright scripts (Chromium at phone size, against a copy of the app with fake secrets and a fake Supabase). They are not part of CI.
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

## Duplicates and backups

- `utils.looks_like_duplicate`: a saved receipt from the same date counts as a duplicate if it has the same total, whatever the store is called (Gemini spells stores inconsistently). Without a total on either side, it falls back to a loose store-name match (`same_store`: same first significant word, or ≥0.8 similarity). The upload page only warns; it never blocks saving.
- The 👤 menu's "Download backup (CSV)" calls `db.export_csv` only when clicked (Streamlit runs the callable on a background thread). It writes one row per item with the receipt's fields repeated, in UTF-8 with a BOM so Excel shows umlauts correctly. Text cells starting with `= + - @` are prefixed with `'` so Excel can't run them as formulas.

## Robustness rules (each fixed a real bug; keep them)

- **Dates:** use `utils.today()` (time zone `config.TIMEZONE`). The Streamlit Cloud server runs on UTC, so `datetime.date.today()` is yesterday between midnight and 1–2 a.m. in Germany.
- **Off-screen widget state:** Streamlit drops it, so forms keep their values in session state. `ui.receipt_editor(key, values)` updates `values` in place and restores from it. `date_input`, `text_input` and `number_input` keep their identity by key, so passing the latest value is safe. The `data_editor` resets when its input changes, so its input is pinned in `<key>_items_base` and refreshed only when the editor is created anew.
- **Refunds:** totals and prices can be negative. Don't put `min_value=0` on them; it crashed the form.
- **Database errors:** reads go through `ui.database_errors(...)`, which shows a friendly message and stops. Writes catch exceptions and keep the user's input. The duplicate check may fail silently, because a warning-only check must never block Save. `db.save_receipt` and `db.delete_receipt` invalidate caches in a `finally` block, since a save can succeed even when its reply is lost.
- **Unexpected errors:** `.streamlit/config.toml` sets `showErrorDetails = "none"`, so users see a generic message; details go to the Streamlit Cloud logs.
- **Gemini retries:** decided only by `APIError.code` (408, 429, 5xx) or network errors, never by text in the message. If the detailed re-read fails, the first read is kept.
- **Images:** `imaging.load_photo` puts transparency onto white, rescales 16-bit images, rejects tiny or garbage files with `UnusableImage`, and decodes huge JPEGs at reduced size. `imaging.clamp_box` keeps crop boxes inside the picture.
- **Money text:** `utils.parse_money` handles `1.234,56`, `1,234.56`, `EUR 2,50` and the Unicode minus, and returns None when it can't read the value. The import script reports unreadable cells and can be re-run safely, because it skips receipts already imported.

## Logo and profile photos

- `assets/logo.png` (`config.LOGO`): a cartoon of the family (512 px), shown on the sign-in page and in the header via `st.logo`. `assets/favicon.png` (`config.FAVICON`) is a round crop of cartoon Bibi for the browser tab. The originals (`logo.jpeg` photo, `logo-cartoon-original.png`) are gitignored; only cartoon images are committed because the repo is public.
- Profile photos: `assets/avatars/<lower-case name>.png`, e.g. `shiqing.png` and `charif.png` (cartoon crops of the logo). `ui.avatar(name)` finds them, ignoring case, and returns None, meaning 👤, for anyone without one. They appear in the top row, the 👤 menu, and the dashboard's "By family member" table (`ui.avatar_data_uri` for `ImageColumn`). To add someone, save a round 192 px PNG under their name.

## Conventions and gotchas

- `streamlit-cropper` (pinned 0.3.1) uses a fabric.js canvas. The first tap selects the box, and only then do the corner handles appear. A drag without a tap first moves the box instead of resizing it. The UI caption says so.
- The cropper reads its starting box only when created. `photo_editor` therefore keeps `crop_start` fixed for each cropper key; the key changes on rotate or tilt. Passing a new start box on every run could make it jump while being dragged.
- `st.columns` stacks on phones. Use `st.container(horizontal=True)` for button rows that should stay on one line.

- Streamlit reruns the whole page on every interaction. Keep network calls in cached functions in `db.py`.
- `st.data_editor` keeps edits only while its input data and key stay the same. To reset an editor, change its key (`draft_no`, `history_rev`).
- `CATEGORIES` feeds the Gemini schema, the prompt and the editor dropdowns. Changing it doesn't touch existing rows, because the database stores plain text.
- PostgREST returns at most 1000 rows per request; `db._fetch_all` pages through larger results.
- UI copy uses emoji and € formatting. Keep that style.
