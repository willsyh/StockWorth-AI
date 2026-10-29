"""Output schemas for calculations, scores, findings and insights."""

from typing import Literal

from pydantic import BaseModel, Field

MetricStatus = Literal["ok", "unavailable", "not_meaningful", "not_applicable"]
MetricUnit = Literal["percent", "ratio", "currency", "currency_per_share", "idr_per_share"]
Severity = Literal["positive", "negative", "warning", "neutral"]


class MetricResult(BaseModel):
    key: str
    label: str
    value: float | None = None
    unit: MetricUnit
    status: MetricStatus
    formula: str
    explanation: str | None = Field(None, description="Why the value is unavailable, or how to read it")
    inputs_used: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    annualized_value: float | None = Field(
        None, description="Linear annualisation for interim periods; used only for scoring"
    )


class ValidationIssue(BaseModel):
    level: Literal["error", "warning"]
    field: str | None = None
    message: str


class MissingField(BaseModel):
    field: str
    label: str
    blocks: list[str] = Field(description="Metric labels that cannot be calculated without this field")


class DataCompleteness(BaseModel):
    percent: float
    provided: int
    applicable: int
    missing: list[MissingField]


class MetricScore(BaseModel):
    metric: str
    label: str
    score: float | None
    basis_value: float | None = None
    rule: str
    note: str | None = None


class DimensionScore(BaseModel):
    key: str
    label: str
    weight: float
    applicable: bool
    score: float | None
    coverage: float
    metrics: list[MetricScore]
    note: str | None = None


class ScoreResult(BaseModel):
    score: float | None
    status: Literal["complete", "provisional", "insufficient", "unavailable"]
    label: str | None
    coverage: float
    dimensions: list[DimensionScore] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class Finding(BaseModel):
    section: Literal[
        "summary", "profitability", "growth", "leverage_liquidity", "cash_flow", "valuation", "risk", "missing"
    ]
    severity: Severity
    text: str
    metrics: list[str] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    methodology_version: str
    scoring_profile: str
    period_label: str
    months_covered: int
    is_financial_sector: bool
    metrics: dict[str, MetricResult]
    fundamental_score: ScoreResult
    valuation_score: ScoreResult
    completeness: DataCompleteness
    findings: list[Finding]
    issues: list[ValidationIssue]
    comparability: dict = Field(default_factory=dict)
    # Input values normalised to whole currency units (shares unscaled), for traceable charts.
    normalized: dict = Field(default_factory=dict)
    disclaimer: str


class InsightContent(BaseModel):
    """Shared shape of AI and rule-based insights."""

    summary: str
    strengths: list[str]
    risks: list[str]
    valuation_observations: list[str]
    missing_information: list[str]
    conclusion: str
    limitations: list[str]


class InsightRecord(BaseModel):
    id: str | None = None
    analysis_id: str
    source: Literal["ai", "rule_based"]
    provider: str | None = None
    model: str | None = None
    content: InsightContent
    fallback_reason: str | None = None
    created_at: str | None = None
