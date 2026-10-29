"""Analysis endpoints."""

import uuid
from typing import Literal

from fastapi.concurrency import run_in_threadpool
from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile

from app.core.auth import CurrentUser, get_current_user
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.rate_limit import RateLimiter
from app.schemas.financials import AnalysisInput
from app.schemas.results import AnalysisResult
from app.services import importer
from app.services.ai_insights import generate_insight, get_provider
from app.services.analysis import run_analysis
from app.services.market_data import quote_cache
from app.services.repository import get_repository, summary_from_record

router = APIRouter(prefix="/api/analysis", tags=["analysis"])

_import_limiter = RateLimiter(limit=30, window_seconds=60)
_calc_limiter = RateLimiter(limit=120, window_seconds=60)
_insight_limiter = RateLimiter(limit=get_settings().ai_rate_limit_per_hour, window_seconds=3600)


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _repo():
    return get_repository(get_settings())


def _verify_price_origin(payload: AnalysisInput) -> AnalysisInput:
    """A price is only labelled as provider-sourced if this server actually fetched it.
    Anything else (edited price, forged claim, server restart) is stored as manual."""
    m = payload.market
    if m.price_origin != "provider":
        return payload.model_copy(update={"market": m.model_copy(update={
            "price_provider": None, "price_provider_symbol": None, "price_fetched_at": None})})
    q = None
    if m.share_price is not None and m.share_price_date is not None:
        q = quote_cache.issued(payload.company.ticker, m.share_price_date.isoformat(), m.share_price)
    if q is None:
        market = m.model_copy(update={
            "price_origin": "manual", "price_provider": None, "price_provider_symbol": None, "price_fetched_at": None})
    else:
        market = m.model_copy(update={
            "price_provider": q.provider, "price_provider_symbol": q.provider_symbol, "price_fetched_at": q.fetched_at})
    return payload.model_copy(update={"market": market})


def _check_uuid(analysis_id: str) -> str:
    try:
        return str(uuid.UUID(analysis_id))
    except ValueError as exc:
        raise AppError(404, "not_found", "Analisis tidak ditemukan.") from exc


@router.post("/calculate", response_model=AnalysisResult, summary="Hitung metrik tanpa menyimpan")
def calculate(payload: AnalysisInput, request: Request) -> AnalysisResult:
    _calc_limiter.check(_client_key(request))
    return run_analysis(payload)


@router.post("", status_code=201, summary="Hitung dan simpan analisis")
def create_analysis(payload: AnalysisInput, user: CurrentUser = Depends(get_current_user)) -> dict:
    payload = _verify_price_origin(payload)
    # Always recalculate on the server; a client-provided result is never trusted.
    result = run_analysis(payload)
    record = {
        "ticker": payload.company.ticker,
        "company_name": payload.company.name,
        "sector": payload.company.sector.value if payload.company.sector else None,
        "fiscal_year": payload.statement.fiscal_year,
        "period": payload.statement.period.value,
        "basis": payload.statement.basis.value,
        "period_label": payload.statement.label,
        "methodology_version": result.methodology_version,
        "input": payload.model_dump(mode="json"),
        "result": result.model_dump(mode="json"),
    }
    return _repo().create(user, record)


@router.get("", summary="Daftar analisis milik pengguna")
def list_analyses(
    q: str | None = Query(None, max_length=80),
    ticker: str | None = Query(None, pattern=r"^[A-Za-z]{4}$"),
    fiscal_year: int | None = Query(None, ge=1990, le=2100),
    period: Literal["FY", "Q1", "Q2", "Q3", "Q4"] | None = None,
    sort: Literal["asc", "desc"] = "desc",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    rows, total = _repo().list(
        user, q=q.strip() if q else None, ticker=ticker.upper() if ticker else None,
        fiscal_year=fiscal_year, period=period, sort=sort, limit=limit, offset=offset,
    )
    return {"items": [summary_from_record(r) for r in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/stats", summary="Ringkasan jumlah analisis")
def stats(user: CurrentUser = Depends(get_current_user)) -> dict:
    return _repo().stats(user)


@router.get("/import/template", summary="Unduh templat impor")
def download_template(format: Literal["csv", "xlsx"] = "xlsx") -> Response:
    if format == "csv":
        return Response(importer.template_csv(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="stockworth_template.csv"'})
    return Response(
        importer.template_xlsx(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="stockworth_template.xlsx"'},
    )


@router.post("/import", summary="Impor PDF/CSV/XLSX/XLS untuk pratinjau (tidak menyimpan)")
async def import_file(request: Request, file: UploadFile = File(...)) -> dict:
    _import_limiter.check(_client_key(request))
    settings = get_settings()
    limit = max(settings.max_upload_bytes, settings.max_pdf_upload_bytes)
    content = await file.read(limit + 1)
    # PDF parsing is CPU-bound; run it off the event loop.
    return await run_in_threadpool(
        importer.parse_upload, content, file.filename, settings.max_upload_bytes, settings.max_pdf_upload_bytes
    )


@router.get("/{analysis_id}", summary="Detail analisis")
def get_analysis(analysis_id: str, user: CurrentUser = Depends(get_current_user)) -> dict:
    analysis_id = _check_uuid(analysis_id)
    repo = _repo()
    rec = repo.get(user, analysis_id)
    if rec is None:
        raise AppError(404, "not_found", "Analisis tidak ditemukan.")
    rec["latest_insight"] = repo.latest_insight(user, analysis_id)
    return rec


@router.delete("/{analysis_id}", status_code=204, summary="Hapus analisis")
def delete_analysis(analysis_id: str, user: CurrentUser = Depends(get_current_user)) -> Response:
    analysis_id = _check_uuid(analysis_id)
    if not _repo().delete(user, analysis_id):
        raise AppError(404, "not_found", "Analisis tidak ditemukan.")
    return Response(status_code=204)


@router.post("/{analysis_id}/insights", status_code=201, summary="Buat insight (AI atau berbasis aturan)")
def create_insight(analysis_id: str, user: CurrentUser = Depends(get_current_user)) -> dict:
    analysis_id = _check_uuid(analysis_id)
    repo = _repo()
    rec = repo.get(user, analysis_id)
    if rec is None:
        raise AppError(404, "not_found", "Analisis tidak ditemukan.")
    settings = get_settings()
    provider = get_provider(settings)
    if provider is not None:
        _insight_limiter.check(user.id)
    inp = AnalysisInput.model_validate(rec["input"])
    result = AnalysisResult.model_validate(rec["result"])
    insight = generate_insight(inp, result, provider)
    insight["analysis_id"] = analysis_id
    return repo.save_insight(user, insight)
