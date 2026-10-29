"""Share-price lookup endpoint."""

import logging

from fastapi import APIRouter, Depends, Query

from app.core.auth import CurrentUser, get_current_user
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.rate_limit import RateLimiter
from app.services.market_data import (
    MarketDataError,
    MarketDataUnavailable,
    get_market_provider,
    quote_cache,
)
from app.services.repository import get_repository

router = APIRouter(prefix="/api/market", tags=["market"])
logger = logging.getLogger("stockworth.market")

_quote_limiter = RateLimiter(limit=get_settings().market_rate_limit_per_hour, window_seconds=3600)


@router.get("/quote", summary="Harga saham terakhir dari penyedia data (jika dikonfigurasi)")
def get_quote(
    ticker: str = Query(..., pattern=r"^[A-Za-z]{4}$"),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    settings = get_settings()
    provider = get_market_provider(settings)
    if provider is None:
        raise AppError(503, "market_data_not_configured", "Penyedia data harga belum dikonfigurasi di server.")
    t = ticker.upper()
    cached = quote_cache.get(t, settings.market_cache_seconds)
    if cached:
        return {**cached.to_dict(), "provider_label": provider.label, "cached": True}

    _quote_limiter.check(user.id)
    try:
        quote = provider.get_quote(t)
    except MarketDataUnavailable as exc:
        raise AppError(404, "price_unavailable", str(exc)) from exc
    except MarketDataError as exc:
        code = "rate_limited" if exc.status_code == 429 else "market_data_error"
        raise AppError(exc.status_code, code, str(exc)) from exc

    quote_cache.put(quote)
    try:
        get_repository(settings).save_price(user, quote.to_dict())
    except Exception:  # storing the audit row must not block the lookup
        logger.warning("Could not store fetched price for %s", t, exc_info=True)
    return {**quote.to_dict(), "provider_label": provider.label, "cached": False}
