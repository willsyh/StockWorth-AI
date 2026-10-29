from datetime import date, timedelta

import httpx
import pytest

from app.services import market_data
from app.services.market_data import (
    AlphaVantageProvider,
    MarketDataError,
    MarketDataUnavailable,
    Quote,
)

TODAY = date.today().isoformat()


def fake_av(responses: dict):
    """Patch httpx.get with canned Alpha Vantage responses keyed by `function`."""
    calls = []

    def _get(url, params=None, timeout=None):
        calls.append(params)
        body = responses[params["function"]]
        return httpx.Response(200, json=body, request=httpx.Request("GET", url))

    return _get, calls


SEARCH_IDX = {"bestMatches": [{"1. symbol": "BBCA.JK", "2. name": "Bank Central Asia", "8. currency": "IDR"}]}
QUOTE_OK = {"Global Quote": {"01. symbol": "BBCA.JK", "05. price": "9150.0000", "07. latest trading day": TODAY}}


def test_valid_idx_quote(monkeypatch):
    get, calls = fake_av({"GLOBAL_QUOTE": QUOTE_OK, "SYMBOL_SEARCH": SEARCH_IDX})
    monkeypatch.setattr(market_data.httpx, "get", get)
    q = AlphaVantageProvider("k").get_quote("BBCA")
    assert q.price == 9150.0 and q.currency == "IDR" and q.provider_symbol == "BBCA.JK"
    assert q.trading_date == TODAY
    assert calls[0]["symbol"] == "BBCA.JK"  # never the bare ticker


def test_empty_quote_is_unavailable(monkeypatch):
    get, _ = fake_av({"GLOBAL_QUOTE": {"Global Quote": {}}})
    monkeypatch.setattr(market_data.httpx, "get", get)
    with pytest.raises(MarketDataUnavailable):
        AlphaVantageProvider("k").get_quote("TLKM")


def test_non_idr_listing_rejected(monkeypatch):
    # Real-world case: the search only finds US ADR / OTC listings in USD.
    search = {"bestMatches": [{"1. symbol": "PBCRY", "8. currency": "USD"}, {"1. symbol": "BBCA", "8. currency": "USD"}]}
    get, _ = fake_av({"GLOBAL_QUOTE": QUOTE_OK, "SYMBOL_SEARCH": search})
    monkeypatch.setattr(market_data.httpx, "get", get)
    with pytest.raises(MarketDataUnavailable) as e:
        AlphaVantageProvider("k").get_quote("BBCA")
    assert "ADR" in str(e.value)


def test_symbol_mismatch_rejected(monkeypatch):
    quote = {"Global Quote": {"01. symbol": "BBCA", "05. price": "40.1", "07. latest trading day": TODAY}}
    get, _ = fake_av({"GLOBAL_QUOTE": quote})
    monkeypatch.setattr(market_data.httpx, "get", get)
    with pytest.raises(MarketDataUnavailable):
        AlphaVantageProvider("k").get_quote("BBCA")


@pytest.mark.parametrize("price", ["0", "-5", "abc", "nan"])
def test_invalid_price_rejected(monkeypatch, price):
    quote = {"Global Quote": {"01. symbol": "BBCA.JK", "05. price": price, "07. latest trading day": TODAY}}
    get, _ = fake_av({"GLOBAL_QUOTE": quote, "SYMBOL_SEARCH": SEARCH_IDX})
    monkeypatch.setattr(market_data.httpx, "get", get)
    with pytest.raises(MarketDataUnavailable):
        AlphaVantageProvider("k").get_quote("BBCA")


def test_future_trading_date_rejected(monkeypatch):
    future = (date.today() + timedelta(days=3)).isoformat()
    quote = {"Global Quote": {"01. symbol": "BBCA.JK", "05. price": "9000", "07. latest trading day": future}}
    get, _ = fake_av({"GLOBAL_QUOTE": quote, "SYMBOL_SEARCH": SEARCH_IDX})
    monkeypatch.setattr(market_data.httpx, "get", get)
    with pytest.raises(MarketDataUnavailable):
        AlphaVantageProvider("k").get_quote("BBCA")


def test_quota_message_is_rate_limit(monkeypatch):
    get, _ = fake_av({"GLOBAL_QUOTE": {"Information": "Please consider spreading out your free API requests (25 requests per day)"}})
    monkeypatch.setattr(market_data.httpx, "get", get)
    with pytest.raises(MarketDataError) as e:
        AlphaVantageProvider("k").get_quote("BBCA")
    assert e.value.status_code == 429


def test_network_error(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(market_data.httpx, "get", boom)
    with pytest.raises(MarketDataError) as e:
        AlphaVantageProvider("secret-key").get_quote("BBCA")
    assert "secret-key" not in str(e.value)


# --- Endpoint ------------------------------------------------------------------------

class FakeProvider:
    name = "fake"
    label = "Fake"

    def __init__(self, unavailable=False):
        self.unavailable = unavailable
        self.calls = 0

    def get_quote(self, ticker):
        self.calls += 1
        if self.unavailable:
            raise MarketDataUnavailable("Tidak tersedia untuk BEI.")
        return Quote(ticker=ticker, provider="fake", provider_symbol=f"{ticker}.JK", price=9150.0, currency="IDR",
                     trading_date=TODAY, fetched_at="2026-10-29T03:00:00+00:00", note="n")


def test_quote_endpoint_not_configured(client):
    r = client.get("/api/market/quote", params={"ticker": "BBCA"})
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "market_data_not_configured"


def test_quote_endpoint_and_cache(client, monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr("app.routers.market.get_market_provider", lambda s: fake)
    r = client.get("/api/market/quote", params={"ticker": "bbca"})
    assert r.status_code == 200
    body = r.json()
    assert body["price"] == 9150.0 and body["provider_symbol"] == "BBCA.JK" and body["cached"] is False
    assert client.get("/api/market/quote", params={"ticker": "BBCA"}).json()["cached"] is True
    assert fake.calls == 1


def test_quote_endpoint_unavailable(client, monkeypatch):
    monkeypatch.setattr("app.routers.market.get_market_provider", lambda s: FakeProvider(unavailable=True))
    r = client.get("/api/market/quote", params={"ticker": "TLKM"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "price_unavailable"


def test_quote_endpoint_validates_ticker(client):
    assert client.get("/api/market/quote", params={"ticker": "BBCA.JK"}).status_code == 422


def test_provider_origin_verified_on_save(client, base_input, monkeypatch):
    monkeypatch.setattr("app.routers.market.get_market_provider", lambda s: FakeProvider())
    base_input["company"]["ticker"] = "BBCA"
    client.get("/api/market/quote", params={"ticker": "BBCA"})
    base_input["market"] = {"share_price": 9150.0, "share_price_date": TODAY, "price_origin": "provider",
                            "price_provider": "fake"}
    rec = client.post("/api/analysis", json=base_input).json()
    m = rec["input"]["market"]
    assert m["price_origin"] == "provider" and m["price_provider_symbol"] == "BBCA.JK"


def test_forged_or_edited_provider_price_downgraded(client, base_input, monkeypatch):
    monkeypatch.setattr("app.routers.market.get_market_provider", lambda s: FakeProvider())
    base_input["company"]["ticker"] = "BBCA"
    client.get("/api/market/quote", params={"ticker": "BBCA"})
    # user changed the price after fetching, but the client still claims provider origin
    base_input["market"] = {"share_price": 9999.0, "share_price_date": TODAY, "price_origin": "provider",
                            "price_provider": "fake"}
    m = client.post("/api/analysis", json=base_input).json()["input"]["market"]
    assert m["price_origin"] == "manual" and m["price_provider"] is None
