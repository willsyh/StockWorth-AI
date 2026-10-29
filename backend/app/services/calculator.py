"""Financial calculation engine.

Rules this module enforces:
* Missing inputs produce `status="unavailable"` with an explanation. Never zero.
* Zero/negative denominators produce `status="not_meaningful"` instead of a number.
* Average balances need both the beginning and ending balance. Ending balances are
  never silently used as a stand-in for an average.
* Values are normalised from the statement unit (ribu/juta/miliar) to whole currency
  units before any ratio is computed. Per-share valuation converts to IDR using the
  user-supplied FX rate when the statement is not in IDR.
* Growth is only computed against a comparable period (same basis, same period,
  previous fiscal year).
* Any assumption that is applied (e.g. using total equity because equity attributable
  to the parent was not given) is recorded on the metric, never applied silently.
"""

from datetime import date

from app.schemas.financials import (
    FIELD_LABELS,
    MONETARY_FIELDS,
    UNIT_MULTIPLIER,
    AnalysisInput,
    Basis,
    Currency,
    FinancialValues,
    Sector,
    period_label,
)
from app.schemas.results import MetricResult, ValidationIssue

METHODOLOGY_VERSION = "1.0.0"

BANK_SECTORS = {Sector.financials_bank}
FINANCIAL_SECTORS = {Sector.financials_bank, Sector.financials_non_bank}

METRIC_LABELS = {
    "npm": "Net Profit Margin (NPM)",
    "roe": "Return on Equity (ROE)",
    "roa": "Return on Assets (ROA)",
    "der": "Debt to Equity Ratio (DER)",
    "current_ratio": "Current Ratio",
    "revenue_growth": "Pertumbuhan Pendapatan",
    "net_income_growth": "Pertumbuhan Laba Bersih",
    "eps": "Earnings per Share (EPS)",
    "per": "Price to Earnings Ratio (PER)",
    "bvps": "Book Value per Share (BVPS)",
    "pbv": "Price to Book Value (PBV)",
    "operating_cash_flow": "Arus Kas Operasi",
    "free_cash_flow": "Free Cash Flow (FCF)",
    "fcf_margin": "Margin Free Cash Flow",
    "cash_flow_quality": "Kualitas Arus Kas (OCF / Laba Bersih)",
}

SHARE_CLASS_ASSUMPTION = (
    "Diasumsikan seluruh saham beredar adalah saham biasa satu kelas dan jumlahnya "
    "sudah dikurangi saham treasuri."
)


def normalize(values: FinancialValues, multiplier: float) -> dict[str, float | None]:
    """Scale monetary values to whole currency units. Share counts are not scaled."""
    out: dict[str, float | None] = {}
    for name, raw in values.model_dump().items():
        if raw is None:
            out[name] = None
        elif name in MONETARY_FIELDS:
            out[name] = raw * multiplier
        else:
            out[name] = raw
    return out


def _missing(fields: list[str], data: dict[str, float | None]) -> list[str]:
    return [f for f in fields if data.get(f) is None]


def _missing_text(fields: list[str]) -> str:
    names = ", ".join(FIELD_LABELS.get(f, f) for f in fields)
    return f"Belum tersedia: {names} belum diisi."


class _Builder:
    """Collects metric results in a consistent shape."""

    def __init__(self):
        self.metrics: dict[str, MetricResult] = {}

    def add(self, key: str, unit: str, formula: str, **kw) -> MetricResult:
        m = MetricResult(key=key, label=METRIC_LABELS[key], unit=unit, formula=formula, **kw)
        self.metrics[key] = m
        return m

    def unavailable(self, key, unit, formula, missing: list[str], extra: str | None = None):
        text = _missing_text(missing)
        if extra:
            text = f"{text} {extra}"
        return self.add(key, unit, formula, status="unavailable", explanation=text, inputs_used=missing)


def check_comparability(inp: AnalysisInput) -> dict:
    """Is the previous period a valid year-over-year comparison for the current one?"""
    st = inp.statement
    prev = inp.previous
    if prev is None:
        return {"comparable": False, "previous_label": None, "reason": "Data periode sebelumnya belum diisi."}
    prev_label = period_label(prev.fiscal_year, prev.period, st.basis)
    if prev.fiscal_year != st.fiscal_year - 1:
        return {
            "comparable": False,
            "previous_label": prev_label,
            "reason": (
                f"Periode pembanding ({prev_label}) bukan tahun fiskal sebelumnya "
                f"({st.fiscal_year - 1}). Pertumbuhan hanya dihitung secara year-over-year."
            ),
        }
    if prev.period != st.period:
        return {
            "comparable": False,
            "previous_label": prev_label,
            "reason": (
                f"Periode pembanding ({prev.period.value}) berbeda dengan periode berjalan "
                f"({st.period.value}). Gunakan periode yang sama dari tahun sebelumnya."
            ),
        }
    return {"comparable": True, "previous_label": prev_label, "reason": None}


def validate_input(inp: AnalysisInput, today: date | None = None) -> list[ValidationIssue]:
    """Consistency checks. Errors block the analysis; warnings are shown for review."""
    today = today or date.today()
    issues: list[ValidationIssue] = []
    cur = inp.current
    st = inp.statement
    mult = UNIT_MULTIPLIER[st.unit]

    def warn(field, msg):
        issues.append(ValidationIssue(level="warning", field=field, message=msg))

    if cur.revenue is None and cur.net_income is None and cur.net_income_attributable is None:
        issues.append(
            ValidationIssue(
                level="error",
                field="current.revenue",
                message="Isi minimal pendapatan atau laba bersih agar analisis dapat dilakukan.",
            )
        )

    a, li, eq = cur.total_assets, cur.total_liabilities, cur.total_equity
    if a is not None and li is not None and eq is not None and a > 0:
        diff = abs(a - (li + eq)) / a
        if diff > 0.02:
            warn(
                "current.total_assets",
                f"Total aset tidak sama dengan liabilitas + ekuitas (selisih {diff * 100:.1f}%). "
                "Periksa kembali angka neraca dan satuannya.",
            )
    if a is not None and cur.current_assets is not None and cur.current_assets > a:
        warn("current.current_assets", "Aset lancar lebih besar dari total aset — kemungkinan salah input.")
    if li is not None and cur.current_liabilities is not None and cur.current_liabilities > li:
        warn(
            "current.current_liabilities",
            "Liabilitas jangka pendek lebih besar dari total liabilitas — kemungkinan salah input.",
        )
    if eq is not None and cur.equity_attributable is not None and eq > 0 and cur.equity_attributable > eq * 1.0001:
        warn(
            "current.equity_attributable",
            "Ekuitas pemilik entitas induk lebih besar dari total ekuitas. Ini hanya wajar jika "
            "kepentingan non-pengendali negatif; mohon periksa.",
        )
    ni = cur.net_income if cur.net_income is not None else cur.net_income_attributable
    if cur.revenue and ni is not None and abs(ni) > cur.revenue:
        warn(
            "current.net_income",
            "Nilai absolut laba bersih lebih besar dari pendapatan. Bisa wajar untuk perusahaan "
            "induk/investasi, tetapi mohon periksa.",
        )
    if cur.weighted_average_shares and cur.shares_outstanding:
        ratio = cur.shares_outstanding / cur.weighted_average_shares
        if ratio > 1.3 or ratio < 1 / 1.3:
            warn(
                "current.weighted_average_shares",
                "Jumlah saham beredar dan rata-rata tertimbang berbeda lebih dari 30%. Bisa terjadi "
                "karena stock split, rights issue, atau buyback; pastikan angkanya benar.",
            )

    # Unit sanity: a listed company with total assets under Rp 1 juta, or above Rp 10.000 triliun,
    # almost certainly has the wrong unit selected.
    if a is not None and a > 0:
        normalized_assets = a * mult
        if normalized_assets < 1e6:
            warn("statement.unit", "Total aset sangat kecil untuk perusahaan tercatat. Apakah satuan sudah benar?")
        if st.currency == Currency.IDR and normalized_assets > 1e16:
            warn("statement.unit", "Total aset sangat besar (> Rp 10.000 triliun). Apakah satuan sudah benar?")

    if st.currency != Currency.IDR and st.fx_rate_to_idr is None:
        warn(
            "statement.fx_rate_to_idr",
            f"Laporan dalam {st.currency.value} tanpa kurs ke IDR. PER dan PBV tidak dapat dihitung "
            "karena harga saham dalam rupiah.",
        )

    m = inp.market
    if m.share_price_date is not None and (today - m.share_price_date).days > 90:
        warn(
            "market.share_price_date",
            f"Harga saham berasal dari {m.share_price_date.isoformat()}, lebih dari 90 hari lalu. "
            "Valuasi mungkin tidak mencerminkan harga terkini.",
        )

    comp = check_comparability(inp)
    if inp.previous is not None and not comp["comparable"]:
        warn("previous.fiscal_year", comp["reason"])

    if inp.company.sector in BANK_SECTORS:
        warn(
            "company.sector",
            "Untuk bank, metrik khusus seperti CAR, NPL, LDR, NIM, dan BOPO belum didukung. "
            "DER dan current ratio tidak diterapkan.",
        )
    return issues


def _annualize(m: MetricResult, months: int) -> None:
    if m.status == "ok" and m.value is not None and months < 12:
        m.annualized_value = m.value * 12 / months
        m.assumptions.append(
            f"Untuk penilaian skor, nilai periode {months} bulan disetahunkan secara linear (×12/{months}). "
            "Bisnis musiman dapat membuat angka ini menyesatkan."
        )


def calculate_metrics(inp: AnalysisInput) -> dict[str, MetricResult]:
    st = inp.statement
    mult = UNIT_MULTIPLIER[st.unit]
    cur = normalize(inp.current, mult)
    prev = normalize(inp.previous.values, mult) if inp.previous else {}
    months = st.months
    sector = inp.company.sector
    is_bank = sector in BANK_SECTORS
    is_financial = sector in FINANCIAL_SECTORS
    comp = check_comparability(inp)
    interim_note = (
        f" Nilai untuk periode {months} bulan, tidak disetahunkan." if months < 12 else ""
    )
    b = _Builder()

    # Beginning balances: for annual statements, the comparable prior-year *ending* balance is
    # by definition this year's *opening* balance. Derive it only in that case, and record it.
    derived_begin: dict[str, str] = {}
    if st.basis == Basis.annual and comp["comparable"]:
        for begin_field, end_field in (
            ("total_assets_begin", "total_assets"),
            ("total_equity_begin", "total_equity"),
            ("equity_attributable_begin", "equity_attributable"),
        ):
            if cur.get(begin_field) is None and prev.get(end_field) is not None:
                cur[begin_field] = prev[end_field]
                derived_begin[begin_field] = (
                    f"{FIELD_LABELS[begin_field]} diambil dari saldo akhir "
                    f"{comp['previous_label']} yang Anda masukkan."
                )

    ni_total = cur.get("net_income")
    ni_attr = cur.get("net_income_attributable")

    def earnings_for_shareholders(assumptions: list[str]) -> tuple[float | None, str | None]:
        if ni_attr is not None:
            return ni_attr, "net_income_attributable"
        if ni_total is not None:
            assumptions.append(
                "Laba yang dapat diatribusikan ke pemilik entitas induk tidak diisi; digunakan laba "
                "bersih total (termasuk kepentingan non-pengendali, jika ada)."
            )
            return ni_total, "net_income"
        return None, None

    # 1. Net Profit Margin
    formula = "Laba bersih / Pendapatan × 100"
    assumptions: list[str] = []
    ni_for_margin, ni_field = (ni_total, "net_income") if ni_total is not None else (ni_attr, "net_income_attributable")
    if ni_total is None and ni_attr is not None:
        assumptions.append("Laba bersih total tidak diisi; digunakan laba yang diatribusikan ke entitas induk.")
    rev = cur.get("revenue")
    if rev is None or ni_for_margin is None:
        b.unavailable("npm", "percent", formula, _missing(["revenue", "net_income"], {**cur, "net_income": ni_for_margin}))
    elif rev == 0:
        b.add("npm", "percent", formula, status="not_meaningful", inputs_used=["revenue", ni_field],
              explanation="Pendapatan bernilai nol sehingga margin tidak dapat dihitung.")
    else:
        b.add("npm", "percent", formula, status="ok", value=ni_for_margin / rev * 100,
              inputs_used=["revenue", ni_field], assumptions=assumptions)

    # 2. ROE (average equity)
    formula = "Laba yang diatribusikan ke pemilik entitas induk / Rata-rata ekuitas × 100"
    assumptions = []
    earnings, e_field = earnings_for_shareholders(assumptions)
    if cur.get("equity_attributable") is not None and cur.get("equity_attributable_begin") is not None:
        eq_end, eq_begin = cur["equity_attributable"], cur["equity_attributable_begin"]
        eq_fields = ["equity_attributable", "equity_attributable_begin"]
    elif cur.get("total_equity") is not None and cur.get("total_equity_begin") is not None:
        eq_end, eq_begin = cur["total_equity"], cur["total_equity_begin"]
        eq_fields = ["total_equity", "total_equity_begin"]
        assumptions.append(
            "Ekuitas pemilik entitas induk (awal & akhir) tidak lengkap; digunakan total ekuitas "
            "yang dapat mencakup kepentingan non-pengendali."
        )
    else:
        eq_end = eq_begin = None
        eq_fields = []
    for f in eq_fields:
        if f in derived_begin:
            assumptions.append(derived_begin[f])
    if earnings is None or eq_end is None:
        missing = _missing(["net_income_attributable"], {"net_income_attributable": earnings})
        if eq_end is None:
            missing += [f for f in ("total_equity", "total_equity_begin") if cur.get(f) is None] or ["equity_attributable_begin"]
        b.unavailable("roe", "percent", formula, missing,
                      "Saldo akhir ekuitas tidak digunakan sebagai pengganti rata-rata ekuitas.")
    else:
        avg = (eq_end + eq_begin) / 2
        if avg <= 0:
            b.add("roe", "percent", formula, status="not_meaningful", inputs_used=[e_field, *eq_fields],
                  assumptions=assumptions,
                  explanation="Rata-rata ekuitas nol atau negatif (defisiensi modal); ROE tidak bermakna.")
        else:
            m = b.add("roe", "percent", formula, status="ok", value=earnings / avg * 100,
                      inputs_used=[e_field, *eq_fields], assumptions=assumptions,
                      explanation=("ROE periode berjalan." + interim_note).strip())
            _annualize(m, months)

    # 3. ROA (average total assets)
    formula = "Laba bersih / Rata-rata total aset × 100"
    assumptions = []
    ni_for_roa = ni_total if ni_total is not None else ni_attr
    if ni_total is None and ni_attr is not None:
        assumptions.append("Laba bersih total tidak diisi; digunakan laba yang diatribusikan ke entitas induk.")
    if "total_assets_begin" in derived_begin:
        assumptions.append(derived_begin["total_assets_begin"])
    ta, ta_begin = cur.get("total_assets"), cur.get("total_assets_begin")
    if ni_for_roa is None or ta is None or ta_begin is None:
        b.unavailable("roa", "percent", formula,
                      _missing(["net_income", "total_assets", "total_assets_begin"],
                               {**cur, "net_income": ni_for_roa}),
                      "Saldo akhir aset tidak digunakan sebagai pengganti rata-rata aset.")
    else:
        avg = (ta + ta_begin) / 2
        if avg <= 0:
            b.add("roa", "percent", formula, status="not_meaningful",
                  explanation="Rata-rata total aset bernilai nol.", inputs_used=["total_assets", "total_assets_begin"])
        else:
            m = b.add("roa", "percent", formula, status="ok", value=ni_for_roa / avg * 100,
                      inputs_used=["net_income", "total_assets", "total_assets_begin"], assumptions=assumptions,
                      explanation=("ROA periode berjalan." + interim_note).strip())
            _annualize(m, months)

    # 4. DER
    formula = "Total liabilitas / Total ekuitas"
    if is_bank:
        b.add("der", "ratio", formula, status="not_applicable",
              explanation="Tidak diterapkan untuk bank: sebagian besar liabilitas bank adalah simpanan nasabah, "
                          "sehingga DER konvensional tidak mencerminkan risiko. Gunakan CAR dan LDR.")
    elif cur.get("total_liabilities") is None or cur.get("total_equity") is None:
        b.unavailable("der", "ratio", formula, _missing(["total_liabilities", "total_equity"], cur))
    elif cur["total_equity"] <= 0:
        b.add("der", "ratio", formula, status="not_meaningful", inputs_used=["total_liabilities", "total_equity"],
              explanation="Total ekuitas nol atau negatif (defisiensi modal). DER tidak bermakna, dan kondisi ini "
                          "merupakan sinyal risiko yang serius.")
    else:
        note = "Untuk perusahaan keuangan non-bank, DER tinggi bisa merupakan bagian dari model bisnis." if is_financial else None
        b.add("der", "ratio", formula, status="ok", value=cur["total_liabilities"] / cur["total_equity"],
              inputs_used=["total_liabilities", "total_equity"], explanation=note)

    # 5. Current ratio
    formula = "Aset lancar / Liabilitas jangka pendek"
    if is_financial:
        b.add("current_ratio", "ratio", formula, status="not_applicable",
              explanation="Tidak diterapkan untuk sektor keuangan karena neraca umumnya tidak dipisahkan "
                          "menjadi lancar dan tidak lancar.")
    elif cur.get("current_assets") is None or cur.get("current_liabilities") is None:
        b.unavailable("current_ratio", "ratio", formula, _missing(["current_assets", "current_liabilities"], cur))
    elif cur["current_liabilities"] == 0:
        b.add("current_ratio", "ratio", formula, status="not_meaningful",
              inputs_used=["current_assets", "current_liabilities"],
              explanation="Liabilitas jangka pendek bernilai nol; rasio tidak dapat dihitung.")
    else:
        b.add("current_ratio", "ratio", formula, status="ok",
              value=cur["current_assets"] / cur["current_liabilities"],
              inputs_used=["current_assets", "current_liabilities"])

    # 6. Revenue growth (YoY, comparable period only)
    formula = "(Pendapatan periode berjalan / Pendapatan periode pembanding − 1) × 100"
    if rev is None:
        b.unavailable("revenue_growth", "percent", formula, ["revenue"])
    elif not comp["comparable"]:
        b.add("revenue_growth", "percent", formula, status="unavailable", explanation=comp["reason"])
    elif prev.get("revenue") is None:
        b.add("revenue_growth", "percent", formula, status="unavailable",
              explanation="Belum tersedia: pendapatan periode pembanding belum diisi.")
    elif prev["revenue"] <= 0:
        b.add("revenue_growth", "percent", formula, status="not_meaningful", inputs_used=["revenue", "previous.revenue"],
              explanation="Pendapatan periode pembanding nol; pertumbuhan tidak dapat dihitung.")
    else:
        b.add("revenue_growth", "percent", formula, status="ok", value=(rev / prev["revenue"] - 1) * 100,
              inputs_used=["revenue", "previous.revenue"],
              explanation=f"Dibandingkan dengan {comp['previous_label']}.")

    # 6b. Net income growth (same earnings definition in both periods)
    formula = "(Laba periode berjalan / Laba periode pembanding − 1) × 100"
    if ni_attr is not None and prev.get("net_income_attributable") is not None:
        ni_c, ni_p, nf = ni_attr, prev["net_income_attributable"], "net_income_attributable"
    elif ni_total is not None and prev.get("net_income") is not None:
        ni_c, ni_p, nf = ni_total, prev["net_income"], "net_income"
    else:
        ni_c = ni_p = nf = None
    if ni_attr is None and ni_total is None:
        b.unavailable("net_income_growth", "percent", formula, ["net_income"])
    elif not comp["comparable"]:
        b.add("net_income_growth", "percent", formula, status="unavailable", explanation=comp["reason"])
    elif ni_c is None:
        b.add("net_income_growth", "percent", formula, status="unavailable",
              explanation="Belum tersedia: laba periode pembanding (dengan definisi yang sama) belum diisi.")
    elif ni_p <= 0:
        direction = "berbalik menjadi laba" if ni_c > 0 else "masih merugi"
        b.add("net_income_growth", "percent", formula, status="not_meaningful", inputs_used=[nf, f"previous.{nf}"],
              explanation=f"Laba periode pembanding nol atau negatif; persentase pertumbuhan tidak bermakna "
                          f"(perusahaan {direction}).")
    else:
        b.add("net_income_growth", "percent", formula, status="ok", value=(ni_c / ni_p - 1) * 100,
              inputs_used=[nf, f"previous.{nf}"], explanation=f"Dibandingkan dengan {comp['previous_label']}.")

    # 7. EPS
    formula = "Laba yang diatribusikan ke pemilik entitas induk / Rata-rata tertimbang saham biasa beredar"
    assumptions = []
    earnings, e_field = earnings_for_shareholders(assumptions)
    w = cur.get("weighted_average_shares")
    eps_value = None
    if earnings is None or w is None:
        b.unavailable("eps", "currency_per_share", formula,
                      _missing(["net_income_attributable", "weighted_average_shares"],
                               {**cur, "net_income_attributable": earnings}))
    else:
        eps_value = earnings / w
        b.add("eps", "currency_per_share", formula, status="ok", value=eps_value,
              inputs_used=[e_field, "weighted_average_shares"], assumptions=assumptions,
              explanation=(f"Dalam {st.currency.value} per lembar (EPS dasar)." + interim_note).strip())

    # FX conversion for valuation
    fx = 1.0 if st.currency == Currency.IDR else st.fx_rate_to_idr
    price = inp.market.share_price
    fx_missing = fx is None
    price_missing = price is None

    def valuation_blockers(extra_missing: list[str]) -> str | None:
        parts = []
        if price_missing:
            parts.append("harga saham dan tanggalnya belum diisi")
        if fx_missing:
            parts.append(f"kurs {st.currency.value} ke IDR belum diisi")
        if extra_missing:
            parts.append(", ".join(FIELD_LABELS.get(f, f) for f in extra_missing) + " belum diisi")
        return ("Belum tersedia: " + "; ".join(parts) + ".") if parts else None

    # 8. PER
    formula = "Harga saham / EPS (tahunan)"
    blocker = valuation_blockers(
        [] if eps_value is not None
        else _missing(["net_income_attributable", "weighted_average_shares"], {**cur, "net_income_attributable": earnings})
    )
    if eps_value is not None and eps_value <= 0:
        b.add("per", "ratio", formula, status="not_meaningful", inputs_used=["eps", "share_price"],
              explanation="EPS nol atau negatif; PER tidak bermakna untuk perusahaan yang merugi.")
    elif blocker:
        b.add("per", "ratio", formula, status="unavailable", explanation=blocker)
    elif months != 12:
        b.add("per", "ratio", formula, status="unavailable",
              explanation=f"PER membutuhkan EPS 12 bulan. Laporan ini mencakup {months} bulan; gunakan laporan "
                          "tahunan atau data trailing twelve months (TTM).")
    else:
        b.add("per", "ratio", formula, status="ok", value=price / (eps_value * fx),
              inputs_used=["share_price", "eps"] + ([] if fx == 1.0 else ["fx_rate_to_idr"]),
              explanation=f"Harga per {inp.market.share_price_date.isoformat()}.")

    # 9. BVPS
    formula = "Ekuitas pemilik entitas induk / Jumlah saham beredar"
    assumptions = [SHARE_CLASS_ASSUMPTION]
    if cur.get("equity_attributable") is not None:
        eq, eq_f = cur["equity_attributable"], "equity_attributable"
    elif cur.get("total_equity") is not None:
        eq, eq_f = cur["total_equity"], "total_equity"
        assumptions.append("Ekuitas pemilik entitas induk tidak diisi; digunakan total ekuitas.")
    else:
        eq, eq_f = None, None
    so = cur.get("shares_outstanding")
    bvps_value = None
    if eq is None or so is None:
        b.unavailable("bvps", "currency_per_share", formula,
                      _missing(["equity_attributable", "shares_outstanding"], {**cur, "equity_attributable": eq}))
    else:
        bvps_value = eq / so
        b.add("bvps", "currency_per_share", formula, status="ok", value=bvps_value,
              inputs_used=[eq_f, "shares_outstanding"], assumptions=assumptions,
              explanation=f"Dalam {st.currency.value} per lembar.")

    # 10. PBV
    formula = "Harga saham / BVPS"
    blocker = valuation_blockers([] if bvps_value is not None else _missing(["equity_attributable", "shares_outstanding"], {**cur, "equity_attributable": eq}))
    if bvps_value is not None and bvps_value <= 0:
        b.add("pbv", "ratio", formula, status="not_meaningful", inputs_used=["bvps", "share_price"],
              explanation="Nilai buku per saham nol atau negatif; PBV tidak bermakna.")
    elif blocker:
        b.add("pbv", "ratio", formula, status="unavailable", explanation=blocker)
    else:
        b.add("pbv", "ratio", formula, status="ok", value=price / (bvps_value * fx),
              inputs_used=["share_price", "bvps"] + ([] if fx == 1.0 else ["fx_rate_to_idr"]),
              explanation=f"Harga per {inp.market.share_price_date.isoformat()}.")

    # 11. Operating cash flow (as reported, normalised)
    ocf = cur.get("operating_cash_flow")
    formula = "Arus kas bersih dari aktivitas operasi (sesuai laporan)"
    bank_cf_note = (
        " Untuk bank, arus kas operasi dipengaruhi pergerakan kredit dan simpanan sehingga sulit ditafsirkan."
        if is_bank else ""
    )
    if ocf is None:
        b.unavailable("operating_cash_flow", "currency", formula, ["operating_cash_flow"])
    else:
        b.add("operating_cash_flow", "currency", formula, status="ok", value=ocf, inputs_used=["operating_cash_flow"],
              explanation=(f"Dalam {st.currency.value}." + interim_note + bank_cf_note).strip())

    # 12. Free cash flow
    formula = "Arus kas operasi − Belanja modal"
    capex = cur.get("capital_expenditure")
    fcf = None
    if ocf is None or capex is None:
        b.unavailable("free_cash_flow", "currency", formula, _missing(["operating_cash_flow", "capital_expenditure"], cur))
    else:
        fcf = ocf - capex
        b.add("free_cash_flow", "currency", formula, status="ok", value=fcf,
              inputs_used=["operating_cash_flow", "capital_expenditure"],
              explanation=(f"Dalam {st.currency.value}." + interim_note + bank_cf_note).strip())

    formula = "Free cash flow / Pendapatan × 100"
    if fcf is None or rev is None:
        b.unavailable("fcf_margin", "percent", formula,
                      _missing(["operating_cash_flow", "capital_expenditure", "revenue"], cur))
    elif rev == 0:
        b.add("fcf_margin", "percent", formula, status="not_meaningful",
              explanation="Pendapatan bernilai nol.", inputs_used=["free_cash_flow", "revenue"])
    else:
        b.add("fcf_margin", "percent", formula, status="ok", value=fcf / rev * 100,
              inputs_used=["free_cash_flow", "revenue"])

    # 13. Cash flow quality
    formula = "Arus kas operasi / Laba bersih"
    limits = (
        "Rasio di atas 1 berarti laba didukung kas. Rasio dapat terdistorsi oleh perubahan modal kerja, "
        "musim, dan pos non-kas; satu periode saja tidak cukup untuk menyimpulkan kualitas laba."
    )
    ni_q = ni_total if ni_total is not None else ni_attr
    if ocf is None or ni_q is None:
        b.unavailable("cash_flow_quality", "ratio", formula,
                      _missing(["operating_cash_flow", "net_income"], {**cur, "net_income": ni_q}))
    elif ni_q <= 0:
        qualitative = (
            "arus kas operasi positif meskipun laba nol/negatif" if ocf > 0
            else "arus kas operasi dan laba sama-sama nol/negatif"
        )
        b.add("cash_flow_quality", "ratio", formula, status="not_meaningful",
              inputs_used=["operating_cash_flow", "net_income"],
              explanation=f"Laba bersih nol atau negatif, sehingga rasio tidak bermakna; secara kualitatif, {qualitative}.")
    else:
        b.add("cash_flow_quality", "ratio", formula, status="ok", value=ocf / ni_q,
              inputs_used=["operating_cash_flow", "net_income"], explanation=limits + bank_cf_note)

    return b.metrics
