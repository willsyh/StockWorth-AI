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


# --- GoAPI.id ----------------------------------------------------------------------------

from app.services.market_data import GoAPIProvider  # noqa: E402


def fake_goapi(status=200, body=None, capture=None):
    def _get(url, params=None, headers=None, timeout=None):
        if capture is not None:
            capture.update(url=url, params=params, headers=headers)
        return httpx.Response(status, json=body, request=httpx.Request("GET", url))

    return _get


GOAPI_OK = {"status": "success", "message": "ok", "data": [
    {"date": TODAY, "symbol": "BBCA", "open": 9100, "high": 9200, "low": 9050, "close": 9150, "volume": 1, "change": 50}]}


def test_goapi_quote(monkeypatch):
    cap = {}
    monkeypatch.setattr(market_data.httpx, "get", fake_goapi(body=GOAPI_OK, capture=cap))
    q = GoAPIProvider("k").get_quote("BBCA")
    assert q.price == 9150.0 and q.currency == "IDR" and q.trading_date == TODAY and q.provider == "goapi"
    assert cap["params"] == {"symbols": "BBCA"} and cap["headers"]["X-API-KEY"] == "k"


def test_goapi_nested_results_shape(monkeypatch):
    body = {"status": "success", "data": {"results": GOAPI_OK["data"]}}
    monkeypatch.setattr(market_data.httpx, "get", fake_goapi(body=body))
    assert GoAPIProvider("k").get_quote("BBCA").price == 9150.0


@pytest.mark.parametrize("body", [
    {"status": "success", "data": []},
    {"status": "success", "data": [{"date": TODAY, "symbol": "BBRI", "close": 4000}]},  # other symbol only
    {"status": "error", "message": "symbol not found"},
])
def test_goapi_unavailable(monkeypatch, body):
    monkeypatch.setattr(market_data.httpx, "get", fake_goapi(body=body))
    with pytest.raises(MarketDataUnavailable):
        GoAPIProvider("k").get_quote("BBCA")


@pytest.mark.parametrize("close", [0, -1, "abc", None])
def test_goapi_invalid_price(monkeypatch, close):
    body = {"status": "success", "data": [{"date": TODAY, "symbol": "BBCA", "close": close}]}
    monkeypatch.setattr(market_data.httpx, "get", fake_goapi(body=body))
    with pytest.raises(MarketDataUnavailable):
        GoAPIProvider("k").get_quote("BBCA")


@pytest.mark.parametrize("status,code", [(401, 503), (429, 429), (500, 503)])
def test_goapi_http_errors(monkeypatch, status, code):
    monkeypatch.setattr(market_data.httpx, "get", fake_goapi(status, {"status": "error", "message": "x"}))
    with pytest.raises(MarketDataError) as e:
        GoAPIProvider("secret").get_quote("BBCA")
    assert e.value.status_code == code and "secret" not in str(e.value)


def test_goapi_selected_by_settings():
    from app.core.config import Settings
    from app.services.market_data import get_market_provider

    s = Settings(_env_file=None, market_data_provider="goapi", goapi_api_key="g")
    assert isinstance(get_market_provider(s), GoAPIProvider)
    assert get_market_provider(Settings(_env_file=None, market_data_provider="goapi", goapi_api_key="")) is None


# --- Finnhub -----------------------------------------------------------------------------

from app.services.market_data import FinnhubProvider  # noqa: E402


def fake_finnhub(status=200, body=None, capture=None):
    def _get(url, params=None, headers=None, timeout=None):
        if capture is not None:
            capture.update(url=url, params=params, headers=headers)
        return httpx.Response(status, json=body, request=httpx.Request("GET", url))

    return _get


def _ts_today_jakarta():
    from datetime import datetime, timedelta, timezone

    return int(datetime.now(timezone(timedelta(hours=7))).replace(hour=9, minute=0, second=0).timestamp())


def test_finnhub_quote(monkeypatch):
    cap = {}
    body = {"c": 9150, "d": 50, "dp": 0.55, "h": 9200, "l": 9050, "o": 9100, "pc": 9100, "t": _ts_today_jakarta()}
    monkeypatch.setattr(market_data.httpx, "get", fake_finnhub(body=body, capture=cap))
    q = FinnhubProvider("k").get_quote("BBCA")
    assert q.price == 9150.0 and q.provider_symbol == "BBCA.JK" and q.currency == "IDR" and q.provider == "finnhub"
    assert cap["params"] == {"symbol": "BBCA.JK"} and cap["headers"]["X-Finnhub-Token"] == "k"


def test_finnhub_zero_response_is_unavailable(monkeypatch):
    body = {"c": 0, "d": None, "dp": None, "h": 0, "l": 0, "o": 0, "pc": 0, "t": 0}
    monkeypatch.setattr(market_data.httpx, "get", fake_finnhub(body=body))
    with pytest.raises(MarketDataUnavailable, match="tidak memiliki data"):
        FinnhubProvider("k").get_quote("BBCA")


def test_finnhub_plan_without_access(monkeypatch):
    monkeypatch.setattr(market_data.httpx, "get", fake_finnhub(403, {"error": "You don't have access to this resource."}))
    with pytest.raises(MarketDataUnavailable, match="paket berbayar"):
        FinnhubProvider("k").get_quote("BBCA")


@pytest.mark.parametrize("status,code", [(401, 503), (429, 429), (502, 503)])
def test_finnhub_http_errors(monkeypatch, status, code):
    monkeypatch.setattr(market_data.httpx, "get", fake_finnhub(status, {"error": "x"}))
    with pytest.raises(MarketDataError) as e:
        FinnhubProvider("secret").get_quote("BBCA")
    assert e.value.status_code == code and "secret" not in str(e.value)


def test_finnhub_selected_by_settings():
    from app.core.config import Settings
    from app.services.market_data import get_market_provider

    assert isinstance(get_market_provider(Settings(_env_file=None, market_data_provider="finnhub", finnhub_api_key="f")),
                      FinnhubProvider)


# --- Yahoo Finance ------------------------------------------------------------------------

from app.services.market_data import YahooFinanceProvider  # noqa: E402


def _yahoo_body(**meta_overrides):
    meta = {"currency": "IDR", "symbol": "BBCA.JK", "exchangeName": "JKT", "instrumentType": "EQUITY",
            "regularMarketPrice": 4940.0, "regularMarketTime": _ts_today_jakarta()}
    meta.update(meta_overrides)
    return {"chart": {"result": [{"meta": meta}], "error": None}}


def test_yahoo_quote(monkeypatch):
    cap = {}
    monkeypatch.setattr(market_data.httpx, "get", fake_finnhub(body=_yahoo_body(), capture=cap))
    q = YahooFinanceProvider().get_quote("BBCA")
    assert q.price == 4940.0 and q.provider == "yahoo" and q.provider_symbol == "BBCA.JK" and q.currency == "IDR"
    assert cap["url"].endswith("/BBCA.JK")


@pytest.mark.parametrize("override", [
    {"currency": "USD"},          # e.g. a US listing
    {"exchangeName": "NYQ"},
    {"symbol": "BBCA"},           # bare symbol = US ETF on Yahoo
    {"instrumentType": "ETF"},
    {"regularMarketPrice": 0},
    {"regularMarketPrice": None},
])
def test_yahoo_rejects_non_idx_or_invalid(monkeypatch, override):
    monkeypatch.setattr(market_data.httpx, "get", fake_finnhub(body=_yahoo_body(**override)))
    with pytest.raises(MarketDataUnavailable):
        YahooFinanceProvider().get_quote("BBCA")


def test_yahoo_not_found(monkeypatch):
    body = {"chart": {"result": None, "error": {"code": "Not Found", "description": "No data found"}}}
    monkeypatch.setattr(market_data.httpx, "get", fake_finnhub(404, body))
    with pytest.raises(MarketDataUnavailable, match="tidak menemukan"):
        YahooFinanceProvider().get_quote("ZZZZ")


def test_yahoo_rate_limited(monkeypatch):
    monkeypatch.setattr(market_data.httpx, "get", fake_finnhub(429, {}))
    with pytest.raises(MarketDataError) as e:
        YahooFinanceProvider().get_quote("BBCA")
    assert e.value.status_code == 429


def test_yahoo_needs_no_key():
    from app.core.config import Settings
    from app.services.market_data import get_market_provider

    assert isinstance(get_market_provider(Settings(_env_file=None, market_data_provider="yahoo")), YahooFinanceProvider)
