"""Transparent scoring and data completeness.

Fundamental score (company quality) and valuation score (price attractiveness versus
configured reference bands) are computed separately and never blended.

* Each metric is scored 0-100 on a linear band from the sector profile.
* A dimension's score is the mean of its scored metrics; unscored metrics lower the
  dimension's coverage instead of counting as zero.
* The overall score uses the dimension weights, renormalised over dimensions that have
  data. If weighted coverage is below `min_coverage_for_score`, or profitability has no
  data, no overall score is issued.
"""

from app.schemas.financials import FIELD_LABELS, AnalysisInput, Basis
from app.schemas.results import (
    DataCompleteness,
    DimensionScore,
    MetricResult,
    MetricScore,
    MissingField,
    ScoreResult,
)
from app.services.calculator import FINANCIAL_SECTORS, METRIC_LABELS, check_comparability
from app.services.scoring_config import get_scoring_config, resolve_profile


def band_score(value: float, band: dict) -> float:
    worst, best = float(band["worst"]), float(band["best"])
    if worst == best:
        return 100.0 if value >= best else 0.0
    t = (value - worst) / (best - worst)
    return round(max(0.0, min(1.0, t)) * 100, 1)


def _band_rule(band: dict) -> str:
    worst, best = band["worst"], band["best"]
    direction = "lebih rendah lebih baik" if worst > best else "lebih tinggi lebih baik"
    return f"Linear: {worst} → skor 0, {best} → skor 100 ({direction})"


def _label(score: float | None, labels: list) -> str | None:
    if score is None:
        return None
    for threshold, text in labels:
        if score >= threshold:
            return text
    return labels[-1][1]


def _score_metric(key: str, m: MetricResult | None, band: dict) -> MetricScore:
    label = METRIC_LABELS.get(key, key)
    rule = _band_rule(band)
    if m is None:
        return MetricScore(metric=key, label=label, score=None, rule=rule, note="Metrik tidak tersedia.")
    # Negative equity is a measured, adverse condition (not missing data): DER scores 0, explicitly.
    if key == "der" and m.status == "not_meaningful":
        return MetricScore(metric=key, label=label, score=0.0, rule=rule,
                           note="Ekuitas nol/negatif: skor leverage 0 sebagai sinyal risiko.")
    if m.status != "ok" or m.value is None:
        return MetricScore(metric=key, label=label, score=None, rule=rule,
                           note=m.explanation or "Belum tersedia.")
    value = m.annualized_value if m.annualized_value is not None else m.value
    note = "Menggunakan nilai yang disetahunkan." if m.annualized_value is not None else None
    return MetricScore(metric=key, label=label, score=band_score(value, band), basis_value=value, rule=rule, note=note)


def score_fundamentals(metrics: dict[str, MetricResult], sector: str | None) -> tuple[ScoreResult, str]:
    cfg = get_scoring_config()
    profile_name, profile = resolve_profile(cfg, sector)
    na_dims = set(profile.get("not_applicable_dimensions", []))
    dims: list[DimensionScore] = []
    for dkey, metric_keys in cfg["dimensions"].items():
        weight = cfg["weights"][dkey]
        label = cfg["dimension_labels"][dkey]
        if dkey in na_dims:
            dims.append(DimensionScore(key=dkey, label=label, weight=weight, applicable=False, score=None,
                                       coverage=0.0, metrics=[],
                                       note=f"Tidak diterapkan untuk profil {profile['label']}."))
            continue
        scored = [_score_metric(k, metrics.get(k), profile["bands"][k]) for k in metric_keys]
        # Metrics that are structurally not applicable (e.g. sector rules) are excluded from coverage.
        applicable = [s for s, k in zip(scored, metric_keys) if not (metrics.get(k) and metrics[k].status == "not_applicable")]
        values = [s.score for s in applicable if s.score is not None]
        coverage = len(values) / len(applicable) if applicable else 0.0
        dims.append(DimensionScore(
            key=dkey, label=label, weight=weight, applicable=bool(applicable),
            score=round(sum(values) / len(values), 1) if values else None,
            coverage=round(coverage, 3), metrics=scored,
            note=None if values else "Belum ada metrik yang dapat dinilai pada dimensi ini.",
        ))

    applicable_dims = [d for d in dims if d.applicable]
    total_weight = sum(d.weight for d in applicable_dims)
    with_data = [d for d in applicable_dims if d.score is not None]
    coverage = (sum(d.weight * d.coverage for d in applicable_dims) / total_weight) if total_weight else 0.0
    notes = [
        "Bobot dan ambang batas adalah heuristik MVP sementara, bukan ambang investasi yang tervalidasi secara empiris.",
        f"Profil penilaian: {profile['label']}.",
    ]
    if na_dims:
        notes.append("Dimensi yang tidak diterapkan dikeluarkan dan bobot dinormalisasi ulang.")

    profitability = next((d for d in dims if d.key == "profitability"), None)
    if not with_data:
        return ScoreResult(score=None, status="unavailable", label=None, coverage=round(coverage, 3),
                           dimensions=dims, notes=notes + ["Belum ada data yang cukup untuk memberi skor."]), profile_name
    if coverage < cfg["min_coverage_for_score"] or profitability is None or profitability.score is None:
        reason = (
            "Dimensi profitabilitas belum memiliki data." if profitability is None or profitability.score is None
            else f"Cakupan data {coverage * 100:.0f}% di bawah batas minimum {cfg['min_coverage_for_score'] * 100:.0f}%."
        )
        return ScoreResult(score=None, status="insufficient", label=None, coverage=round(coverage, 3),
                           dimensions=dims, notes=notes + [f"Skor keseluruhan tidak diterbitkan: {reason}"]), profile_name

    w = sum(d.weight for d in with_data)
    score = round(sum(d.weight * d.score for d in with_data) / w, 1)
    status = "complete" if coverage >= cfg["complete_coverage"] else "provisional"
    if status == "provisional":
        notes.append(f"Skor bersifat sementara karena cakupan data {coverage * 100:.0f}%.")
    if sector == "financials_bank":
        status = "provisional"
        notes.append("Untuk bank, skor bersifat sementara karena metrik khusus bank (CAR, NPL, LDR, NIM) belum didukung.")
    return ScoreResult(score=score, status=status, label=_label(score, cfg["fundamental_labels"]),
                       coverage=round(coverage, 3), dimensions=dims, notes=notes), profile_name


def score_valuation(metrics: dict[str, MetricResult], inp: AnalysisInput, stale_price: bool) -> ScoreResult:
    cfg = get_scoring_config()
    _, profile = resolve_profile(cfg, inp.company.sector.value if inp.company.sector else None)
    bands = profile["valuation"]
    scored = [_score_metric(k, metrics.get(k), bands[k]) for k in ("per", "pbv")]
    values = [s.score for s in scored if s.score is not None]
    notes = [
        "Skor valuasi hanya membandingkan PER/PBV dengan rentang acuan yang dapat dikonfigurasi; "
        "ini bukan estimasi nilai wajar dan bukan perbandingan dengan emiten sejenis.",
        "PER atau PBV yang rendah tidak otomatis berarti saham murah: bisa mencerminkan prospek atau risiko yang lemah.",
    ]
    dim = DimensionScore(key="valuation", label="Valuasi", weight=1.0, applicable=True,
                         score=round(sum(values) / len(values), 1) if values else None,
                         coverage=len(values) / 2, metrics=scored)
    if not values:
        return ScoreResult(score=None, status="unavailable", label=None, coverage=0.0, dimensions=[dim],
                           notes=notes + ["Skor valuasi membutuhkan harga saham beserta tanggalnya serta PER atau PBV yang valid."])
    score = dim.score
    status = "complete" if len(values) == 2 and not stale_price else "provisional"
    if len(values) < 2:
        notes.append("Hanya satu dari PER/PBV yang tersedia; skor bersifat sementara.")
    if stale_price:
        notes.append("Harga saham lebih dari 90 hari; skor bersifat sementara.")
    return ScoreResult(score=score, status=status, label=_label(score, cfg["valuation_labels"]),
                       coverage=dim.coverage, dimensions=[dim], notes=notes)


# --- Data completeness ---------------------------------------------------------------

def compute_completeness(inp: AnalysisInput) -> DataCompleteness:
    cur = inp.current
    prev = inp.previous.values if inp.previous else None
    is_fin = inp.company.sector in FINANCIAL_SECTORS
    is_bank = inp.company.sector is not None and inp.company.sector.value == "financials_bank"
    annual_comparable = inp.statement.basis == Basis.annual and check_comparability(inp)["comparable"]

    def begin_ok(begin_field: str, end_field: str) -> bool:
        if getattr(cur, begin_field) is not None:
            return True
        return bool(annual_comparable and prev is not None and getattr(prev, end_field) is not None)

    # (key, label, provided?, blocked metrics, applicable?)
    reqs = [
        ("revenue", FIELD_LABELS["revenue"], cur.revenue is not None, ["npm", "revenue_growth", "fcf_margin"], True),
        ("net_income", "Laba bersih", cur.net_income is not None or cur.net_income_attributable is not None,
         ["npm", "roe", "roa", "eps", "per", "cash_flow_quality"], True),
        ("total_assets", FIELD_LABELS["total_assets"], cur.total_assets is not None, ["roa"], True),
        ("total_assets_begin", FIELD_LABELS["total_assets_begin"], begin_ok("total_assets_begin", "total_assets"), ["roa"], True),
        ("total_liabilities", FIELD_LABELS["total_liabilities"], cur.total_liabilities is not None, ["der"], not is_bank),
        ("total_equity", "Ekuitas (akhir periode)", cur.total_equity is not None or cur.equity_attributable is not None,
         ["roe", "der", "bvps", "pbv"], True),
        ("total_equity_begin", "Ekuitas (awal periode)",
         begin_ok("total_equity_begin", "total_equity") or begin_ok("equity_attributable_begin", "equity_attributable"),
         ["roe"], True),
        ("current_assets", FIELD_LABELS["current_assets"], cur.current_assets is not None, ["current_ratio"], not is_fin),
        ("current_liabilities", FIELD_LABELS["current_liabilities"], cur.current_liabilities is not None, ["current_ratio"], not is_fin),
        ("operating_cash_flow", FIELD_LABELS["operating_cash_flow"], cur.operating_cash_flow is not None,
         ["operating_cash_flow", "free_cash_flow", "cash_flow_quality"], True),
        ("capital_expenditure", FIELD_LABELS["capital_expenditure"], cur.capital_expenditure is not None,
         ["free_cash_flow", "fcf_margin"], True),
        ("weighted_average_shares", FIELD_LABELS["weighted_average_shares"], cur.weighted_average_shares is not None,
         ["eps", "per"], True),
        ("shares_outstanding", FIELD_LABELS["shares_outstanding"], cur.shares_outstanding is not None, ["bvps", "pbv"], True),
        ("share_price", "Harga saham & tanggal", inp.market.share_price is not None, ["per", "pbv"], True),
        ("previous.revenue", "Pendapatan periode pembanding", prev is not None and prev.revenue is not None,
         ["revenue_growth"], True),
        ("previous.net_income", "Laba bersih periode pembanding",
         prev is not None and (prev.net_income is not None or prev.net_income_attributable is not None),
         ["net_income_growth"], True),
    ]
    applicable = [r for r in reqs if r[4]]
    provided = sum(1 for r in applicable if r[2])
    missing = [
        MissingField(field=r[0], label=r[1], blocks=[METRIC_LABELS[m] for m in r[3]])
        for r in applicable if not r[2]
    ]
    pct = round(provided / len(applicable) * 100, 1) if applicable else 0.0
    return DataCompleteness(percent=pct, provided=provided, applicable=len(applicable), missing=missing)
