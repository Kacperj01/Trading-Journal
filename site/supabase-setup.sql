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
