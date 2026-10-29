"""Authentication.

* Supabase mode: private endpoints require `Authorization: Bearer <access token>`.
  The token is verified by Supabase Auth (`GET /auth/v1/user`), which works for both
  legacy HS256 and asymmetric JWT signing keys. The user id always comes from the
  verified token, never from the request body.
* Local mode (Supabase not configured, non-production only): one fixed local user,
  so the app is usable for local development without any credentials.
"""

import threading
import time
from dataclasses import dataclass

import httpx
from fastapi import Request

from app.core.config import Settings, get_settings
from app.core.errors import AppError

LOCAL_USER_ID = "00000000-0000-0000-0000-000000000001"
_CACHE_TTL = 60.0


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str | None
    access_token: str | None  # forwarded to Supabase so RLS policies apply
    is_local: bool = False


_cache: dict[str, tuple[float, CurrentUser]] = {}
_cache_lock = threading.Lock()


def _verify_supabase_token(token: str, settings: Settings) -> CurrentUser:
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(token)
        if hit and now - hit[0] < _CACHE_TTL:
            return hit[1]
    try:
        resp = httpx.get(
            f"{settings.supabase_url.rstrip('/')}/auth/v1/user",
            headers={"Authorization": f"Bearer {token}", "apikey": settings.supabase_anon_key},
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        raise AppError(503, "auth_unavailable", "Layanan autentikasi tidak dapat dihubungi.") from exc
    if resp.status_code != 200:
        raise AppError(401, "unauthorized", "Sesi tidak valid atau sudah berakhir. Silakan masuk kembali.")
    data = resp.json()
    user = CurrentUser(id=data["id"], email=data.get("email"), access_token=token)
    with _cache_lock:
        if len(_cache) > 1000:
            _cache.clear()
        _cache[token] = (now, user)
    return user


def get_current_user(request: Request) -> CurrentUser:
    settings = get_settings()
    if not settings.supabase_enabled:
        if settings.is_production:
            raise AppError(503, "storage_not_configured", "Penyimpanan belum dikonfigurasi di server.")
        return CurrentUser(id=LOCAL_USER_ID, email=None, access_token=None, is_local=True)

    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("bearer "):
        raise AppError(401, "unauthorized", "Silakan masuk untuk melanjutkan.")
    token = header[7:].strip()
    if not token:
        raise AppError(401, "unauthorized", "Silakan masuk untuk melanjutkan.")
    return _verify_supabase_token(token, settings)
