-- ELEV8 Trading Journal: tables for syncing trades between devices.
-- Run once in Supabase: SQL Editor -> New query -> paste -> Run.
-- Row-level security makes every row readable and writable only by the account that owns it.

create table if not exists public.trades (
  user_id uuid not null default auth.uid() references auth.users on delete cascade,
  id text not null,
  data jsonb not null,
  updated_at timestamptz not null default now(),
  primary key (user_id, id)
);

create table if not exists public.journal_settings (
  user_id uuid primary key default auth.uid() references auth.users on delete cascade,
  data jsonb not null,
  updated_at timestamptz not null default now()
);

alter table public.trades enable row level security;
alter table public.journal_settings enable row level security;

drop policy if exists "Own trades" on public.trades;
create policy "Own trades" on public.trades
  for all to authenticated using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists "Own settings" on public.journal_settings;
create policy "Own settings" on public.journal_settings
  for all to authenticated using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- Newer Supabase projects don't expose new tables to the API automatically.
-- Signed-in users need these grants; the policies above still limit them to their own rows.
grant usage on schema public to authenticated;
grant select, insert, update, delete on public.trades to authenticated;
grant select, insert, update, delete on public.journal_settings to authenticated;

-- The weekly review email job (GitHub Action) reads with the secret service key.
-- Newer projects don't grant the service role access to new tables automatically.
grant usage on schema public to service_role;
grant select on public.trades to service_role;
grant select on public.journal_settings to service_role;

-- Payout certificates (Settings › Accounts › Payouts): a private storage bucket where each
-- user's files sit in a folder named after their user id, readable only by them.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('payout-certificates', 'payout-certificates', false, 10485760,
        array['image/png', 'image/jpeg', 'image/webp', 'image/gif', 'image/heic', 'image/heif', 'application/pdf'])
on conflict (id) do update set public = false, file_size_limit = excluded.file_size_limit, allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "Own payout certificates: read" on storage.objects;
create policy "Own payout certificates: read" on storage.objects for select to authenticated
  using (bucket_id = 'payout-certificates' and (storage.foldername(name))[1] = auth.uid()::text);
drop policy if exists "Own payout certificates: upload" on storage.objects;
create policy "Own payout certificates: upload" on storage.objects for insert to authenticated
  with check (bucket_id = 'payout-certificates' and (storage.foldername(name))[1] = auth.uid()::text);
drop policy if exists "Own payout certificates: replace" on storage.objects;
create policy "Own payout certificates: replace" on storage.objects for update to authenticated
  using (bucket_id = 'payout-certificates' and (storage.foldername(name))[1] = auth.uid()::text)
  with check (bucket_id = 'payout-certificates' and (storage.foldername(name))[1] = auth.uid()::text);
drop policy if exists "Own payout certificates: delete" on storage.objects;
create policy "Own payout certificates: delete" on storage.objects for delete to authenticated
  using (bucket_id = 'payout-certificates' and (storage.foldername(name))[1] = auth.uid()::text);
