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
from datetime import date, datetime, timezone
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


def get_market_provider(settings: Settings) -> MarketDataProvider | None:
    if settings.market_data_configured:
        return AlphaVantageProvider(settings.alpha_vantage_api_key)
    return None


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
