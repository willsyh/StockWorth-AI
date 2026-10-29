"""Input schemas for financial statement data.

Conventions
-----------
* All monetary statement values are entered in the statement currency and unit
  chosen by the user (e.g. "juta" = millions of IDR) and are normalised to whole
  currency units before any calculation.
* Share counts are always entered as a number of shares (lembar), never scaled.
* Share price is always in IDR per share (IDX quotes in rupiah).
* `None` means "not provided". It is never treated as zero.
"""

import math
import re
from datetime import date
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator


class Unit(str, Enum):
    unit = "unit"
    ribu = "ribu"
    juta = "juta"
    miliar = "miliar"


UNIT_MULTIPLIER: dict[Unit, float] = {
    Unit.unit: 1.0,
    Unit.ribu: 1e3,
    Unit.juta: 1e6,
    Unit.miliar: 1e9,
}


class Currency(str, Enum):
    IDR = "IDR"
    USD = "USD"


class Basis(str, Enum):
    annual = "annual"  # full fiscal year (12 months)
    quarterly = "quarterly"  # a single, discrete 3-month quarter
    ytd = "ytd"  # cumulative from start of fiscal year (year-to-date)


class Period(str, Enum):
    FY = "FY"
    Q1 = "Q1"
    Q2 = "Q2"
    Q3 = "Q3"
    Q4 = "Q4"


class Sector(str, Enum):
    """IDX Industrial Classification (IDX-IC) sectors, with financials split into bank / non-bank."""

    energy = "energy"
    basic_materials = "basic_materials"
    industrials = "industrials"
    consumer_non_cyclicals = "consumer_non_cyclicals"
    consumer_cyclicals = "consumer_cyclicals"
    healthcare = "healthcare"
    financials_bank = "financials_bank"
    financials_non_bank = "financials_non_bank"
    properties = "properties"
    technology = "technology"
    infrastructures = "infrastructures"
    transportation = "transportation"


SECTOR_LABELS: dict[Sector, str] = {
    Sector.energy: "Energi",
    Sector.basic_materials: "Barang Baku",
    Sector.industrials: "Perindustrian",
    Sector.consumer_non_cyclicals: "Barang Konsumen Primer",
    Sector.consumer_cyclicals: "Barang Konsumen Non-Primer",
    Sector.healthcare: "Kesehatan",
    Sector.financials_bank: "Keuangan — Perbankan",
    Sector.financials_non_bank: "Keuangan — Non-Bank",
    Sector.properties: "Properti & Real Estat",
    Sector.technology: "Teknologi",
    Sector.infrastructures: "Infrastruktur",
    Sector.transportation: "Transportasi & Logistik",
}


def months_covered(basis: Basis, period: Period) -> int:
    if basis == Basis.annual:
        return 12
    if basis == Basis.quarterly:
        return 3
    return {Period.Q1: 3, Period.Q2: 6, Period.Q3: 9, Period.Q4: 12, Period.FY: 12}[period]


def period_label(fiscal_year: int, period: Period, basis: Basis) -> str:
    if basis == Basis.annual:
        return f"FY{fiscal_year}"
    if basis == Basis.ytd:
        return f"{months_covered(basis, period)}M{fiscal_year} (kumulatif)"
    return f"{period.value} {fiscal_year}"


# Field metadata shared by validation, the import template and the UI.
MONETARY_FIELDS = [
    "revenue",
    "net_income",
    "net_income_attributable",
    "total_assets",
    "total_assets_begin",
    "total_liabilities",
    "total_equity",
    "total_equity_begin",
    "equity_attributable",
    "equity_attributable_begin",
    "current_assets",
    "current_liabilities",
    "operating_cash_flow",
    "capital_expenditure",
]
SHARE_FIELDS = ["weighted_average_shares", "shares_outstanding"]
VALUE_FIELDS = MONETARY_FIELDS + SHARE_FIELDS

FIELD_LABELS: dict[str, str] = {
    "revenue": "Pendapatan",
    "net_income": "Laba bersih (total)",
    "net_income_attributable": "Laba bersih yang dapat diatribusikan ke pemilik entitas induk",
    "total_assets": "Total aset (akhir periode)",
    "total_assets_begin": "Total aset (awal periode)",
    "total_liabilities": "Total liabilitas",
    "total_equity": "Total ekuitas (akhir periode)",
    "total_equity_begin": "Total ekuitas (awal periode)",
    "equity_attributable": "Ekuitas pemilik entitas induk (akhir periode)",
    "equity_attributable_begin": "Ekuitas pemilik entitas induk (awal periode)",
    "current_assets": "Aset lancar",
    "current_liabilities": "Liabilitas jangka pendek",
    "operating_cash_flow": "Arus kas dari aktivitas operasi",
    "capital_expenditure": "Belanja modal (capex)",
    "weighted_average_shares": "Rata-rata tertimbang saham biasa beredar",
    "shares_outstanding": "Jumlah saham beredar (akhir periode)",
}

# Fields that must not be negative. Equity, net income and cash flow can legitimately be negative.
NON_NEGATIVE_FIELDS = {
    "revenue",
    "total_assets",
    "total_assets_begin",
    "total_liabilities",
    "current_assets",
    "current_liabilities",
    "capital_expenditure",
}
POSITIVE_FIELDS = {"weighted_average_shares", "shares_outstanding"}

MAX_ABS_VALUE = 1e18  # guards against absurd inputs / overflow; ~1 quintillion


def _check_number(name: str, v: float | None) -> float | None:
    if v is None:
        return None
    if isinstance(v, bool):
        raise ValueError(f"{FIELD_LABELS.get(name, name)} harus berupa angka.")
    if not math.isfinite(v):
        raise ValueError(f"{FIELD_LABELS.get(name, name)} harus berupa angka yang valid.")
    if abs(v) > MAX_ABS_VALUE:
        raise ValueError(f"{FIELD_LABELS.get(name, name)} di luar rentang yang wajar.")
    if name in NON_NEGATIVE_FIELDS and v < 0:
        hint = " Masukkan belanja modal sebagai angka positif." if name == "capital_expenditure" else ""
        raise ValueError(f"{FIELD_LABELS.get(name, name)} tidak boleh negatif.{hint}")
    if name in POSITIVE_FIELDS and v <= 0:
        raise ValueError(f"{FIELD_LABELS.get(name, name)} harus lebih besar dari nol.")
    return float(v)


class FinancialValues(BaseModel):
    """Values for one reporting period, in the statement unit/currency. All optional."""

    model_config = ConfigDict(extra="forbid")

    revenue: float | None = Field(None, description="Pendapatan / penjualan bersih")
    net_income: float | None = Field(None, description="Laba bersih periode berjalan (total)")
    net_income_attributable: float | None = Field(
        None, description="Laba bersih yang dapat diatribusikan ke pemilik entitas induk"
    )
    total_assets: float | None = None
    total_assets_begin: float | None = None
    total_liabilities: float | None = None
    total_equity: float | None = None
    total_equity_begin: float | None = None
    equity_attributable: float | None = None
    equity_attributable_begin: float | None = None
    current_assets: float | None = None
    current_liabilities: float | None = None
    operating_cash_flow: float | None = None
    capital_expenditure: float | None = Field(None, description="Belanja modal, sebagai angka positif")
    weighted_average_shares: float | None = Field(None, description="Jumlah lembar, tidak diskalakan")
    shares_outstanding: float | None = Field(None, description="Jumlah lembar, tidak diskalakan")

    @field_validator(*VALUE_FIELDS, mode="after")
    @classmethod
    def _validate_value(cls, v, info: ValidationInfo):
        return _check_number(info.field_name, v)

    def provided_fields(self) -> list[str]:
        return [f for f in VALUE_FIELDS if getattr(self, f) is not None]


TICKER_RE = re.compile(r"^[A-Z]{4}$")


class CompanyInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(..., description="Kode saham BEI, 4 huruf (mis. BBCA)")
    name: str = Field(..., min_length=2, max_length=160)
    sector: Sector | None = None

    @field_validator("ticker", mode="before")
    @classmethod
    def _ticker(cls, v):
        if not isinstance(v, str):
            raise ValueError("Kode saham harus berupa teks.")
        t = v.strip().upper()
        if not TICKER_RE.match(t):
            raise ValueError("Kode saham harus terdiri dari 4 huruf, contoh: BBCA.")
        return t

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, v):
        if not isinstance(v, str):
            raise ValueError("Nama perusahaan harus berupa teks.")
        name = " ".join(v.split())
        if any(ord(c) < 32 for c in name):
            raise ValueError("Nama perusahaan mengandung karakter yang tidak valid.")
        return name


class StatementInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fiscal_year: int = Field(..., ge=1990, le=2100)
    period: Period
    basis: Basis
    currency: Currency = Currency.IDR
    unit: Unit = Unit.juta
    fx_rate_to_idr: float | None = Field(
        None, gt=0, description="Kurs IDR per 1 unit mata uang laporan; wajib untuk valuasi jika laporan bukan IDR"
    )

    @model_validator(mode="after")
    def _consistent(self):
        if self.basis == Basis.annual and self.period != Period.FY:
            raise ValueError("Laporan tahunan harus menggunakan periode FY.")
        if self.basis != Basis.annual and self.period == Period.FY:
            raise ValueError("Laporan kuartalan/kumulatif harus menggunakan periode Q1–Q4.")
        if self.fx_rate_to_idr is not None and not math.isfinite(self.fx_rate_to_idr):
            raise ValueError("Kurs harus berupa angka yang valid.")
        if self.currency == Currency.IDR and self.fx_rate_to_idr not in (None, 1.0):
            raise ValueError("Kurs hanya diisi jika mata uang laporan bukan IDR.")
        return self

    @property
    def months(self) -> int:
        return months_covered(self.basis, self.period)

    @property
    def label(self) -> str:
        return period_label(self.fiscal_year, self.period, self.basis)


class PreviousPeriod(BaseModel):
    """Comparative period. Uses the same currency, unit and basis as the current statement."""

    model_config = ConfigDict(extra="forbid")

    fiscal_year: int = Field(..., ge=1990, le=2100)
    period: Period
    values: FinancialValues = Field(default_factory=FinancialValues)


class MarketData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    share_price: float | None = Field(None, gt=0, le=10_000_000, description="Harga saham (IDR per lembar)")
    share_price_date: date | None = None
    price_source: str | None = Field(None, max_length=200, description="Catatan sumber harga dari pengguna")
    # "provider" only when the price was fetched by the server; it is re-verified on save.
    price_origin: Literal["manual", "provider"] = "manual"
    price_provider: str | None = Field(None, max_length=40)
    price_provider_symbol: str | None = Field(None, max_length=20)
    price_fetched_at: str | None = Field(None, max_length=40)

    @model_validator(mode="after")
    def _check(self):
        if self.price_origin == "provider" and (self.share_price is None or not self.price_provider):
            raise ValueError("Harga dari penyedia data harus menyertakan harga dan nama penyedia.")
        if self.share_price is not None and self.share_price_date is None:
            raise ValueError("Tanggal harga saham wajib diisi jika harga saham diisi.")
        if self.share_price_date is not None and self.share_price_date > date.today():
            raise ValueError("Tanggal harga saham tidak boleh di masa depan.")
        return self


class SourceInfo(BaseModel):
    """Where the numbers came from, so every value stays traceable."""

    model_config = ConfigDict(extra="forbid")

    method: Literal["manual", "csv", "xlsx", "xls", "pdf"] = "manual"
    file_name: str | None = Field(None, max_length=255)
    # field key -> human-readable location, e.g. "Sheet1!C5" or "baris 7"
    cell_refs: dict[str, str] = Field(default_factory=dict)
    edited_after_import: list[str] = Field(default_factory=list)


class AnalysisInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: CompanyInfo
    statement: StatementInfo
    current: FinancialValues
    previous: PreviousPeriod | None = None
    market: MarketData = Field(default_factory=MarketData)
    source: SourceInfo = Field(default_factory=SourceInfo)
