import copy
import os

import pytest

# Force local mode and no AI for tests, regardless of the developer's .env file.
os.environ["SUPABASE_URL"] = ""
os.environ["SUPABASE_ANON_KEY"] = ""
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["GEMINI_API_KEY"] = ""
os.environ["ALPHA_VANTAGE_API_KEY"] = ""
os.environ["APP_ENV"] = "test"

BASE_INPUT = {
    "company": {"ticker": "ABCD", "name": "PT Contoh Tbk", "sector": "consumer_non_cyclicals"},
    "statement": {"fiscal_year": 2024, "period": "FY", "basis": "annual", "currency": "IDR", "unit": "juta"},
    "current": {
        "revenue": 10_000,
        "net_income": 1_200,
        "net_income_attributable": 1_000,
        "total_assets": 20_000,
        "total_assets_begin": 18_000,
        "total_liabilities": 8_000,
        "total_equity": 12_000,
        "total_equity_begin": 11_000,
        "equity_attributable": 10_000,
        "equity_attributable_begin": 9_000,
        "current_assets": 6_000,
        "current_liabilities": 3_000,
        "operating_cash_flow": 1_500,
        "capital_expenditure": 500,
        "weighted_average_shares": 1_000_000_000,
        "shares_outstanding": 1_000_000_000,
    },
    "previous": {
        "fiscal_year": 2023,
        "period": "FY",
        "values": {"revenue": 8_000, "net_income": 1_000, "net_income_attributable": 800},
    },
    "market": {"share_price": 10_000, "share_price_date": None},
}


@pytest.fixture
def base_input():
    from datetime import date

    data = copy.deepcopy(BASE_INPUT)
    data["market"]["share_price_date"] = date.today().isoformat()
    return data


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_DB_PATH", str(tmp_path / "test.db"))
    from app.core.config import get_settings

    get_settings.cache_clear()
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.routers import analysis

    analysis._insight_limiter.reset()
    analysis._import_limiter.reset()
    analysis._calc_limiter.reset()
    from app.routers import market
    from app.services.market_data import quote_cache

    market._quote_limiter.reset()
    quote_cache.clear()
    with TestClient(create_app()) as c:
        yield c
    get_settings.cache_clear()
