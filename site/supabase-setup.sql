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

-- Notifications (Settings › Profile › Notifications). Each device that turns them on is stored in
-- push_subscriptions. Nobody can read or change these tables through the app: the app goes through
-- the three functions below, and the notification jobs (GitHub Actions) use the secret service key.
create table if not exists public.push_subscriptions (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users on delete cascade,
  endpoint text not null unique,
  p256dh text not null,
  auth text not null,
  created_at timestamptz not null default now()
);
-- The key pair notifications are signed with. The first notification job makes it; the private half
-- stays here and in the jobs, never in the app or the repo.
create table if not exists public.push_keys (
  id int primary key default 1 check (id = 1),
  public_key text not null,
  private_key text not null,
  created_at timestamptz not null default now()
);
-- News alerts already sent, so each one goes out once.
create table if not exists public.push_log (
  key text primary key,
  sent_at timestamptz not null default now()
);
alter table public.push_subscriptions enable row level security;
alter table public.push_keys enable row level security;
alter table public.push_log enable row level security;
revoke all on public.push_subscriptions, public.push_keys, public.push_log from anon, authenticated;
grant select, delete on public.push_subscriptions to service_role;
grant select, insert on public.push_keys to service_role;
grant select, insert, delete on public.push_log to service_role;

-- The public half of the key, which the app needs to turn notifications on.
create or replace function public.push_public_key() returns text
language sql stable security definer set search_path = '' as $$
  select public_key from public.push_keys where id = 1
$$;
-- Turn notifications on for this device. A device belongs to whoever signed in on it last, and each
-- account keeps its 10 most recent devices.
create or replace function public.push_subscribe(p_endpoint text, p_p256dh text, p_auth text)
returns boolean language plpgsql security definer set search_path = '' as $$
declare uid uuid := auth.uid();
begin
  if uid is null then raise exception 'Not signed in'; end if;
  if p_endpoint !~ '^https://' or length(p_endpoint) > 1000 or length(p_p256dh) not between 20 and 200
     or length(p_auth) not between 8 and 100 then
    raise exception 'This device gave an address notifications can''t be sent to.';
  end if;
  delete from public.push_subscriptions where endpoint = p_endpoint;
  delete from public.push_subscriptions where id in (
    select id from public.push_subscriptions where user_id = uid order by created_at desc offset 9);
  insert into public.push_subscriptions (user_id, endpoint, p256dh, auth) values (uid, p_endpoint, p_p256dh, p_auth);
  return true;
end $$;
-- Turn them off for this device (also done when signing out).
create or replace function public.push_unsubscribe(p_endpoint text)
returns boolean language plpgsql security definer set search_path = '' as $$
begin
  if auth.uid() is null then raise exception 'Not signed in'; end if;
  delete from public.push_subscriptions where endpoint = p_endpoint and user_id = auth.uid();
  return true;
end $$;
revoke all on function public.push_public_key() from public, anon;
revoke all on function public.push_subscribe(text, text, text) from public, anon;
revoke all on function public.push_unsubscribe(text) from public, anon;
grant execute on function public.push_public_key() to authenticated;
grant execute on function public.push_subscribe(text, text, text) to authenticated;
grant execute on function public.push_unsubscribe(text) to authenticated;

-- Bug report emails: every new report is emailed to this address by the news-alerts GitHub Action
-- (site/bug_alerts.py). The address is kept here in Supabase rather than in the public repo; change
-- 'you@example.com' to yours. Only the secret service key can read this table.
create table if not exists public.app_config (key text primary key, value text not null);
alter table public.app_config enable row level security;
revoke all on public.app_config from anon, authenticated;
grant select on public.app_config to service_role;
grant select on public.bug_reports to service_role;
insert into public.app_config (key, value) values ('bug_report_email', 'you@example.com')
  on conflict (key) do update set value = excluded.value;
