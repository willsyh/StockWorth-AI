from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from app.schemas.financials import AnalysisInput
from app.services.calculator import calculate_metrics, normalize, validate_input
from app.schemas.financials import FinancialValues


def calc(data):
    return calculate_metrics(AnalysisInput.model_validate(data))


# --- Normal inputs ----------------------------------------------------------------

def test_normal_ratios(base_input):
    m = calc(base_input)
    assert m["npm"].value == pytest.approx(12.0)  # 1200 / 10000
    assert m["roe"].value == pytest.approx(1000 / 9500 * 100)  # attributable / avg attributable equity
    assert m["roa"].value == pytest.approx(1200 / 19000 * 100)
    assert m["der"].value == pytest.approx(8000 / 12000)
    assert m["current_ratio"].value == pytest.approx(2.0)
    assert m["revenue_growth"].value == pytest.approx(25.0)
    assert m["net_income_growth"].value == pytest.approx(25.0)  # attributable 1000 vs 800
    assert m["free_cash_flow"].value == pytest.approx(1_000 * 1e6)
    assert m["fcf_margin"].value == pytest.approx(10.0)
    assert m["cash_flow_quality"].value == pytest.approx(1.25)
    for k in ("npm", "roe", "roa", "der", "current_ratio", "eps", "per", "bvps", "pbv"):
        assert m[k].status == "ok", k


def test_unit_normalisation_for_per_share(base_input):
    m = calc(base_input)
    # 1.000 juta / 1 miliar saham = Rp 1 per saham
    assert m["eps"].value == pytest.approx(1.0)
    assert m["per"].value == pytest.approx(10_000.0)
    assert m["bvps"].value == pytest.approx(10.0)  # 10.000 juta / 1 miliar saham
    assert m["pbv"].value == pytest.approx(1_000.0)


def test_units_do_not_change_ratios(base_input):
    base_input["statement"]["unit"] = "miliar"
    m = calc(base_input)
    assert m["npm"].value == pytest.approx(12.0)
    assert m["eps"].value == pytest.approx(1_000.0)  # values now 1000x larger in rupiah


def test_normalize_scales_money_not_shares():
    v = FinancialValues(revenue=5, weighted_average_shares=100)
    n = normalize(v, 1e6)
    assert n["revenue"] == 5e6
    assert n["weighted_average_shares"] == 100
    assert n["net_income"] is None


def test_usd_statement_requires_fx_for_valuation(base_input):
    base_input["statement"]["currency"] = "USD"
    m = calc(base_input)
    assert m["per"].status == "unavailable"
    assert "kurs" in m["per"].explanation
    base_input["statement"]["fx_rate_to_idr"] = 16_000
    m = calc(base_input)
    assert m["per"].status == "ok"
    assert m["per"].value == pytest.approx(10_000 / (1.0 * 16_000))


# --- Missing values --------------------------------------------------------------

def test_missing_values_are_unavailable_not_zero(base_input):
    base_input["current"] = {"revenue": 10_000, "net_income": 1_000}
    base_input["previous"] = None
    base_input["market"] = {}
    m = calc(base_input)
    assert m["npm"].status == "ok"
    for k in ("roe", "roa", "der", "current_ratio", "revenue_growth", "eps", "per", "bvps", "pbv",
              "operating_cash_flow", "free_cash_flow", "cash_flow_quality"):
        assert m[k].status == "unavailable", k
        assert m[k].value is None, k
        assert m[k].explanation, k


def test_no_ending_balance_substitution_for_average(base_input):
    for f in ("total_assets_begin", "total_equity_begin", "equity_attributable_begin"):
        base_input["current"].pop(f)
    base_input["previous"]["values"] = {"revenue": 8_000}  # no prior balances to derive from
    m = calc(base_input)
    assert m["roe"].status == "unavailable"
    assert m["roa"].status == "unavailable"
    assert "tidak digunakan sebagai pengganti" in m["roa"].explanation


def test_beginning_balance_derived_from_prior_year_end_annual_only(base_input):
    base_input["current"].pop("total_assets_begin")
    base_input["previous"]["values"]["total_assets"] = 18_000
    m = calc(base_input)
    assert m["roa"].status == "ok"
    assert m["roa"].value == pytest.approx(1200 / 19000 * 100)
    assert any("saldo akhir FY2023" in a for a in m["roa"].assumptions)

    # Not derived for interim statements (prior-year same quarter is not the opening balance).
    base_input["statement"].update({"basis": "quarterly", "period": "Q2"})
    base_input["previous"]["period"] = "Q2"
    m = calc(base_input)
    assert m["roa"].status == "unavailable"


def test_attributable_fallback_is_recorded(base_input):
    base_input["current"].pop("net_income_attributable")
    m = calc(base_input)
    assert m["eps"].status == "ok"
    assert m["eps"].value == pytest.approx(1.2)
    assert any("laba bersih total" in a for a in m["eps"].assumptions)


def test_total_equity_fallback_for_roe_is_recorded(base_input):
    base_input["current"].pop("equity_attributable_begin")
    m = calc(base_input)
    assert m["roe"].value == pytest.approx(1000 / 11500 * 100)
    assert any("total ekuitas" in a for a in m["roe"].assumptions)


# --- Zero denominators -----------------------------------------------------------

def test_zero_revenue(base_input):
    base_input["current"]["revenue"] = 0
    m = calc(base_input)
    assert m["npm"].status == "not_meaningful"
    assert m["npm"].value is None


def test_zero_current_liabilities(base_input):
    base_input["current"]["current_liabilities"] = 0
    m = calc(base_input)
    assert m["current_ratio"].status == "not_meaningful"


def test_zero_previous_revenue(base_input):
    base_input["previous"]["values"]["revenue"] = 0
    m = calc(base_input)
    assert m["revenue_growth"].status == "not_meaningful"


# --- Negative values -------------------------------------------------------------

def test_negative_earnings(base_input):
    base_input["current"]["net_income"] = -500
    base_input["current"]["net_income_attributable"] = -400
    m = calc(base_input)
    assert m["npm"].value == pytest.approx(-5.0)
    assert m["roe"].status == "ok" and m["roe"].value < 0
    assert m["eps"].value < 0
    assert m["per"].status == "not_meaningful"
    assert m["cash_flow_quality"].status == "not_meaningful"


def test_negative_equity(base_input):
    base_input["current"].update({"total_equity": -1_000, "total_equity_begin": -500,
                                  "equity_attributable": -1_000, "equity_attributable_begin": -500,
                                  "total_liabilities": 21_000})
    m = calc(base_input)
    assert m["der"].status == "not_meaningful"
    assert m["roe"].status == "not_meaningful"
    assert m["bvps"].value < 0
    assert m["pbv"].status == "not_meaningful"


def test_previous_loss_makes_growth_not_meaningful(base_input):
    base_input["previous"]["values"]["net_income_attributable"] = -100
    m = calc(base_input)
    assert m["net_income_growth"].status == "not_meaningful"
    assert "berbalik menjadi laba" in m["net_income_growth"].explanation


# --- Period comparability / interim -------------------------------------------------

def test_growth_requires_comparable_period(base_input):
    base_input["previous"]["fiscal_year"] = 2022
    m = calc(base_input)
    assert m["revenue_growth"].status == "unavailable"
    assert "tahun fiskal sebelumnya" in m["revenue_growth"].explanation


def test_quarter_vs_different_quarter_not_comparable(base_input):
    base_input["statement"].update({"basis": "ytd", "period": "Q3"})
    base_input["previous"].update({"fiscal_year": 2024, "period": "Q2"})
    m = calc(base_input)
    assert m["revenue_growth"].status == "unavailable"


def test_interim_per_requires_annual_eps_and_roe_annualized(base_input):
    base_input["statement"].update({"basis": "ytd", "period": "Q2"})
    base_input["previous"]["period"] = "Q2"
    m = calc(base_input)
    assert m["per"].status == "unavailable"
    assert "12 bulan" in m["per"].explanation
    assert m["roe"].annualized_value == pytest.approx(m["roe"].value * 2)
    assert m["revenue_growth"].status == "ok"


def test_bank_sector_rules(base_input):
    base_input["company"]["sector"] = "financials_bank"
    m = calc(base_input)
    assert m["der"].status == "not_applicable"
    assert m["current_ratio"].status == "not_applicable"


# --- Invalid inputs ---------------------------------------------------------------

@pytest.mark.parametrize("field,value", [
    ("revenue", -1),
    ("total_assets", -5),
    ("capital_expenditure", -10),
    ("weighted_average_shares", 0),
    ("shares_outstanding", -1),
    ("revenue", float("inf")),
    ("revenue", 1e30),
])
def test_invalid_values_rejected(base_input, field, value):
    base_input["current"][field] = value
    with pytest.raises(ValidationError):
        AnalysisInput.model_validate(base_input)


@pytest.mark.parametrize("ticker", ["BB", "BBCA1", "12AB", ""])
def test_invalid_ticker(base_input, ticker):
    base_input["company"]["ticker"] = ticker
    with pytest.raises(ValidationError):
        AnalysisInput.model_validate(base_input)


def test_ticker_normalised(base_input):
    base_input["company"]["ticker"] = " bbca "
    assert AnalysisInput.model_validate(base_input).company.ticker == "BBCA"


def test_period_basis_consistency(base_input):
    base_input["statement"]["period"] = "Q1"  # annual must be FY
    with pytest.raises(ValidationError):
        AnalysisInput.model_validate(base_input)


def test_future_price_date_rejected(base_input):
    base_input["market"]["share_price_date"] = (date.today() + timedelta(days=2)).isoformat()
    with pytest.raises(ValidationError):
        AnalysisInput.model_validate(base_input)


def test_price_requires_date(base_input):
    base_input["market"]["share_price_date"] = None
    with pytest.raises(ValidationError):
        AnalysisInput.model_validate(base_input)


def test_unknown_fields_rejected(base_input):
    base_input["current"]["ebitda"] = 5
    with pytest.raises(ValidationError):
        AnalysisInput.model_validate(base_input)


# --- Consistency warnings ---------------------------------------------------------

def test_balance_sheet_mismatch_warning(base_input):
    base_input["current"]["total_liabilities"] = 2_000
    issues = validate_input(AnalysisInput.model_validate(base_input))
    assert any(i.field == "current.total_assets" for i in issues)


def test_no_income_data_is_error(base_input):
    for f in ("revenue", "net_income", "net_income_attributable"):
        base_input["current"].pop(f)
    issues = validate_input(AnalysisInput.model_validate(base_input))
    assert any(i.level == "error" for i in issues)


def test_stale_price_warning(base_input):
    base_input["market"]["share_price_date"] = (date.today() - timedelta(days=200)).isoformat()
    issues = validate_input(AnalysisInput.model_validate(base_input))
    assert any(i.field == "market.share_price_date" for i in issues)


def test_unit_sanity_warning(base_input):
    base_input["statement"]["unit"] = "unit"
    base_input["current"]["total_assets"] = 500
    issues = validate_input(AnalysisInput.model_validate(base_input))
    assert any(i.field == "statement.unit" for i in issues)
