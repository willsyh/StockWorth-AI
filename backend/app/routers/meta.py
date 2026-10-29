"""Health, configuration status and methodology endpoints (public, no secrets)."""

from fastapi import APIRouter

from app.core.config import get_settings
from app.schemas.financials import FIELD_LABELS, SECTOR_LABELS
from app.services.calculator import METHODOLOGY_VERSION, METRIC_LABELS
from app.services.scoring_config import get_scoring_config

router = APIRouter(prefix="/api", tags=["meta"])

APP_VERSION = "0.1.0"


@router.get("/health")
def health() -> dict:
    s = get_settings()
    return {
        "status": "ok",
        "version": APP_VERSION,
        "methodology_version": METHODOLOGY_VERSION,
        "storage": "supabase" if s.supabase_enabled else "local",
        "auth_required": s.supabase_enabled,
        "ai": {
            "configured": s.ai_configured,
            "provider": s.ai_provider if s.ai_configured else None,
            "model": s.ai_model_name if s.ai_configured else None,
        },
        "market_data": {
            "configured": s.market_data_configured,
            "provider": s.market_data_provider if s.market_data_configured else None,
            "coverage_note": "Hanya kode BEI (.JK) dalam IDR yang diterima.",
        },
        "max_upload_mb": round(s.max_upload_bytes / (1024 * 1024), 1),
        "max_pdf_upload_mb": round(s.max_pdf_upload_bytes / (1024 * 1024), 1),
    }


@router.get("/methodology")
def methodology() -> dict:
    return {
        "methodology_version": METHODOLOGY_VERSION,
        "scoring": get_scoring_config(),
        "metric_labels": METRIC_LABELS,
        "field_labels": FIELD_LABELS,
        "sectors": {k.value: v for k, v in SECTOR_LABELS.items()},
    }
