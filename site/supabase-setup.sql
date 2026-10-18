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

-- Bug reports (sidebar › Report a bug). Only signed-in accounts can send one (so nobody can flood them),
-- and nobody can read them through the app. Read them in Table Editor › bug_reports.
create table if not exists public.bug_reports (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  user_id uuid default auth.uid() references auth.users on delete set null,
  title text not null check (char_length(title) between 1 and 200),
  body text not null check (char_length(body) between 1 and 8000),
  status text not null default 'new'
);
alter table public.bug_reports enable row level security;
drop policy if exists "Anyone can send a bug report" on public.bug_reports;
drop policy if exists "Signed-in users can send a bug report" on public.bug_reports;
create policy "Signed-in users can send a bug report" on public.bug_reports
  for insert to authenticated with check (user_id = auth.uid());
revoke insert on public.bug_reports from anon;
grant usage on schema public to authenticated;
grant insert (title, body) on public.bug_reports to authenticated;

-- Delete my account (Settings › Account › Delete account). Deletes the signed-in person's trades,
-- settings, bug reports and login. Their screenshots and payout certificates are removed by the app
-- through the Storage API first (Supabase doesn't allow deleting storage files from SQL).
-- Called with really = false it only checks the function exists, so the app can stop before
-- removing any files if this hasn't been set up yet.
create or replace function public.delete_my_account(really boolean default false)
returns boolean language plpgsql security definer set search_path = '' as $$
declare uid uuid := auth.uid();
begin
  if uid is null then raise exception 'Not signed in'; end if;
  if not really then return false; end if;
  delete from public.trades where user_id = uid;
  delete from public.journal_settings where user_id = uid;
  delete from public.bug_reports where user_id = uid;
  delete from auth.users where id = uid;
  return true;
end $$;
revoke all on function public.delete_my_account(boolean) from public, anon;
grant execute on function public.delete_my_account(boolean) to authenticated;

-- Spam protection for bug reports: at most 20 reports from everyone in any 10 minutes, and 5 an
-- hour from any one signed-in account. The message is shown to the person in the app.
create or replace function public.bug_report_limit() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  if (select count(*) from public.bug_reports where created_at > now() - interval '10 minutes') >= 20 then
    raise exception 'Too many bug reports are arriving right now. Please try again in a few minutes.';
  end if;
  if new.user_id is not null and (select count(*) from public.bug_reports
      where user_id = new.user_id and created_at > now() - interval '1 hour') >= 5 then
    raise exception 'You''ve sent several reports in the last hour. Please try again later.';
  end if;
  return new;
end $$;
drop trigger if exists bug_report_limit on public.bug_reports;
create trigger bug_report_limit before insert on public.bug_reports
  for each row execute function public.bug_report_limit();
