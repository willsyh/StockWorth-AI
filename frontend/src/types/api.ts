// Types mirroring the FastAPI schemas (backend/app/schemas).

export type Unit = "unit" | "ribu" | "juta" | "miliar";
export type Currency = "IDR" | "USD";
export type Basis = "annual" | "quarterly" | "ytd";
export type Period = "FY" | "Q1" | "Q2" | "Q3" | "Q4";
export type Sector =
  | "energy"
  | "basic_materials"
  | "industrials"
  | "consumer_non_cyclicals"
  | "consumer_cyclicals"
  | "healthcare"
  | "financials_bank"
  | "financials_non_bank"
  | "properties"
  | "technology"
  | "infrastructures"
  | "transportation";

export type ValueField =
  | "revenue"
  | "net_income"
  | "net_income_attributable"
  | "total_assets"
  | "total_assets_begin"
  | "total_liabilities"
  | "total_equity"
  | "total_equity_begin"
  | "equity_attributable"
  | "equity_attributable_begin"
  | "current_assets"
  | "current_liabilities"
  | "operating_cash_flow"
  | "capital_expenditure"
  | "weighted_average_shares"
  | "shares_outstanding";

export type FinancialValues = Partial<Record<ValueField, number | null>>;

export interface SourceInfo {
  method: "manual" | "csv" | "xlsx" | "xls" | "pdf";
  file_name?: string | null;
  cell_refs: Record<string, string>;
  edited_after_import: string[];
}

export interface AnalysisInput {
  company: { ticker: string; name: string; sector?: Sector | null };
  statement: {
    fiscal_year: number;
    period: Period;
    basis: Basis;
    currency: Currency;
    unit: Unit;
    fx_rate_to_idr?: number | null;
  };
  current: FinancialValues;
  previous?: { fiscal_year: number; period: Period; values: FinancialValues } | null;
  market: {
    share_price?: number | null;
    share_price_date?: string | null;
    price_source?: string | null;
    price_origin?: "manual" | "provider";
    price_provider?: string | null;
    price_provider_symbol?: string | null;
    price_fetched_at?: string | null;
  };
  source: SourceInfo;
}

export type MetricStatus = "ok" | "unavailable" | "not_meaningful" | "not_applicable";
export type MetricUnit = "percent" | "ratio" | "currency" | "currency_per_share" | "idr_per_share";
export type Severity = "positive" | "negative" | "warning" | "neutral";

export interface MetricResult {
  key: string;
  label: string;
  value: number | null;
  unit: MetricUnit;
  status: MetricStatus;
  formula: string;
  explanation: string | null;
  inputs_used: string[];
  assumptions: string[];
  annualized_value: number | null;
}

export interface ValidationIssue {
  level: "error" | "warning";
  field: string | null;
  message: string;
}

export interface MetricScore {
  metric: string;
  label: string;
  score: number | null;
  basis_value: number | null;
  rule: string;
  note: string | null;
}

export interface DimensionScore {
  key: string;
  label: string;
  weight: number;
  applicable: boolean;
  score: number | null;
  coverage: number;
  metrics: MetricScore[];
  note: string | null;
}

export interface ScoreResult {
  score: number | null;
  status: "complete" | "provisional" | "insufficient" | "unavailable";
  label: string | null;
  coverage: number;
  dimensions: DimensionScore[];
  notes: string[];
}

export type FindingSection =
  | "summary"
  | "profitability"
  | "growth"
  | "leverage_liquidity"
  | "cash_flow"
  | "valuation"
  | "risk"
  | "missing";

export interface Finding {
  section: FindingSection;
  severity: Severity;
  text: string;
  metrics: string[];
}

export interface MissingField {
  field: string;
  label: string;
  blocks: string[];
}

export interface AnalysisResult {
  methodology_version: string;
  scoring_profile: string;
  period_label: string;
  months_covered: number;
  is_financial_sector: boolean;
  metrics: Record<string, MetricResult>;
  fundamental_score: ScoreResult;
  valuation_score: ScoreResult;
  completeness: { percent: number; provided: number; applicable: number; missing: MissingField[] };
  findings: Finding[];
  issues: ValidationIssue[];
  comparability: { comparable?: boolean; previous_label?: string | null; reason?: string | null };
  normalized: {
    currency?: Currency;
    current?: FinancialValues;
    previous?: { fiscal_year: number; period: Period; values: FinancialValues } | null;
  };
  disclaimer: string;
}

export interface InsightContent {
  summary: string;
  strengths: string[];
  risks: string[];
  valuation_observations: string[];
  missing_information: string[];
  conclusion: string;
  limitations: string[];
}

export interface InsightRecord {
  id: string;
  analysis_id: string;
  created_at: string;
  source: "ai" | "rule_based";
  provider: string | null;
  model: string | null;
  fallback_reason: string | null;
  content: InsightContent;
}

export interface AnalysisRecord {
  id: string;
  created_at: string;
  ticker: string;
  company_name: string;
  sector: Sector | null;
  fiscal_year: number;
  period: Period;
  basis: Basis;
  period_label: string;
  methodology_version: string;
  input: AnalysisInput;
  result: AnalysisResult;
  latest_insight?: InsightRecord | null;
}

export interface AnalysisSummary {
  id: string;
  created_at: string;
  ticker: string;
  company_name: string;
  sector: Sector | null;
  fiscal_year: number;
  period: Period;
  basis: Basis;
  period_label: string;
  currency: Currency;
  unit: Unit;
  methodology_version: string;
  fundamental_score: number | null;
  fundamental_status: ScoreResult["status"];
  fundamental_label: string | null;
  valuation_score: number | null;
  valuation_status: ScoreResult["status"];
  completeness: number;
  source_method: SourceInfo["method"];
  key_figures: {
    revenue: number | null;
    net_income: number | null;
    npm: number | null;
    roe: number | null;
    roa: number | null;
    der: number | null;
    operating_cash_flow: number | null;
    free_cash_flow: number | null;
  };
}

export interface AnalysisList {
  items: AnalysisSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface ImportRow {
  row: number;
  code: string;
  field: ValueField | null;
  label: string | null;
  current: number | null;
  previous: number | null;
  status: "ok" | "warning" | "error" | "ignored";
  messages: string[];
}

export interface DetectedMetadata {
  company_name: string | null;
  ticker: string | null;
  fiscal_year: number | null;
  period: Period | null;
  basis: Basis | null;
  period_end: string | null;
  sector?: Sector | null;
  /** Set when a period end was found but its length isn't a supported annual/quarterly period. */
  period_note?: string | null;
  sources: Partial<Record<"company_name" | "ticker" | "fiscal_year" | "period" | "basis" | "period_end" | "sector", string>>;
}

export interface ImportPreview {
  detected?: DetectedMetadata;
  file_name: string;
  file_type: "csv" | "xlsx" | "xls" | "pdf";
  sheet: string | null;
  unit: Unit | null;
  currency: Currency | null;
  current: FinancialValues;
  previous: FinancialValues;
  cell_refs: Record<string, string>;
  rows: ImportRow[];
  errors: string[];
  warnings: string[];
}

export interface HealthStatus {
  status: string;
  version: string;
  methodology_version: string;
  storage: "supabase" | "local";
  auth_required: boolean;
  ai: { configured: boolean; provider: string | null; model: string | null };
  market_data: { configured: boolean; provider: string | null; coverage_note: string };
  max_upload_mb: number;
  max_pdf_upload_mb: number;
}

export interface Quote {
  ticker: string;
  provider: string;
  provider_label: string;
  provider_symbol: string;
  price: number;
  currency: "IDR";
  trading_date: string;
  fetched_at: string;
  note: string;
  cached: boolean;
}
