# StockWorth AI

Fundamental-analysis decision support for stocks listed on Bursa Efek Indonesia (BEI/IDX).
Users enter or import financial statements; the backend validates them, normalises units,
calculates ratios, produces a transparent score, and explains the results with AI when it is
configured, or with labelled rule-based findings when it is not.

The interface is in Bahasa Indonesia, with IDR and `id-ID` number formatting.

> StockWorth AI is an analytical tool, not investment advice. It does not predict prices,
> does not fetch live market data, and never fills missing data with zeros or estimates.

## What works

| Area | Status |
|---|---|
| React + Vite + TS frontend, light/dark/system theme (persisted), responsive shell with collapsible sidebar | ✅ |
| FastAPI backend: calculations, validation, scoring, findings, consistent error format | ✅ |
| 4-step wizard: company → input method → financials → review (server-side preview) → save | ✅ |
| Import: CSV / XLSX / XLS with template download, row-level errors/warnings, preview, cell traceability | ✅ |
| Import: text-based PDF financial statements (bilingual IDX line items, unit detection) | ✅ Beta, every value must be confirmed |
| Persistence: Supabase (Auth + RLS) **or** local SQLite fallback for development | ✅ (Supabase path not tested against a live project, see below) |
| History: search, period/year filter, sort, pagination, delete with confirmation | ✅ |
| Charts from saved data only (no generated history) with a data-table view | ✅ |
| AI insights via the Anthropic API (structured JSON output), honest rule-based fallback, rate limit | ✅ (live AI call not exercised: no key in this environment) |
| Scanned (image) PDFs / OCR | ❌ Detected and rejected with a clear message |
| Share-price lookup ("Ambil harga") via a swappable provider, Alpha Vantage first | ✅ (Alpha Vantage currently has no BEI data, see below) |
| Watchlist, real-time prices, peer comparison | ❌ Out of scope (not faked) |

## Quick start (local mode, no credentials needed)

Requirements: Python 3.12+, Node 20+.

```bash
# 1. Backend
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # optional; defaults work for local mode
uvicorn app.main:app --reload --port 8000

# 2. Frontend (new terminal)
cd frontend
npm install
cp .env.example .env.local      # optional; defaults point at localhost:8000
npm run dev                     # http://localhost:5173
```

With no Supabase variables, the backend runs in **local mode**: one fixed local user, data in
`backend/data/stockworth_local.db`. The sidebar shows "Mode lokal". Local mode is refused when
`APP_ENV=production`.

### Verify

```bash
cd backend && python -m pytest -q          # 143 tests: calculator, scoring, importers (CSV/XLSX/XLS/PDF), market data, AI, API
cd frontend && npm run typecheck && npm run build
curl http://localhost:8000/api/health
```

Interactive API docs: http://localhost:8000/docs (hidden in production).

## Enabling Supabase (auth + persistent per-user storage)

1. Create a Supabase project. In **SQL Editor**, run `database/migrations/001_initial_schema.sql`, then `002_stock_prices.sql`.
2. Set the same project URL and **anon** key in both places:
   - `backend/.env`: `SUPABASE_URL`, `SUPABASE_ANON_KEY`
   - `frontend/.env.local`: `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`
3. Restart both apps. Users now sign up or sign in at `/masuk` (email + password).

How it is secured:
- The backend verifies each bearer token with Supabase Auth (`GET /auth/v1/user`) and takes the
  user id from the verified token only, never from the request body.
- The backend calls PostgREST **with the user's own token**, so the RLS policies in the migration
  decide access. No service-role key is used anywhere.
- `create_analysis(payload)` is a `SECURITY INVOKER` function that writes the company, analysis and
  statements in one transaction, under the caller's RLS.
- Analyses are immutable snapshots (there is no update policy) tied to a methodology version.
- The Settings page reads and updates `profiles` directly through the Supabase JS client (RLS-scoped).

The migration was syntax-checked with the Postgres parser (`pglast`), including the PL/pgSQL
functions, but has not yet been run against a live Supabase project. Run it on a staging project
first and check sign-up, save, list and delete with two different users.

## Enabling AI insights

Two providers are supported; choose one with `AI_PROVIDER` in `backend/.env`:

- **Gemini**: `AI_PROVIDER=gemini`, `GEMINI_API_KEY=<Google AI Studio key>`; default model `gemini-3.5-flash`.
  Uses the Gemini API (`generativelanguage.googleapis.com`) with `responseJsonSchema`, and retries once on 500/503.
  `gemini-flash-latest` also works but took 90–120 s per insight in testing, so it is not the default.
- **Anthropic**: `AI_PROVIDER=anthropic`, `ANTHROPIC_API_KEY=...`; default model `claude-opus-5-5`.

Keys stay on the server (never in `frontend/.env`); `/api/health` reports only whether AI is configured.

- The model receives structured, validated metrics, scores, rule findings and missing-data
  lists. It never receives raw files or free-text notes. The company name is marked as
  unverified user input and treated as data, not instructions.
- Output is constrained to a JSON schema: `summary, strengths, risks, valuation_observations,
  missing_information, conclusion, limitations`.
- Server-side refusal fallback (`fallbacks: "default"`) is enabled. Any failure (no key, network
  error, refusal, invalid output) returns the **rule-based** insight, stored with
  `source = "rule_based"` and the reason. A fallback is never labelled as AI.
- Rate limit: `AI_RATE_LIMIT_PER_HOUR` per user (default 10), in memory per process.

## Share prices (market data)

Set `ALPHA_VANTAGE_API_KEY` in `backend/.env` to show an **Ambil harga** button in the wizard.

- Only IDX listings are accepted: the backend queries `TICKER.JK` and confirms through symbol
  search that the listing trades in IDR. A bare ticker is never queried: on Alpha Vantage, `BBCA`
  is a US ETF, not Bank Central Asia. US ADR/OTC listings in USD (e.g. `TLK`, `PBCRY`) are never used.
- **Current coverage:** the Alpha Vantage free tier (tested on 2026-10-29) returns no data for `.JK`
  symbols, so the app reports "tidak tersedia" and the price stays manual. To get IDX prices, add a
  provider that covers BEI in `app/services/market_data.py` (implement `get_quote`) and select it with
  `MARKET_DATA_PROVIDER`.
- Quotes are cached (`MARKET_CACHE_SECONDS`), rate-limited per user (`MARKET_RATE_LIMIT_PER_HOUR`) and
  stored in `stock_prices` (migration `002_stock_prices.sql`).
- A price is saved as provider-sourced only if this server fetched exactly that price and date. Edited
  or unverifiable prices are stored as manual. The report shows which one it is.

## Calculation methodology (v1.0.0)

Implemented in `backend/app/services/calculator.py`. All monetary inputs are multiplied by the
chosen unit (unit / ribu / juta / miliar) before any ratio is computed. Share counts are never scaled.

| Metric | Formula | Notes |
|---|---|---|
| NPM | net income / revenue × 100 | revenue = 0 → not meaningful |
| ROE | NI attributable to parent / **average** parent equity × 100 | needs opening + closing equity; falls back to total equity with a recorded assumption |
| ROA | net income / **average** total assets × 100 | the closing balance is never used as a stand-in for the average |
| DER | total liabilities / total equity | equity ≤ 0 → not meaningful (and scored 0, explicitly); not applied to banks |
| Current ratio | current assets / current liabilities | not applied to financial-sector companies |
| Revenue / NI growth | current / comparable previous − 1 | only year-over-year, same basis and period; previous ≤ 0 → not meaningful |
| EPS | NI attributable / weighted average ordinary shares | |
| PER | price / EPS | EPS must be positive and cover 12 months; non-IDR statements need an FX rate |
| BVPS / PBV | parent equity / shares outstanding; price / BVPS | single share class assumed (recorded); BVPS ≤ 0 → not meaningful |
| FCF, FCF margin | OCF − capex; FCF / revenue | |
| Cash-flow quality | OCF / net income | NI ≤ 0 → explained qualitatively; limitations stated |

Other rules:
- Statuses are `ok`, `unavailable` (missing input, with the reason), `not_meaningful` (zero or negative
  denominator) and `not_applicable` (sector rule). A missing value is never turned into 0.
- For annual statements only, a missing opening balance is taken from the previous fiscal year's
  closing balance, which is the same figure by definition, and this is recorded on the metric.
- Interim (quarterly / YTD) ROE and ROA are shown un-annualised; scoring uses a linear
  annualisation that is stated on the metric.
- Consistency warnings cover: balance sheet not balancing, current items larger than totals,
  implausible units, stale prices (over 90 days), share-count jumps, and non-comparable periods.

## Scoring (provisional MVP heuristics)

Configured in `backend/app/services/scoring_config.py` (override with `SCORING_CONFIG_PATH`).

- **Fundamental score**: profitability 30%, growth 20%, leverage 20%, liquidity 15%, cash flow 15%.
  Each metric is scored linearly between a `worst` and a `best` threshold from a **sector profile**
  (default, capital-intensive, bank, non-bank financial). Dimensions without data reduce *coverage*;
  they are not scored as zero. Below 60% weighted coverage, or with no profitability data, **no
  overall score is issued**. Bank scores are always provisional (CAR, NPL, LDR and NIM are not supported yet).
- **Valuation score**: PER and PBV against configurable reference bands. It is kept separate from
  quality and needs a dated price. Labels are neutral ("relatively low versus reference"), and a low
  multiple combined with falling earnings is flagged as a possible value trap.
- These weights and thresholds are not empirically validated investment thresholds. The UI says so.

## API

| Method | Path | Auth* | Purpose |
|---|---|---|---|
| GET | `/api/health` | – | status, storage mode, AI configured (no secrets) |
| GET | `/api/methodology` | – | scoring config, labels |
| POST | `/api/analysis/calculate` | – | validate + calculate, no persistence |
| POST | `/api/analysis` | ✓ | recalculate on the server and save (client results are never trusted) |
| GET | `/api/analysis` | ✓ | list (`q, ticker, fiscal_year, period, sort, limit, offset`) |
| GET | `/api/analysis/stats` | ✓ | totals for the dashboard |
| GET | `/api/analysis/{id}` | ✓ | full record + latest insight |
| DELETE | `/api/analysis/{id}` | ✓ | delete (cascades statements and insights) |
| GET | `/api/market/quote?ticker=XXXX` | ✓ | latest close from the market-data provider (IDX/IDR only) |
| POST | `/api/analysis/import` | – | CSV/XLSX → preview (nothing stored) |
| GET | `/api/analysis/import/template?format=csv\|xlsx` | – | template download |
| POST | `/api/analysis/{id}/insights` | ✓ | AI insight or labelled rule-based fallback |

\* Required when Supabase is configured. Errors always use `{"error": {"code", "message", "details"}}`.

## PDF import (beta)

`app/services/pdf_import.py` reads **text-based** PDFs with `pdfplumber` (up to 20 MB / 400 pages; the
first 150 pages are scanned within a 40 s budget):

- Lines are matched against bilingual IDX line items (e.g. "Jumlah aset / Total assets", "Laba tahun berjalan",
  "Arus kas bersih diperoleh dari aktivitas operasi", "Perolehan aset tetap"); the first two grouped numbers
  are taken as current and comparative period. Note references such as `2c,25` are ignored.
- The attributable-profit line is taken from the profit section, not from comprehensive income.
- Unit and currency are detected from "dalam jutaan Rupiah" / "in thousands of US Dollars" and normalised.
- Share counts (weighted average, outstanding) live in the notes and are **not** extracted.
- Scanned PDFs (no text layer) and password-protected PDFs are rejected with specific messages.
- Every value is marked "Periksa" with its page and source line, and nothing is saved until the user confirms.
- Tested on synthetic statements laid out like IDX reports; real reports vary in layout, so always verify.

## Import safety

Files are parsed in memory and never written to disk. The file name is sanitised and never used
as a path. Limits: 2 MB and 200 rows for `.csv`/`.xlsx`/`.xls`; 20 MB for `.pdf`. Macro-enabled Excel files
(`.xlsm`, `.xlsb`, or `.xls` with a VBA project) are rejected, the archive is checked against decompression bombs, and formulas are **never evaluated**:
XLSX formula cells use Excel's cached value and are flagged, or rejected if there is none. Numbers
are read in Indonesian format (`1.234.567,89`), with parentheses or a minus sign for negatives.
Each value keeps its source cell (e.g. `Data!C5`), and values edited after import are recorded.

## Project layout

```
backend/   FastAPI app (core/, routers/, schemas/, services/), tests/
frontend/  React app (app/, components/{layout,analysis,charts,ui}, pages/, hooks/, lib/, schemas/, types/)
database/  migrations/001_initial_schema.sql
```

## Known limitations / next steps

- PDF extraction is not implemented.
- The Supabase path (RLS, RPC, auth) is implemented and syntax-checked but needs a live-project test.
- Rate limits are in-memory per process; use a shared store when running several instances.
- Bank-specific metrics (CAR, NPL, LDR, NIM, BOPO) are not supported yet.
- Fiscal year ends are assumed to be standard; there is no TTM aggregation of quarterly data.
- Light-theme secondary text is slightly darker than the brief's `#737B8C` (HSL 221° 10% 45%
  instead of 50%) so small text meets WCAG AA contrast on the `#F7F8FA` background.
