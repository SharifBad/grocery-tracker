// Runs supabase/schema.sql in PGlite (real Postgres in WebAssembly). Usage: npm test (in tests/sql).
import { PGlite } from "@electric-sql/pglite";
import { readFileSync } from "node:fs";

const read = (rel) => readFileSync(new URL(rel, import.meta.url), "utf8");
const schema = read("../../supabase/schema.sql");
const schemaV1 = read("./schema_v1.sql"); // first released schema (had receipts.image_path + a storage bucket)

let failures = 0;
const ok = (cond, msg) => {
  console.log(`${cond ? "ok  " : "FAIL"} - ${msg}`);
  if (!cond) failures++;
};

const db = new PGlite();
// Stand-ins for what Supabase provides.
await db.exec(`
  create role anon; create role authenticated; create role service_role;
  create schema storage;
  create table storage.buckets (id text primary key, name text, public boolean);
`);

// Upgrade path: a database created with v1, then the current schema (twice: must be re-runnable).
await db.exec(schemaV1);
await db.query("insert into receipts (purchased_on, store, uploaded_by, image_path) values ('2026-01-01','Old','x','a/b.png')");
await db.exec(schema);
await db.exec(schema);
const cols = (await db.query("select column_name from information_schema.columns where table_name='receipts'")).rows.map((r) => r.column_name);
ok(!cols.includes("image_path"), "upgrade drops receipts.image_path");
ok((await db.query("select count(*)::int n from receipts where store='Old'")).rows[0].n === 1, "upgrade keeps existing receipts");
await db.query("delete from receipts");

const save = async (receipt, items, user, id = null) =>
  (await db.query("select save_receipt($1::jsonb, $2::jsonb, $3, $4) as id",
    [JSON.stringify(receipt), JSON.stringify(items), user, id])).rows[0].id;
const receipt = async (id) => (await db.query("select * from receipts where id=$1", [id])).rows[0];
const items = async (id) => (await db.query("select name, category, price from items where receipt_id=$1 order by name", [id])).rows;

const rid = await save(
  { purchased_on: "2026-11-01", store: " Lidl ", total: 5.49 },
  [{ name: "Milk", category: "Dairy", price: 1.99 }, { name: "", category: "", price: null }, { name: "Discount", category: "Other", price: -0.5 }],
  "Bibi");
let r = await receipt(rid);
ok(r.store === "Lidl" && r.total === "5.49" && r.uploaded_by === "Bibi", "insert trims store, keeps total and uploader");
let its = await items(rid);
ok(its.length === 3 && its.some((i) => i.name === "Item" && i.category === "Other" && i.price === "0.00") && its.some((i) => i.price === "-0.50"),
  "blank item gets defaults; negative discount allowed");

r = await receipt(await save({ purchased_on: "2026-10-31", store: "", total: null }, [], "Dad"));
ok(r.store === "Unknown Store" && r.total === null, "blank store and null total");

await save({ purchased_on: "2026-11-02", store: "Aldi", total: 3 }, [{ name: "Bread", category: "Bakery", price: 3 }], "Dad", rid);
r = await receipt(rid);
its = await items(rid);
ok(r.store === "Aldi" && r.uploaded_by === "Bibi" && r.updated_by === "Dad" && r.updated_at && its.length === 1 && its[0].name === "Bread",
  "update replaces items, keeps uploader, records editor");

let failed = false;
try { await save({ purchased_on: "2026-11-02", store: "Z", total: 1 }, [], "a", "00000000-0000-0000-0000-000000000000"); } catch { failed = true; }
ok(failed, "updating an unknown receipt raises");

const before = (await db.query("select count(*)::int n from receipts")).rows[0].n;
failed = false;
try { await save({ purchased_on: "2026-11-03", store: "Q", total: 1 }, [{ name: "x", category: "Other", price: "abc" }], "a"); } catch { failed = true; }
ok(failed && (await db.query("select count(*)::int n from receipts")).rows[0].n === before, "a bad item rolls back the whole receipt");

const lines = (await db.query("select * from item_lines where receipt_id=$1", [rid])).rows;
ok(lines.length === 1 && lines[0].store === "Aldi" && lines[0].uploaded_by === "Bibi", "item_lines view joins receipt fields");

await db.query("delete from receipts where id=$1", [rid]);
ok((await items(rid)).length === 0, "deleting a receipt deletes its items");

const priv = (await db.query(`select
  has_function_privilege('anon', 'save_receipt(jsonb,jsonb,text,uuid)', 'execute') a,
  has_function_privilege('authenticated', 'save_receipt(jsonb,jsonb,text,uuid)', 'execute') b,
  has_function_privilege('service_role', 'save_receipt(jsonb,jsonb,text,uuid)', 'execute') c,
  has_table_privilege('anon', 'item_lines', 'select') d,
  (select relrowsecurity from pg_class where relname='receipts') e,
  (select relrowsecurity from pg_class where relname='items') f`)).rows[0];
ok(!priv.a && !priv.b && priv.c && !priv.d && priv.e && priv.f, "only service_role can call save_receipt; RLS on; anon can't read the view");

// category memory + budgets
await db.query("insert into category_memory (name_key, category, updated_by) values ('haferfl zart', 'Pantry', 'Bibi') on conflict (name_key) do update set category = excluded.category");
await db.query("insert into category_memory (name_key, category, updated_by) values ('haferfl zart', 'Bakery', 'Dad') on conflict (name_key) do update set category = excluded.category");
ok((await db.query("select category from category_memory where name_key='haferfl zart'")).rows[0].category === "Bakery", "category memory upserts by item name");
await db.query("insert into budgets (category, amount) values ('TOTAL', 450), ('Snacks & Sweets', 40)");
failed = false;
try { await db.query("insert into budgets (category, amount) values ('Drinks', -5)"); } catch { failed = true; }
ok(failed, "negative budget rejected");
const priv2 = (await db.query(`select has_table_privilege('anon', 'category_memory', 'select') a, has_table_privilege('anon', 'budgets', 'insert') b,
  (select relrowsecurity from pg_class where relname='budgets') c, (select relrowsecurity from pg_class where relname='category_memory') d`)).rows[0];
ok(!priv2.a && !priv2.b && priv2.c && priv2.d, "new tables locked down like the others");

console.log(failures ? `\n${failures} FAILED` : "\nall SQL tests passed");
process.exit(failures ? 1 : 0);
