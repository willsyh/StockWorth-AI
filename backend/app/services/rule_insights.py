"""Deterministic, rule-based findings and the non-AI insight fallback.

Every finding is derived from a calculated metric or score and names the metrics it
used. Nothing here is AI-generated, and the output is labelled accordingly.
"""

from app.schemas.financials import AnalysisInput, Currency
from app.schemas.results import (
    DataCompleteness,
    Finding,
    InsightContent,
    MetricResult,
    ScoreResult,
)

SECTION_FOR_METRIC = {
    "npm": "profitability",
    "roe": "profitability",
    "roa": "profitability",
    "revenue_growth": "growth",
    "net_income_growth": "growth",
    "der": "leverage_liquidity",
    "current_ratio": "leverage_liquidity",
    "cash_flow_quality": "cash_flow",
    "fcf_margin": "cash_flow",
}


def fmt_number(v: float, decimals: int = 1) -> str:
    """Indonesian formatting: '.' thousands separator, ',' decimal separator."""
    s = f"{v:,.{decimals}f}"
    return s.replace(",", "_").replace(".", ",").replace("_", ".")


def fmt_money(v: float, currency: Currency) -> str:
    sign = "-" if v < 0 else ""
    a = abs(v)
    prefix = "Rp" if currency == Currency.IDR else currency.value
    for size, word in ((1e12, "triliun"), (1e9, "miliar"), (1e6, "juta")):
        if a >= size:
            return f"{sign}{prefix} {fmt_number(a / size, 2)} {word}"
    return f"{sign}{prefix} {fmt_number(a, 0)}"


def fmt_metric(m: MetricResult, currency: Currency) -> str:
    if m.value is None:
        return "Belum tersedia"
    if m.unit == "percent":
        return f"{fmt_number(m.value)}%"
    if m.unit == "ratio":
        return f"{fmt_number(m.value, 2)}x"
    if m.unit == "currency":
        return fmt_money(m.value, currency)
    return f"{fmt_number(m.value, 2)} {currency.value}/saham"


def _strength_word(score: float) -> str:
    if score >= 70:
        return "kuat"
    if score >= 40:
        return "moderat"
    return "lemah"


def build_findings(
    inp: AnalysisInput,
    metrics: dict[str, MetricResult],
    fundamental: ScoreResult,
    valuation: ScoreResult,
    completeness: DataCompleteness,
) -> list[Finding]:
    cur = inp.statement.currency
    out: list[Finding] = []

    def ok(key: str) -> MetricResult | None:
        m = metrics.get(key)
        return m if m and m.status == "ok" and m.value is not None else None

    # Per-metric findings, graded with the same bands as the score (keeps them consistent).
    for dim in fundamental.dimensions:
        for ms in dim.metrics:
            m = metrics.get(ms.metric)
            if ms.score is None or m is None or m.value is None:
                continue
            section = SECTION_FOR_METRIC.get(ms.metric, "summary")
            word = _strength_word(ms.score)
            severity = "positive" if ms.score >= 70 else "neutral" if ms.score >= 40 else "warning"
            if m.value < 0 and m.unit == "percent":
                severity = "negative" if ms.score < 40 else "warning"
            annual = " (disetahunkan untuk penilaian)" if m.annualized_value is not None else ""
            out.append(Finding(
                section=section, severity=severity, metrics=[ms.metric],
                text=f"{m.label} sebesar {fmt_metric(m, cur)}{annual}, tergolong {word} menurut ambang profil penilaian.",
            ))

    npm, roe = ok("npm"), ok("roe")
    der_m = metrics.get("der")
    rev_g, ni_g = ok("revenue_growth"), ok("net_income_growth")
    ocf, fcf, cfq = ok("operating_cash_flow"), ok("free_cash_flow"), ok("cash_flow_quality")
    cr = ok("current_ratio")

    # Risk rules
    if npm and npm.value < 0:
        out.append(Finding(section="risk", severity="negative", metrics=["npm"],
                           text="Perusahaan mencatat rugi bersih pada periode ini."))
    if der_m and der_m.status == "not_meaningful":
        out.append(Finding(section="risk", severity="negative", metrics=["der"],
                           text="Ekuitas nol atau negatif (defisiensi modal). Ini risiko solvabilitas yang serius."))
    if rev_g and ni_g and rev_g.value > 0 and ni_g.value < 0:
        out.append(Finding(section="growth", severity="warning", metrics=["revenue_growth", "net_income_growth"],
                           text="Pendapatan tumbuh tetapi laba menurun, menandakan margin yang tertekan."))
    if rev_g and ni_g and rev_g.value < 0 and ni_g.value < 0:
        out.append(Finding(section="risk", severity="negative", metrics=["revenue_growth", "net_income_growth"],
                           text="Pendapatan dan laba sama-sama menurun dibanding periode pembanding."))
    ni_growth_m = metrics.get("net_income_growth")
    if ni_growth_m and ni_growth_m.status == "not_meaningful" and ni_growth_m.explanation:
        out.append(Finding(section="growth", severity="neutral", metrics=["net_income_growth"],
                           text=ni_growth_m.explanation))
    if ocf and ocf.value < 0:
        out.append(Finding(section="risk", severity="negative", metrics=["operating_cash_flow"],
                           text=f"Arus kas operasi negatif ({fmt_metric(ocf, cur)}): operasi belum menghasilkan kas."))
    if cfq and cfq.value < 0.5:
        out.append(Finding(section="cash_flow", severity="warning", metrics=["cash_flow_quality"],
                           text="Arus kas operasi jauh di bawah laba bersih; sebagian laba belum terealisasi menjadi kas. "
                                "Periksa piutang, persediaan, dan pos non-kas."))
    if fcf and fcf.value < 0:
        out.append(Finding(section="cash_flow", severity="warning", metrics=["free_cash_flow"],
                           text=f"Free cash flow negatif ({fmt_metric(fcf, cur)}). Bisa wajar saat ekspansi, "
                                "tetapi berarti investasi belum didanai sepenuhnya dari operasi."))
    if cr and cr.value < 1:
        out.append(Finding(section="risk", severity="warning", metrics=["current_ratio"],
                           text="Current ratio di bawah 1: aset lancar lebih kecil dari liabilitas jangka pendek."))

    # Valuation observations (never "cheap" just because a multiple is low)
    per, pbv = ok("per"), ok("pbv")
    if per:
        out.append(Finding(section="valuation", severity="neutral", metrics=["per"],
                           text=f"PER {fmt_metric(per, cur)} berdasarkan harga per {inp.market.share_price_date}."))
        per_score = next((s.score for d in valuation.dimensions for s in d.metrics if s.metric == "per"), None)
        weak_fundamentals = (ni_g is not None and ni_g.value < -10) or (
            fundamental.score is not None and fundamental.score < 50)
        if per_score is not None and per_score >= 70 and weak_fundamentals:
            out.append(Finding(section="valuation", severity="warning", metrics=["per", "net_income_growth"],
                               text="PER relatif rendah, tetapi disertai laba yang turun atau fundamental yang lemah. "
                                    "PER rendah bisa mencerminkan ekspektasi pasar yang menurun (potensi value trap)."))
    if pbv:
        out.append(Finding(section="valuation", severity="neutral", metrics=["pbv"],
                           text=f"PBV {fmt_metric(pbv, cur)}."))
        if pbv.value < 1:
            out.append(Finding(section="valuation", severity="neutral", metrics=["pbv"],
                               text="Harga di bawah nilai buku. Ini bisa mencerminkan ROE rendah, kualitas aset yang "
                                    "diragukan, atau risiko lain, bukan otomatis murah."))
        if roe and pbv.value > 3 and roe.value < 10:
            out.append(Finding(section="valuation", severity="warning", metrics=["pbv", "roe"],
                               text="PBV tinggi tetapi ROE relatif rendah; harga mungkin sudah mengasumsikan "
                                    "perbaikan profitabilitas yang signifikan."))
    if valuation.status == "unavailable":
        out.append(Finding(section="valuation", severity="neutral", metrics=["per", "pbv"],
                           text="Valuasi belum dapat dinilai karena data harga atau per-saham belum lengkap."))

    for mf in completeness.missing:
        out.append(Finding(section="missing", severity="neutral", metrics=[],
                           text=f"{mf.label} — dibutuhkan untuk: {', '.join(mf.blocks)}."))

    # Summary
    if fundamental.score is not None:
        prefix = "sementara " if fundamental.status == "provisional" else ""
        out.insert(0, Finding(section="summary", severity="neutral", metrics=[],
                              text=f"Skor fundamental {prefix}{fmt_number(fundamental.score, 0)}/100 ({fundamental.label}) "
                                   f"dengan cakupan data {fmt_number(fundamental.coverage * 100, 0)}%."))
    else:
        out.insert(0, Finding(section="summary", severity="warning", metrics=[],
                              text="Data belum cukup untuk menerbitkan skor fundamental keseluruhan."))
    return out


LIMITATIONS = [
    "Analisis hanya didasarkan pada angka yang Anda masukkan atau impor; angka tersebut belum diverifikasi terhadap laporan resmi.",
    "Ambang dan bobot skor adalah heuristik sementara, bukan standar investasi yang tervalidasi.",
    "Tidak ada perbandingan dengan emiten sejenis, data pasar langsung, atau berita perusahaan.",
    "Hasil ini adalah alat bantu analisis, bukan rekomendasi beli/jual atau jaminan imbal hasil.",
]


def rule_based_insight(
    findings: list[Finding], fundamental: ScoreResult, valuation: ScoreResult, inp: AnalysisInput
) -> InsightContent:
    strengths = [f.text for f in findings if f.severity == "positive"]
    risks = [f.text for f in findings if f.severity in ("negative", "warning") and f.section != "valuation"]
    valuation_obs = [f.text for f in findings if f.section == "valuation"]
    missing = [f.text for f in findings if f.section == "missing"]
    summary = next((f.text for f in findings if f.section == "summary"), "")
    name = f"{inp.company.ticker} ({inp.company.name})"
    if fundamental.score is None:
        conclusion = (
            f"Belum ada kesimpulan yang dapat ditarik untuk {name}: data inti belum cukup. "
            "Lengkapi data yang dibutuhkan terlebih dahulu."
        )
    else:
        val = (
            f"Valuasi {valuation.label.lower()} (skor {fmt_number(valuation.score, 0)}/100)."
            if valuation.score is not None and valuation.label else "Valuasi belum dapat dinilai."
        )
        conclusion = (
            f"Berdasarkan data yang tersedia, kualitas fundamental {name} tergolong "
            f"{fundamental.label.lower()} ({'sementara' if fundamental.status != 'complete' else 'cakupan lengkap'}). "
            f"{val} Pertimbangkan risiko dan data yang masih kurang sebelum mengambil keputusan."
        )
    return InsightContent(
        summary=summary,
        strengths=strengths,
        risks=risks,
        valuation_observations=valuation_obs,
        missing_information=missing,
        conclusion=conclusion,
        limitations=LIMITATIONS,
    )
