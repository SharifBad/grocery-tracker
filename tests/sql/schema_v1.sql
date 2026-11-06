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
  image_path   text,                          -- object path in the 'receipts' storage bucket
  created_at   timestamptz not null default now(),
  updated_by   text,
  updated_at   timestamptz
);

create table if not exists items (
  id         uuid primary key default gen_random_uuid(),
  receipt_id uuid not null references receipts(id) on delete cascade,
  name       text not null,
  category   text not null default 'Other',
  price      numeric(10,2) not null           -- may be negative for discounts
);

create index if not exists receipts_purchased_on_idx on receipts (purchased_on);
create index if not exists items_receipt_id_idx on items (receipt_id);

alter table receipts enable row level security;
alter table items enable row level security;

-- One row per item with its receipt's date/store/uploader: what the dashboard reads.
create or replace view item_lines with (security_invoker = true) as
select i.id as item_id, i.receipt_id, r.purchased_on, r.store, r.uploaded_by,
       i.name, i.category, i.price
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
    insert into receipts (purchased_on, store, total, uploaded_by, image_path)
    values (
      (p_receipt->>'purchased_on')::date,
      coalesce(nullif(trim(p_receipt->>'store'), ''), 'Unknown Store'),
      (p_receipt->>'total')::numeric,
      p_user,
      p_receipt->>'image_path'
    )
    returning id into rid;
  else
    update receipts set
      purchased_on = (p_receipt->>'purchased_on')::date,
      store        = coalesce(nullif(trim(p_receipt->>'store'), ''), 'Unknown Store'),
      total        = (p_receipt->>'total')::numeric,
      updated_by   = p_user,
      updated_at   = now()
    where id = p_id
    returning id into rid;

    if rid is null then
      raise exception 'receipt % not found', p_id;
    end if;

    delete from items where receipt_id = rid;
  end if;

  insert into items (receipt_id, name, category, price)
  select rid,
         coalesce(nullif(trim(i->>'name'), ''), 'Item'),
         coalesce(nullif(trim(i->>'category'), ''), 'Other'),
         coalesce((i->>'price')::numeric, 0)
  from jsonb_array_elements(p_items) as i;

  return rid;
end;
$$;

-- Only the server (service_role) may call it; anon/authenticated get it by default otherwise.
revoke execute on function save_receipt(jsonb, jsonb, text, uuid) from public, anon, authenticated;
grant execute on function save_receipt(jsonb, jsonb, text, uuid) to service_role;

-- Private bucket for receipt photos/PDFs.
insert into storage.buckets (id, name, public)
values ('receipts', 'receipts', false)
on conflict (id) do nothing;
