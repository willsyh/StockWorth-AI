"""Share-price lookup behind a swappable provider.

Safety rules
* Only IDX listings are accepted: the provider symbol must be the BEI ticker with the
  `.JK` suffix, and the provider must confirm the listing trades in IDR. A bare ticker is
  never queried, because on many providers it belongs to a different company or fund
  (on Alpha Vantage, "BBCA" is a US ETF, not Bank Central Asia).
* A missing or unconfirmed quote is reported as unavailable, never guessed or
  substituted with an ADR or foreign listing.
* Every quote carries its provider, provider symbol, trading date and fetch time.
* The API key is sent only to the provider and never logged or returned.
"""

import logging
import math
import threading
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Protocol

import httpx

from app.core.config import Settings

logger = logging.getLogger("stockworth.market")

IDX_SUFFIX = ".JK"


class MarketDataUnavailable(Exception):
    """No trustworthy quote exists for this ticker at this provider."""


class MarketDataError(Exception):
    """The provider could not be queried (network, quota, bad key)."""

    def __init__(self, message: str, status_code: int = 503):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class Quote:
    ticker: str
    provider: str
    provider_symbol: str
    price: float
    currency: str
    trading_date: str  # ISO date of the trading session the price belongs to
    fetched_at: str  # ISO timestamp (UTC)
    note: str

    def to_dict(self) -> dict:
        return asdict(self)


class MarketDataProvider(Protocol):
    name: str
    label: str

    def get_quote(self, ticker: str) -> Quote: ...


class AlphaVantageProvider:
    name = "alpha_vantage"
    label = "Alpha Vantage"
    BASE_URL = "https://www.alphavantage.co/query"

    def __init__(self, api_key: str, timeout: float = 15.0):
        self._key = api_key
        self._timeout = timeout

    def _call(self, params: dict) -> dict:
        try:
            resp = httpx.get(self.BASE_URL, params={**params, "apikey": self._key}, timeout=self._timeout)
        except httpx.HTTPError as exc:
            raise MarketDataError("Penyedia data harga tidak dapat dihubungi.") from exc
        if resp.status_code != 200:
            raise MarketDataError(f"Penyedia data harga mengembalikan galat ({resp.status_code}).")
        try:
            data = resp.json()
        except ValueError as exc:
            raise MarketDataError("Respons penyedia data harga tidak valid.") from exc
        # Alpha Vantage reports quota and key problems with HTTP 200 and these fields.
        if "Information" in data or "Note" in data:
            msg = str(data.get("Information") or data.get("Note"))
            if "api key" in msg.lower() and "invalid" in msg.lower():
                raise MarketDataError("Kunci API penyedia data harga tidak valid.")
            raise MarketDataError("Batas penggunaan penyedia data harga tercapai. Coba lagi nanti.", status_code=429)
        if "Error Message" in data:
            raise MarketDataUnavailable("Simbol tidak dikenali oleh penyedia data harga.")
        return data

    def _confirm_idx_listing(self, symbol: str) -> None:
        data = self._call({"function": "SYMBOL_SEARCH", "keywords": symbol})
        for m in data.get("bestMatches", []) or []:
            if str(m.get("1. symbol", "")).upper() == symbol and str(m.get("8. currency", "")).upper() == "IDR":
                return
        raise MarketDataUnavailable(
            f"{self.label} tidak memiliki data {symbol} (Bursa Efek Indonesia, IDR). "
            "Harga dari bursa lain atau ADR tidak digunakan karena bukan harga saham BEI."
        )

    def get_quote(self, ticker: str) -> Quote:
        symbol = f"{ticker}{IDX_SUFFIX}"
        data = self._call({"function": "GLOBAL_QUOTE", "symbol": symbol})
        q = data.get("Global Quote") or {}
        if not q:
            raise MarketDataUnavailable(
                f"{self.label} tidak menyediakan harga untuk {symbol} (Bursa Efek Indonesia). "
                "Isi harga secara manual beserta tanggalnya."
            )
        if str(q.get("01. symbol", "")).upper() != symbol:
            raise MarketDataUnavailable("Simbol pada respons tidak cocok dengan simbol yang diminta.")
        try:
            price = float(q["05. price"])
            trading_day = date.fromisoformat(q["07. latest trading day"])
        except (KeyError, ValueError) as exc:
            raise MarketDataUnavailable("Data harga dari penyedia tidak lengkap.") from exc
        if not math.isfinite(price) or price <= 0:
            raise MarketDataUnavailable("Harga dari penyedia tidak valid.")
        if trading_day > date.today():
            raise MarketDataUnavailable("Tanggal harga dari penyedia tidak valid.")
        # GLOBAL_QUOTE carries no currency, so confirm the listing is the IDR one on IDX.
        self._confirm_idx_listing(symbol)
        return Quote(
            ticker=ticker,
            provider=self.name,
            provider_symbol=symbol,
            price=price,
            currency="IDR",
            trading_date=trading_day.isoformat(),
            fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            note="Harga penutupan sesi terakhir dari penyedia; bisa tertunda dan tidak real-time.",
        )


class GoAPIProvider:
    """GoAPI.id — IDX-only price API (https://goapi.io). Prices are delayed 3–10 minutes
    according to the provider's documentation."""

    name = "goapi"
    label = "GoAPI.id"
    BASE_URL = "https://api.goapi.io/stock/idx/prices"

    def __init__(self, api_key: str, timeout: float = 15.0):
        self._key = api_key
        self._timeout = timeout

    def get_quote(self, ticker: str) -> Quote:
        try:
            resp = httpx.get(self.BASE_URL, params={"symbols": ticker},
                             headers={"X-API-KEY": self._key, "Accept": "application/json"}, timeout=self._timeout)
        except httpx.HTTPError as exc:
            raise MarketDataError("Penyedia data harga tidak dapat dihubungi.") from exc
        if resp.status_code in (401, 403):
            raise MarketDataError("Kunci API GoAPI tidak valid atau tidak punya akses.")
        if resp.status_code == 429:
            raise MarketDataError("Batas penggunaan GoAPI tercapai. Coba lagi nanti.", status_code=429)
        if resp.status_code != 200:
            raise MarketDataError(f"Penyedia data harga mengembalikan galat ({resp.status_code}).")
        try:
            body = resp.json()
        except ValueError as exc:
            raise MarketDataError("Respons penyedia data harga tidak valid.") from exc
        if str(body.get("status", "")).lower() != "success":
            msg = str(body.get("message", ""))
            if "limit" in msg.lower() or "quota" in msg.lower():
                raise MarketDataError("Batas penggunaan GoAPI tercapai. Coba lagi nanti.", status_code=429)
            raise MarketDataUnavailable("GoAPI tidak mengembalikan data harga untuk kode ini.")
        data = body.get("data")
        # The documented shape is a list; some responses nest it under "results".
        items = data.get("results") if isinstance(data, dict) else data
        item = next((i for i in (items or []) if str(i.get("symbol", "")).upper() == ticker), None)
        if item is None:
            raise MarketDataUnavailable(f"GoAPI tidak memiliki harga untuk {ticker}. Periksa kode saham.")
        try:
            price = float(item["close"])
            trading_day = date.fromisoformat(str(item["date"])[:10])
        except (KeyError, TypeError, ValueError) as exc:
            raise MarketDataUnavailable("Data harga dari penyedia tidak lengkap.") from exc
        if not math.isfinite(price) or price <= 0:
            raise MarketDataUnavailable("Harga dari penyedia tidak valid.")
        if trading_day > date.today():
            raise MarketDataUnavailable("Tanggal harga dari penyedia tidak valid.")
        return Quote(
            ticker=ticker,
            provider=self.name,
            provider_symbol=f"{ticker}{IDX_SUFFIX}",  # canonical IDX listing id (GoAPI only covers IDX)
            price=price,
            currency="IDR",
            trading_date=trading_day.isoformat(),
            fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            note="Harga terakhir dari GoAPI.id; tertunda sekitar 3–10 menit dan bukan harga real-time.",
        )


class FinnhubProvider:
    """Finnhub (https://finnhub.io) quote endpoint for the IDX listing TICKER.JK.

    Finnhub returns all-zero fields for symbols it has no data for, and HTTP 403 when the
    account's plan does not include the exchange; both are reported as unavailable.
    """

    name = "finnhub"
    label = "Finnhub"
    BASE_URL = "https://finnhub.io/api/v1/quote"
    JAKARTA = timezone(timedelta(hours=7))

    def __init__(self, api_key: str, timeout: float = 15.0):
        self._key = api_key
        self._timeout = timeout

    def get_quote(self, ticker: str) -> Quote:
        symbol = f"{ticker}{IDX_SUFFIX}"
        try:
            resp = httpx.get(self.BASE_URL, params={"symbol": symbol},
                             headers={"X-Finnhub-Token": self._key}, timeout=self._timeout)
        except httpx.HTTPError as exc:
            raise MarketDataError("Penyedia data harga tidak dapat dihubungi.") from exc
        if resp.status_code == 401:
            raise MarketDataError("Kunci API Finnhub tidak valid.")
        if resp.status_code == 403:
            raise MarketDataUnavailable(
                f"Paket Finnhub Anda tidak mencakup harga {symbol} (Bursa Efek Indonesia). "
                "Harga saham di luar AS umumnya memerlukan paket berbayar; isi harga secara manual."
            )
        if resp.status_code == 429:
            raise MarketDataError("Batas penggunaan Finnhub tercapai. Coba lagi nanti.", status_code=429)
        if resp.status_code != 200:
            raise MarketDataError(f"Penyedia data harga mengembalikan galat ({resp.status_code}).")
        try:
            body = resp.json()
        except ValueError as exc:
            raise MarketDataError("Respons penyedia data harga tidak valid.") from exc
        if not isinstance(body, dict) or "error" in body:
            raise MarketDataUnavailable(f"Finnhub tidak menyediakan harga untuk {symbol}.")
        price, ts = body.get("c"), body.get("t")
        if not isinstance(price, (int, float)) or not isinstance(ts, (int, float)) or price <= 0 or ts <= 0:
            raise MarketDataUnavailable(
                f"Finnhub tidak memiliki data harga untuk {symbol} (Bursa Efek Indonesia). Isi harga secara manual."
            )
        if not math.isfinite(price):
            raise MarketDataUnavailable("Harga dari penyedia tidak valid.")
        trading_day = datetime.fromtimestamp(ts, tz=self.JAKARTA).date()
        if trading_day > datetime.now(self.JAKARTA).date():
            raise MarketDataUnavailable("Tanggal harga dari penyedia tidak valid.")
        return Quote(
            ticker=ticker,
            provider=self.name,
            provider_symbol=symbol,
            price=float(price),
            currency="IDR",  # the .JK listing trades in rupiah
            trading_date=trading_day.isoformat(),
            fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            note="Harga terakhir dari Finnhub untuk listing BEI; bisa tertunda dan bukan harga real-time.",
        )


class YahooFinanceProvider:
    """Yahoo Finance public chart endpoint (unofficial; no key, no SLA, not for commercial use).

    Only accepted when Yahoo confirms the listing is TICKER.JK on the Jakarta exchange in IDR.
    """

    name = "yahoo"
    label = "Yahoo Finance"
    BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart/"
    JAKARTA = timezone(timedelta(hours=7))
    HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; StockWorthAI/0.1)", "Accept": "application/json"}

    def __init__(self, timeout: float = 15.0):
        self._timeout = timeout

    def get_quote(self, ticker: str) -> Quote:
        symbol = f"{ticker}{IDX_SUFFIX}"
        try:
            resp = httpx.get(self.BASE_URL + symbol, params={"range": "5d", "interval": "1d"},
                             headers=self.HEADERS, timeout=self._timeout)
        except httpx.HTTPError as exc:
            raise MarketDataError("Yahoo Finance tidak dapat dihubungi.") from exc
        if resp.status_code == 404:
            raise MarketDataUnavailable(f"Yahoo Finance tidak menemukan {symbol}. Periksa kode saham.")
        if resp.status_code == 429:
            raise MarketDataError("Yahoo Finance membatasi permintaan. Coba lagi nanti.", status_code=429)
        if resp.status_code != 200:
            raise MarketDataError(f"Yahoo Finance mengembalikan galat ({resp.status_code}).")
        try:
            chart = resp.json().get("chart") or {}
        except ValueError as exc:
            raise MarketDataError("Respons Yahoo Finance tidak valid.") from exc
        results = chart.get("result") or []
        if chart.get("error") or not results:
            raise MarketDataUnavailable(f"Yahoo Finance tidak memiliki data untuk {symbol}.")
        meta = results[0].get("meta") or {}
        if str(meta.get("symbol", "")).upper() != symbol:
            raise MarketDataUnavailable("Simbol pada respons tidak cocok dengan simbol yang diminta.")
        if str(meta.get("currency", "")).upper() != "IDR" or str(meta.get("exchangeName", "")).upper() != "JKT":
            raise MarketDataUnavailable(
                f"Data {symbol} dari Yahoo Finance bukan listing Bursa Efek Indonesia dalam IDR; tidak digunakan."
            )
        if meta.get("instrumentType") not in (None, "EQUITY"):
            raise MarketDataUnavailable(f"{symbol} bukan saham biasa.")
        price, ts = meta.get("regularMarketPrice"), meta.get("regularMarketTime")
        if not isinstance(price, (int, float)) or not isinstance(ts, (int, float)) or not math.isfinite(price)                 or price <= 0 or ts <= 0:
            raise MarketDataUnavailable("Harga dari Yahoo Finance tidak valid.")
        trading_day = datetime.fromtimestamp(ts, tz=self.JAKARTA).date()
        if trading_day > datetime.now(self.JAKARTA).date():
            raise MarketDataUnavailable("Tanggal harga dari Yahoo Finance tidak valid.")
        return Quote(
            ticker=ticker,
            provider=self.name,
            provider_symbol=symbol,
            price=float(price),
            currency="IDR",
            trading_date=trading_day.isoformat(),
            fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            note="Harga terakhir dari Yahoo Finance (sumber tidak resmi); bisa tertunda dan bukan harga real-time.",
        )


def get_market_provider(settings: Settings) -> MarketDataProvider | None:
    if not settings.market_data_configured:
        return None
    if settings.market_data_provider == "yahoo":
        return YahooFinanceProvider()
    if settings.market_data_provider == "finnhub":
        return FinnhubProvider(settings.finnhub_api_key)
    if settings.market_data_provider == "goapi":
        return GoAPIProvider(settings.goapi_api_key)
    return AlphaVantageProvider(settings.alpha_vantage_api_key)


class QuoteCache:
    """Caches quotes (saves the provider's small free quota) and lets the server verify
    that a price submitted with origin "provider" really came from the provider."""

    def __init__(self):
        self._items: dict[str, tuple[float, Quote]] = {}
        self._issued: dict[tuple[str, str, float], Quote] = {}
        self._lock = threading.Lock()

    def get(self, ticker: str, max_age: float) -> Quote | None:
        with self._lock:
            hit = self._items.get(ticker)
        if hit and time.monotonic() - hit[0] < max_age:
            return hit[1]
        return None

    def put(self, quote: Quote) -> None:
        with self._lock:
            self._items[quote.ticker] = (time.monotonic(), quote)
            if len(self._issued) > 5000:
                self._issued.clear()
            self._issued[(quote.ticker, quote.trading_date, quote.price)] = quote

    def issued(self, ticker: str, trading_date: str, price: float) -> Quote | None:
        with self._lock:
            return self._issued.get((ticker, trading_date, price))

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._issued.clear()


quote_cache = QuoteCache()
