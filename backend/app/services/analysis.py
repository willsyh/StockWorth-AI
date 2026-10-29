"""Orchestrates validation, calculation, scoring and findings into one AnalysisResult."""

from datetime import date

from app.core.errors import AppError
from app.schemas.financials import UNIT_MULTIPLIER, AnalysisInput
from app.schemas.results import AnalysisResult
from app.services.calculator import (
    FINANCIAL_SECTORS,
    METHODOLOGY_VERSION,
    calculate_metrics,
    check_comparability,
    normalize,
    validate_input,
)
from app.services.rule_insights import build_findings
from app.services.scoring import compute_completeness, score_fundamentals, score_valuation

DISCLAIMER = (
    "StockWorth AI adalah alat bantu analisis fundamental, bukan nasihat investasi. Hasil dihitung "
    "dari data yang Anda berikan dan tidak menjamin imbal hasil atau memprediksi harga saham. "
    "Lakukan riset mandiri dan pertimbangkan profil risiko Anda."
)


def run_analysis(inp: AnalysisInput, today: date | None = None) -> AnalysisResult:
    issues = validate_input(inp, today=today)
    errors = [i for i in issues if i.level == "error"]
    if errors:
        raise AppError(
            422,
            "validation_error",
            "Data belum dapat dianalisis.",
            [{"field": e.field, "message": e.message} for e in errors],
        )
    metrics = calculate_metrics(inp)
    sector = inp.company.sector.value if inp.company.sector else None
    fundamental, profile = score_fundamentals(metrics, sector)
    today = today or date.today()
    stale = bool(inp.market.share_price_date and (today - inp.market.share_price_date).days > 90)
    valuation = score_valuation(metrics, inp, stale_price=stale)
    completeness = compute_completeness(inp)
    findings = build_findings(inp, metrics, fundamental, valuation, completeness)
    return AnalysisResult(
        methodology_version=METHODOLOGY_VERSION,
        scoring_profile=profile,
        period_label=inp.statement.label,
        months_covered=inp.statement.months,
        is_financial_sector=inp.company.sector in FINANCIAL_SECTORS,
        metrics=metrics,
        fundamental_score=fundamental,
        valuation_score=valuation,
        completeness=completeness,
        findings=findings,
        issues=issues,
        comparability=check_comparability(inp),
        normalized={
            "currency": inp.statement.currency.value,
            "current": normalize(inp.current, UNIT_MULTIPLIER[inp.statement.unit]),
            "previous": (
                {
                    "fiscal_year": inp.previous.fiscal_year,
                    "period": inp.previous.period.value,
                    "values": normalize(inp.previous.values, UNIT_MULTIPLIER[inp.statement.unit]),
                }
                if inp.previous else None
            ),
        },
        disclaimer=DISCLAIMER,
    )
