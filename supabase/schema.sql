-- Grocery Tracker schema. Run once in the Supabase SQL editor (safe to re-run).
--
-- Access model: the Streamlit server talks to Supabase with the service_role key and does its
-- own sign-in check (family member names in the app's secrets). RLS is enabled with NO policies, so the
-- public anon key can read or write nothing.

create table if not exists receipts (
  id           uuid primary key default gen_random_uuid(),
  purchased_on date        not null,
  store        text        not null default 'Unknown Store',
  total        numeric(10,2),                 -- amount paid per the receipt; null if unknown
  uploaded_by  text        not null,          -- name of the family member who added it
  created_at   timestamptz not null default now(),
  updated_by   text,
  updated_at   timestamptz
);

-- Receipt photos are not stored. Drops the column from databases created by an older version.
alter table receipts drop column if exists image_path;

create table if not exists items (
  id         uuid primary key default gen_random_uuid(),
  receipt_id uuid not null references receipts(id) on delete cascade,
  name       text not null,
  category   text not null default 'Other',
  price      numeric(10,2) not null           -- may be negative for discounts
);

-- How many were bought on that line (pieces, or kg for weighed items); price is the line total.
alter table items add column if not exists quantity numeric(10,3) not null default 1 check (quantity > 0);

-- Who paid (a family member's name). Usually the uploader, but one can log a receipt for someone else.
alter table receipts add column if not exists paid_by text;
update receipts set paid_by = uploaded_by where paid_by is null;

-- Bought just for the payer themselves (not for the family). Shown per person on the dashboard.
alter table receipts add column if not exists personal boolean not null default false;

create index if not exists receipts_purchased_on_idx on receipts (purchased_on);
create index if not exists items_receipt_id_idx on items (receipt_id);

alter table receipts enable row level security;
alter table items enable row level security;

-- Category corrections, remembered per item name (as normalised by utils.item_key) and applied
-- automatically the next time that item is read.
create table if not exists category_memory (
  name_key   text primary key,
  category   text not null,
  updated_by text,
  updated_at timestamptz not null default now()
);

-- Monthly budgets. category = 'TOTAL' is the overall budget; 0 means no budget.
create table if not exists budgets (
  category   text primary key,
  amount     numeric(10,2) not null check (amount >= 0),
  updated_by text,
  updated_at timestamptz not null default now()
);

alter table category_memory enable row level security;
alter table budgets enable row level security;
revoke all on category_memory, budgets from anon, authenticated;

-- One row per item with its receipt's date/store/uploader/payer: what the dashboard reads.
-- New columns go at the end: "create or replace view" can only append.
create or replace view item_lines with (security_invoker = true) as
select i.id as item_id, i.receipt_id, r.purchased_on, r.store, r.uploaded_by,
       i.name, i.category, i.price, i.quantity, coalesce(r.paid_by, r.uploaded_by) as paid_by, r.personal
from items i
join receipts r on r.id = i.receipt_id;

revoke all on item_lines from anon, authenticated;

-- Create (p_id null) or update (p_id set) a receipt and replace its items, atomically.
create or replace function save_receipt(p_receipt jsonb, p_items jsonb, p_user text, p_id uuid default null)
returns uuid
language plpgsql
set search_path = public
as $$
declare
  rid uuid;
begin
  if p_id is null then
    insert into receipts (purchased_on, store, total, uploaded_by, paid_by, personal)
    values (
      (p_receipt->>'purchased_on')::date,
      coalesce(nullif(trim(p_receipt->>'store'), ''), 'Unknown Store'),
      (p_receipt->>'total')::numeric,
      p_user,
      coalesce(nullif(trim(p_receipt->>'paid_by'), ''), p_user),  -- default: whoever adds it paid
      coalesce((p_receipt->>'personal')::boolean, false)
    )
    returning id into rid;
  else
    update receipts set
      purchased_on = (p_receipt->>'purchased_on')::date,
      store        = coalesce(nullif(trim(p_receipt->>'store'), ''), 'Unknown Store'),
      total        = (p_receipt->>'total')::numeric,
      paid_by      = coalesce(nullif(trim(p_receipt->>'paid_by'), ''), paid_by, uploaded_by),
      personal     = coalesce((p_receipt->>'personal')::boolean, personal),
      updated_by   = p_user,
      updated_at   = now()
    where id = p_id
    returning id into rid;

    if rid is null then
      raise exception 'receipt % not found', p_id;
    end if;

    delete from items where receipt_id = rid;
  end if;

  insert into items (receipt_id, name, category, price, quantity)
  select rid,
         coalesce(nullif(trim(i->>'name'), ''), 'Item'),
         coalesce(nullif(trim(i->>'category'), ''), 'Other'),
         coalesce((i->>'price')::numeric, 0),
         case when (i->>'quantity')::numeric > 0 then (i->>'quantity')::numeric else 1 end
  from jsonb_array_elements(p_items) as i;

  return rid;
end;
$$;

-- Only the server (service_role) may call it; anon/authenticated get it by default otherwise.
revoke execute on function save_receipt(jsonb, jsonb, text, uuid) from public, anon, authenticated;
grant execute on function save_receipt(jsonb, jsonb, text, uuid) to service_role;
