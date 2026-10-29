"""Persistence for analyses and insights.

* `SupabaseRepository` talks to Supabase PostgREST *with the end user's access token*,
  so Row Level Security policies decide what each user can read and write. No
  service-role key is used or needed.
* `LocalRepository` is a SQLite fallback for local development when Supabase is not
  configured. It is still scoped by owner id.
"""

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

import httpx

from app.core.auth import CurrentUser
from app.core.config import Settings
from app.core.errors import AppError


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def summary_from_record(rec: dict) -> dict:
    """Small list-view projection, including key figures used for trend charts."""
    result = rec["result"]
    metrics = result.get("metrics", {})
    inp = rec["input"]

    def mv(key):
        m = metrics.get(key) or {}
        return m.get("value") if m.get("status") == "ok" else None

    norm = (result.get("normalized") or {}).get("current") or {}

    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "ticker": rec["ticker"],
        "company_name": rec["company_name"],
        "sector": rec.get("sector"),
        "fiscal_year": rec["fiscal_year"],
        "period": rec["period"],
        "basis": rec["basis"],
        "period_label": rec["period_label"],
        "currency": inp["statement"]["currency"],
        "unit": inp["statement"]["unit"],
        "methodology_version": rec["methodology_version"],
        "fundamental_score": result["fundamental_score"].get("score"),
        "fundamental_status": result["fundamental_score"].get("status"),
        "fundamental_label": result["fundamental_score"].get("label"),
        "valuation_score": result["valuation_score"].get("score"),
        "valuation_status": result["valuation_score"].get("status"),
        "completeness": result["completeness"].get("percent"),
        "source_method": inp.get("source", {}).get("method", "manual"),
        "key_figures": {
            "revenue": norm.get("revenue"),
            "net_income": norm.get("net_income") if norm.get("net_income") is not None
            else norm.get("net_income_attributable"),
            "npm": mv("npm"),
            "roe": mv("roe"),
            "roa": mv("roa"),
            "der": mv("der"),
            "operating_cash_flow": mv("operating_cash_flow"),
            "free_cash_flow": mv("free_cash_flow"),
        },
    }


class Repository(Protocol):
    def create(self, user: CurrentUser, record: dict) -> dict: ...
    def list(self, user: CurrentUser, *, q: str | None, ticker: str | None, fiscal_year: int | None,
             period: str | None, sort: str, limit: int, offset: int) -> tuple[list[dict], int]: ...
    def get(self, user: CurrentUser, analysis_id: str) -> dict | None: ...
    def delete(self, user: CurrentUser, analysis_id: str) -> bool: ...
    def save_insight(self, user: CurrentUser, insight: dict) -> dict: ...
    def latest_insight(self, user: CurrentUser, analysis_id: str) -> dict | None: ...
    def stats(self, user: CurrentUser) -> dict: ...
    def save_price(self, user: CurrentUser, quote: dict) -> None: ...


# --- Local SQLite --------------------------------------------------------------------

class LocalRepository:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS analyses (
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, created_at TEXT NOT NULL,
                    ticker TEXT NOT NULL, company_name TEXT NOT NULL, sector TEXT,
                    fiscal_year INTEGER NOT NULL, period TEXT NOT NULL, basis TEXT NOT NULL,
                    period_label TEXT NOT NULL, methodology_version TEXT NOT NULL,
                    input_json TEXT NOT NULL, result_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_analyses_owner ON analyses(owner_id, created_at);
                CREATE TABLE IF NOT EXISTS ai_insights (
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, analysis_id TEXT NOT NULL
                        REFERENCES analyses(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL, source TEXT NOT NULL, provider TEXT, model TEXT,
                    fallback_reason TEXT, content_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS stock_prices (
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, ticker TEXT NOT NULL,
                    provider TEXT NOT NULL, provider_symbol TEXT NOT NULL, price REAL NOT NULL,
                    currency TEXT NOT NULL, trading_date TEXT NOT NULL, fetched_at TEXT NOT NULL
                );
                """
            )

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def _row(r: sqlite3.Row) -> dict:
        d = dict(r)
        d["input"] = json.loads(d.pop("input_json"))
        d["result"] = json.loads(d.pop("result_json"))
        d.pop("owner_id", None)
        return d

    def create(self, user, record):
        rec = {**record, "id": str(uuid.uuid4()), "created_at": _now()}
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO analyses VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (rec["id"], user.id, rec["created_at"], rec["ticker"], rec["company_name"], rec.get("sector"),
                 rec["fiscal_year"], rec["period"], rec["basis"], rec["period_label"], rec["methodology_version"],
                 json.dumps(rec["input"]), json.dumps(rec["result"])),
            )
        return rec

    def list(self, user, *, q, ticker, fiscal_year, period, sort, limit, offset):
        where, params = ["owner_id = ?"], [user.id]
        if q:
            where.append("(ticker LIKE ? OR company_name LIKE ?)")
            like = f"%{q}%"
            params += [like, like]
        if ticker:
            where.append("ticker = ?")
            params.append(ticker)
        if fiscal_year:
            where.append("fiscal_year = ?")
            params.append(fiscal_year)
        if period:
            where.append("period = ?")
            params.append(period)
        order = "ASC" if sort == "asc" else "DESC"
        sql_where = " AND ".join(where)
        with self._conn() as c:
            total = c.execute(f"SELECT COUNT(*) FROM analyses WHERE {sql_where}", params).fetchone()[0]
            rows = c.execute(
                f"SELECT * FROM analyses WHERE {sql_where} ORDER BY created_at {order} LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
        return [self._row(r) for r in rows], total

    def get(self, user, analysis_id):
        with self._conn() as c:
            r = c.execute("SELECT * FROM analyses WHERE id = ? AND owner_id = ?", (analysis_id, user.id)).fetchone()
        return self._row(r) if r else None

    def delete(self, user, analysis_id):
        with self._lock, self._conn() as c:
            cur = c.execute("DELETE FROM analyses WHERE id = ? AND owner_id = ?", (analysis_id, user.id))
        return cur.rowcount > 0

    def save_insight(self, user, insight):
        rec = {**insight, "id": str(uuid.uuid4()), "created_at": _now()}
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO ai_insights VALUES (?,?,?,?,?,?,?,?,?)",
                (rec["id"], user.id, rec["analysis_id"], rec["created_at"], rec["source"], rec.get("provider"),
                 rec.get("model"), rec.get("fallback_reason"), json.dumps(rec["content"])),
            )
        return rec

    def latest_insight(self, user, analysis_id):
        with self._conn() as c:
            r = c.execute(
                "SELECT * FROM ai_insights WHERE analysis_id = ? AND owner_id = ? ORDER BY created_at DESC LIMIT 1",
                (analysis_id, user.id),
            ).fetchone()
        if not r:
            return None
        d = dict(r)
        d["content"] = json.loads(d.pop("content_json"))
        d.pop("owner_id", None)
        return d

    def stats(self, user):
        with self._conn() as c:
            total = c.execute("SELECT COUNT(*) FROM analyses WHERE owner_id = ?", (user.id,)).fetchone()[0]
            companies = c.execute("SELECT COUNT(DISTINCT ticker) FROM analyses WHERE owner_id = ?", (user.id,)).fetchone()[0]
        return {"total_analyses": total, "companies": companies}

    def save_price(self, user, quote):
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO stock_prices VALUES (?,?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), user.id, quote["ticker"], quote["provider"], quote["provider_symbol"],
                 quote["price"], quote["currency"], quote["trading_date"], quote["fetched_at"]),
            )


# --- Supabase (PostgREST, RLS-enforced) ----------------------------------------------

_ANALYSIS_COLUMNS = (
    "id,created_at,ticker,company_name,sector,fiscal_year,period,basis,period_label,"
    "methodology_version,input,result"
)


class SupabaseRepository:
    def __init__(self, settings: Settings):
        self.base = settings.supabase_url.rstrip("/") + "/rest/v1"
        self.anon_key = settings.supabase_anon_key

    def _headers(self, user: CurrentUser, extra: dict | None = None) -> dict:
        h = {
            "apikey": self.anon_key,
            "Authorization": f"Bearer {user.access_token}",
            "Content-Type": "application/json",
        }
        if extra:
            h.update(extra)
        return h

    def _request(self, method: str, path: str, user: CurrentUser, **kw) -> httpx.Response:
        try:
            resp = httpx.request(method, f"{self.base}{path}", headers=self._headers(user, kw.pop("headers", None)),
                                 timeout=15.0, **kw)
        except httpx.HTTPError as exc:
            raise AppError(503, "storage_unavailable", "Database tidak dapat dihubungi.") from exc
        if resp.status_code in (401, 403):
            raise AppError(401, "unauthorized", "Akses database ditolak. Silakan masuk kembali.")
        if resp.status_code >= 400:
            try:
                pg_code = str(resp.json().get("code", ""))
            except ValueError:
                pg_code = ""
            # PGRST202 = function not found, PGRST205 / 42P01 = table not found: schema was never migrated.
            if pg_code in ("PGRST202", "PGRST205", "42P01", "42883"):
                raise AppError(
                    503,
                    "database_not_migrated",
                    "Tabel database belum dibuat. Jalankan database/migrations/001_initial_schema.sql dan "
                    "002_stock_prices.sql di Supabase SQL Editor.",
                )
            raise AppError(502, "storage_error", "Gagal mengakses database.", {"status": resp.status_code, "code": pg_code})
        return resp

    def create(self, user, record):
        # One RPC call so company, analysis and statements are written in a single transaction.
        payload = {"payload": {k: record[k] for k in (
            "ticker", "company_name", "sector", "fiscal_year", "period", "basis", "period_label",
            "methodology_version", "input", "result")}}
        resp = self._request("POST", "/rpc/create_analysis", user, json=payload)
        new_id = resp.json()
        rec = self.get(user, new_id)
        if rec is None:
            raise AppError(502, "storage_error", "Analisis tersimpan tetapi tidak dapat dibaca kembali.")
        return rec

    def list(self, user, *, q, ticker, fiscal_year, period, sort, limit, offset):
        params: dict = {
            "select": _ANALYSIS_COLUMNS,
            "order": f"created_at.{'asc' if sort == 'asc' else 'desc'}",
            "limit": str(limit),
            "offset": str(offset),
        }
        if q:
            safe = "".join(ch for ch in q if ch.isalnum() or ch in " .-").strip().replace(" ", "*")
            params["or"] = f"(ticker.ilike.*{safe}*,company_name.ilike.*{safe}*)"
        if ticker:
            params["ticker"] = f"eq.{ticker}"
        if fiscal_year:
            params["fiscal_year"] = f"eq.{fiscal_year}"
        if period:
            params["period"] = f"eq.{period}"
        resp = self._request("GET", "/analyses", user, params=params, headers={"Prefer": "count=exact"})
        total = int(resp.headers.get("content-range", "*/0").split("/")[-1] or 0)
        return resp.json(), total

    def get(self, user, analysis_id):
        resp = self._request("GET", "/analyses", user, params={"select": _ANALYSIS_COLUMNS, "id": f"eq.{analysis_id}"})
        rows = resp.json()
        return rows[0] if rows else None

    def delete(self, user, analysis_id):
        resp = self._request("DELETE", "/analyses", user, params={"id": f"eq.{analysis_id}"},
                             headers={"Prefer": "return=representation"})
        return len(resp.json()) > 0

    def save_insight(self, user, insight):
        body = {k: insight.get(k) for k in ("analysis_id", "source", "provider", "model", "fallback_reason", "content")}
        resp = self._request("POST", "/ai_insights", user, json=body, headers={"Prefer": "return=representation"})
        return resp.json()[0]

    def latest_insight(self, user, analysis_id):
        resp = self._request("GET", "/ai_insights", user, params={
            "select": "id,analysis_id,created_at,source,provider,model,fallback_reason,content",
            "analysis_id": f"eq.{analysis_id}", "order": "created_at.desc", "limit": "1"})
        rows = resp.json()
        return rows[0] if rows else None

    def stats(self, user):
        resp = self._request("GET", "/analyses", user, params={"select": "ticker"})
        rows = resp.json()
        return {"total_analyses": len(rows), "companies": len({r["ticker"] for r in rows})}

    def save_price(self, user, quote):
        body = {k: quote[k] for k in ("ticker", "provider", "provider_symbol", "price", "currency",
                                      "trading_date", "fetched_at")}
        self._request("POST", "/stock_prices", user, json=body, headers={"Prefer": "return=minimal"})


_repo_lock = threading.Lock()
_repos: dict[str, Repository] = {}


def get_repository(settings: Settings) -> Repository:
    key = "supabase" if settings.supabase_enabled else f"local:{settings.local_db_path}"
    with _repo_lock:
        if key not in _repos:
            _repos[key] = SupabaseRepository(settings) if settings.supabase_enabled else LocalRepository(settings.local_db_path)
        return _repos[key]
