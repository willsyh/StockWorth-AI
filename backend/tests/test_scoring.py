import pytest

from app.schemas.financials import AnalysisInput
from app.services.analysis import run_analysis
from app.services.scoring import band_score


def analyse(data):
    return run_analysis(AnalysisInput.model_validate(data))


def test_band_score_directions():
    assert band_score(15, {"worst": 0, "best": 15}) == 100
    assert band_score(-5, {"worst": 0, "best": 15}) == 0
    assert band_score(7.5, {"worst": 0, "best": 15}) == 50
    # lower is better
    assert band_score(0.5, {"worst": 2.0, "best": 0.5}) == 100
    assert band_score(3.0, {"worst": 2.0, "best": 0.5}) == 0


def test_complete_score(base_input):
    r = analyse(base_input)
    f = r.fundamental_score
    assert f.status == "complete"
    assert 0 <= f.score <= 100
    assert f.coverage == pytest.approx(1.0)
    assert r.completeness.percent == 100.0


def test_missing_metrics_lower_coverage_not_score(base_input):
    full = analyse(base_input).fundamental_score
    base_input["current"].pop("current_assets")  # liquidity dimension loses its only metric
    partial = analyse(base_input).fundamental_score
    assert partial.coverage < full.coverage
    liquidity = next(d for d in partial.dimensions if d.key == "liquidity")
    assert liquidity.score is None  # not zero
    assert partial.status in ("provisional", "complete")


def test_insufficient_data_gives_no_score(base_input):
    base_input["current"] = {"revenue": 10_000, "net_income": 1_000}
    base_input["previous"] = None
    base_input["market"] = {}
    r = analyse(base_input)
    assert r.fundamental_score.score is None
    assert r.fundamental_score.status == "insufficient"
    assert r.valuation_score.score is None
    assert r.valuation_score.status == "unavailable"
    assert r.completeness.percent < 30
    assert any(m.field == "share_price" for m in r.completeness.missing)


def test_negative_equity_scores_leverage_zero_explicitly(base_input):
    base_input["current"].update({"total_equity": -1_000, "total_equity_begin": -500,
                                  "equity_attributable": -1_000, "equity_attributable_begin": -500,
                                  "total_liabilities": 21_000})
    r = analyse(base_input)
    lev = next(d for d in r.fundamental_score.dimensions if d.key == "leverage")
    assert lev.score == 0
    assert "negatif" in lev.metrics[0].note
    assert any(f.section == "risk" and "defisiensi" in f.text for f in r.findings)


def test_bank_dimensions_not_applicable(base_input):
    base_input["company"]["sector"] = "financials_bank"
    r = analyse(base_input)
    dims = {d.key: d for d in r.fundamental_score.dimensions}
    assert not dims["leverage"].applicable
    assert not dims["liquidity"].applicable
    assert r.fundamental_score.status == "provisional"
    assert r.scoring_profile == "bank"


def test_sector_specific_der_threshold(base_input):
    base_input["current"]["total_liabilities"] = 24_000  # DER 2.0
    base_input["current"]["total_assets"] = 36_000
    default = analyse(base_input)
    base_input["company"]["sector"] = "infrastructures"
    infra = analyse(base_input)

    def der_score(r):
        return next(d for d in r.fundamental_score.dimensions if d.key == "leverage").score

    assert der_score(infra) > der_score(default)


def test_valuation_separate_and_requires_price(base_input):
    r = analyse(base_input)
    assert r.valuation_score.score is not None
    base_input["market"] = {}
    r2 = analyse(base_input)
    assert r2.valuation_score.status == "unavailable"
    # fundamental score unaffected by price
    assert r2.fundamental_score.score == r.fundamental_score.score


def test_low_per_with_falling_earnings_flags_value_trap(base_input):
    base_input["market"]["share_price"] = 5  # EPS 1 -> PER 5, "low"
    base_input["previous"]["values"]["net_income_attributable"] = 2_000  # earnings fell 50%
    r = analyse(base_input)
    assert any("value trap" in f.text for f in r.findings)


def test_findings_carry_methodology(base_input):
    r = analyse(base_input)
    assert r.methodology_version
    assert r.disclaimer
    assert all(f.text for f in r.findings)
