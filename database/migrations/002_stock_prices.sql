-- StockWorth AI — sourced share prices (audit trail of prices fetched from a market-data provider).
-- Rows are written by the backend with the end user's token, so RLS applies.
-- Only IDX listings (provider symbol ending in .JK, currency IDR) are stored.

create table if not exists public.stock_prices (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  ticker text not null check (ticker ~ '^[A-Z]{4}$'),
  provider text not null check (char_length(provider) <= 40),
  provider_symbol text not null check (provider_symbol ~ '^[A-Z]{4}\.JK$'),
  price numeric(14, 4) not null check (price > 0),
  currency text not null check (currency = 'IDR'),
  trading_date date not null,
  fetched_at timestamptz not null,
  created_at timestamptz not null default now()
);

create index if not exists stock_prices_owner_ticker_idx
  on public.stock_prices (owner_id, ticker, trading_date desc);

alter table public.stock_prices enable row level security;

drop policy if exists "stock_prices_select_own" on public.stock_prices;
create policy "stock_prices_select_own" on public.stock_prices
  for select using (owner_id = auth.uid());
drop policy if exists "stock_prices_insert_own" on public.stock_prices;
create policy "stock_prices_insert_own" on public.stock_prices
  for insert with check (owner_id = auth.uid());
drop policy if exists "stock_prices_delete_own" on public.stock_prices;
create policy "stock_prices_delete_own" on public.stock_prices
  for delete using (owner_id = auth.uid());
