-- StockWorth AI — initial schema
-- Run in the Supabase SQL editor (or `supabase db push`). Idempotent where practical.
--
-- Security model
--   * Every user-owned table has RLS enabled and policies restricted to auth.uid().
--   * The backend calls PostgREST with the end user's access token (anon key + user JWT),
--     so these policies are what actually protect the data. No service-role key is used.
--   * Sourced share prices live in stock_prices (002_stock_prices.sql).

create extension if not exists "pgcrypto";

-- If a different, pre-existing public.companies table is found (no owner_id column),
-- keep its data by renaming it instead of failing or dropping it.
do $$
begin
  if exists (select 1 from information_schema.tables where table_schema = 'public' and table_name = 'companies')
     and not exists (
       select 1 from information_schema.columns
       where table_schema = 'public' and table_name = 'companies' and column_name = 'owner_id'
     ) then
    if exists (select 1 from information_schema.tables where table_schema = 'public' and table_name = 'companies_legacy') then
      raise exception 'public.companies has an unexpected structure and public.companies_legacy already exists; resolve manually.';
    end if;
    alter table public.companies rename to companies_legacy;
    raise notice 'Existing public.companies renamed to public.companies_legacy (data kept).';
  end if;
end;
$$;

-- ---------------------------------------------------------------------------
-- profiles
-- ---------------------------------------------------------------------------
create table if not exists public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  display_name text check (char_length(display_name) <= 80),
  theme text not null default 'system' check (theme in ('light', 'dark', 'system')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.profiles enable row level security;

drop policy if exists "profiles_select_own" on public.profiles;
create policy "profiles_select_own" on public.profiles
  for select using (id = auth.uid());
drop policy if exists "profiles_insert_own" on public.profiles;
create policy "profiles_insert_own" on public.profiles
  for insert with check (id = auth.uid());
drop policy if exists "profiles_update_own" on public.profiles;
create policy "profiles_update_own" on public.profiles
  for update using (id = auth.uid()) with check (id = auth.uid());

-- Create a profile row automatically for new users.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id) values (new.id) on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ---------------------------------------------------------------------------
-- companies (user-owned, unverified metadata entered by the user)
-- ---------------------------------------------------------------------------
create table if not exists public.companies (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  ticker text not null check (ticker ~ '^[A-Z]{4}$'),
  name text not null check (char_length(name) between 2 and 160),
  sector text,
  is_verified boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (owner_id, ticker)
);

alter table public.companies enable row level security;

drop policy if exists "companies_all_own" on public.companies;
create policy "companies_all_own" on public.companies
  for all using (owner_id = auth.uid()) with check (owner_id = auth.uid());

-- ---------------------------------------------------------------------------
-- analyses
-- ---------------------------------------------------------------------------
create table if not exists public.analyses (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  company_id uuid not null references public.companies (id) on delete cascade,
  ticker text not null check (ticker ~ '^[A-Z]{4}$'),
  company_name text not null,
  sector text,
  fiscal_year int not null check (fiscal_year between 1990 and 2100),
  period text not null check (period in ('FY', 'Q1', 'Q2', 'Q3', 'Q4')),
  basis text not null check (basis in ('annual', 'quarterly', 'ytd')),
  period_label text not null,
  methodology_version text not null,
  fundamental_score numeric(5, 1) check (fundamental_score between 0 and 100),
  valuation_score numeric(5, 1) check (valuation_score between 0 and 100),
  completeness numeric(5, 1) check (completeness between 0 and 100),
  input jsonb not null,
  result jsonb not null,
  created_at timestamptz not null default now()
);

create index if not exists analyses_owner_created_idx on public.analyses (owner_id, created_at desc);
create index if not exists analyses_owner_ticker_idx on public.analyses (owner_id, ticker);

alter table public.analyses enable row level security;

drop policy if exists "analyses_select_own" on public.analyses;
create policy "analyses_select_own" on public.analyses
  for select using (owner_id = auth.uid());
drop policy if exists "analyses_insert_own" on public.analyses;
create policy "analyses_insert_own" on public.analyses
  for insert with check (
    owner_id = auth.uid()
    and exists (select 1 from public.companies c where c.id = company_id and c.owner_id = auth.uid())
  );
drop policy if exists "analyses_delete_own" on public.analyses;
create policy "analyses_delete_own" on public.analyses
  for delete using (owner_id = auth.uid());
-- No update policy: analyses are immutable snapshots tied to a methodology version.

-- ---------------------------------------------------------------------------
-- financial_statements (normalised period values, traceable to their source)
-- ---------------------------------------------------------------------------
create table if not exists public.financial_statements (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  analysis_id uuid not null references public.analyses (id) on delete cascade,
  company_id uuid not null references public.companies (id) on delete cascade,
  period_role text not null check (period_role in ('current', 'previous')),
  fiscal_year int not null check (fiscal_year between 1990 and 2100),
  period text not null check (period in ('FY', 'Q1', 'Q2', 'Q3', 'Q4')),
  basis text not null check (basis in ('annual', 'quarterly', 'ytd')),
  currency text not null check (currency in ('IDR', 'USD')),
  entered_unit text not null check (entered_unit in ('unit', 'ribu', 'juta', 'miliar')),
  -- values normalised to whole currency units (share counts unscaled)
  amounts jsonb not null,
  source jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (analysis_id, period_role)
);

create index if not exists fs_owner_company_idx on public.financial_statements (owner_id, company_id, fiscal_year);

alter table public.financial_statements enable row level security;

drop policy if exists "fs_select_own" on public.financial_statements;
create policy "fs_select_own" on public.financial_statements
  for select using (owner_id = auth.uid());
drop policy if exists "fs_insert_own" on public.financial_statements;
create policy "fs_insert_own" on public.financial_statements
  for insert with check (
    owner_id = auth.uid()
    and exists (select 1 from public.analyses a where a.id = analysis_id and a.owner_id = auth.uid())
  );
drop policy if exists "fs_delete_own" on public.financial_statements;
create policy "fs_delete_own" on public.financial_statements
  for delete using (owner_id = auth.uid());

-- ---------------------------------------------------------------------------
-- ai_insights (AI-generated or rule-based; the source column says which)
-- ---------------------------------------------------------------------------
create table if not exists public.ai_insights (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  analysis_id uuid not null references public.analyses (id) on delete cascade,
  source text not null check (source in ('ai', 'rule_based')),
  provider text,
  model text,
  fallback_reason text,
  content jsonb not null,
  created_at timestamptz not null default now(),
  check (source = 'rule_based' or (provider is not null and model is not null))
);

create index if not exists ai_insights_analysis_idx on public.ai_insights (analysis_id, created_at desc);

alter table public.ai_insights enable row level security;

drop policy if exists "ai_insights_select_own" on public.ai_insights;
create policy "ai_insights_select_own" on public.ai_insights
  for select using (owner_id = auth.uid());
drop policy if exists "ai_insights_insert_own" on public.ai_insights;
create policy "ai_insights_insert_own" on public.ai_insights
  for insert with check (
    owner_id = auth.uid()
    and exists (select 1 from public.analyses a where a.id = analysis_id and a.owner_id = auth.uid())
  );
drop policy if exists "ai_insights_delete_own" on public.ai_insights;
create policy "ai_insights_delete_own" on public.ai_insights
  for delete using (owner_id = auth.uid());

-- ---------------------------------------------------------------------------
-- updated_at maintenance
-- ---------------------------------------------------------------------------
create or replace function public.touch_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists profiles_touch on public.profiles;
create trigger profiles_touch before update on public.profiles
  for each row execute function public.touch_updated_at();
drop trigger if exists companies_touch on public.companies;
create trigger companies_touch before update on public.companies
  for each row execute function public.touch_updated_at();

-- ---------------------------------------------------------------------------
-- create_analysis: writes company + analysis + statements atomically.
-- SECURITY INVOKER, so all RLS policies above still apply to the caller.
-- ---------------------------------------------------------------------------
create or replace function public.create_analysis(payload jsonb)
returns uuid
language plpgsql
security invoker
set search_path = public
as $$
declare
  uid uuid := auth.uid();
  v_company_id uuid;
  v_analysis_id uuid;
  v_input jsonb := payload -> 'input';
  v_result jsonb := payload -> 'result';
  v_norm jsonb := v_result -> 'normalized';
begin
  if uid is null then
    raise exception 'not authenticated' using errcode = '28000';
  end if;

  insert into companies (owner_id, ticker, name, sector)
  values (uid, payload ->> 'ticker', payload ->> 'company_name', payload ->> 'sector')
  on conflict (owner_id, ticker)
    do update set name = excluded.name, sector = excluded.sector
  returning id into v_company_id;

  insert into analyses (
    owner_id, company_id, ticker, company_name, sector, fiscal_year, period, basis, period_label,
    methodology_version, fundamental_score, valuation_score, completeness, input, result
  ) values (
    uid, v_company_id, payload ->> 'ticker', payload ->> 'company_name', payload ->> 'sector',
    (payload ->> 'fiscal_year')::int, payload ->> 'period', payload ->> 'basis', payload ->> 'period_label',
    payload ->> 'methodology_version',
    nullif(v_result #>> '{fundamental_score,score}', '')::numeric,
    nullif(v_result #>> '{valuation_score,score}', '')::numeric,
    nullif(v_result #>> '{completeness,percent}', '')::numeric,
    v_input, v_result
  )
  returning id into v_analysis_id;

  insert into financial_statements (
    owner_id, analysis_id, company_id, period_role, fiscal_year, period, basis, currency, entered_unit, amounts, source
  ) values (
    uid, v_analysis_id, v_company_id, 'current',
    (payload ->> 'fiscal_year')::int, payload ->> 'period', payload ->> 'basis',
    v_input #>> '{statement,currency}', v_input #>> '{statement,unit}',
    coalesce(v_norm -> 'current', '{}'::jsonb), coalesce(v_input -> 'source', '{}'::jsonb)
  );

  if jsonb_typeof(v_norm -> 'previous') = 'object' then
    insert into financial_statements (
      owner_id, analysis_id, company_id, period_role, fiscal_year, period, basis, currency, entered_unit, amounts, source
    ) values (
      uid, v_analysis_id, v_company_id, 'previous',
      (v_norm #>> '{previous,fiscal_year}')::int, v_norm #>> '{previous,period}', payload ->> 'basis',
      v_input #>> '{statement,currency}', v_input #>> '{statement,unit}',
      coalesce(v_norm #> '{previous,values}', '{}'::jsonb), coalesce(v_input -> 'source', '{}'::jsonb)
    );
  end if;

  return v_analysis_id;
end;
$$;

revoke all on function public.create_analysis(jsonb) from public, anon;
grant execute on function public.create_analysis(jsonb) to authenticated;
