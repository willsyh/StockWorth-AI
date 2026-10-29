import io
import zipfile

import pytest
from openpyxl import Workbook

from app.core.errors import AppError
from app.services.importer import parse_number, parse_upload, safe_file_name, template_csv, template_xlsx

MAX = 2 * 1024 * 1024


@pytest.mark.parametrize("raw,expected", [
    ("1.234.567", 1234567),
    ("1,234,567", 1234567),
    ("1.234.567,89", 1234567.89),
    ("1,234,567.89", 1234567.89),
    ("(1.500.000)", -1500000),
    ("-2.500", -2500),
    ("Rp 3.000.000", 3000000),
    ("12,5", 12.5),
    ("12.5", 12.5),
    (42, 42),
    (3.5, 3.5),
    ("", None),
    ("-", None),
    (None, None),
])
def test_parse_number(raw, expected):
    value, _ = parse_number(raw)
    assert value == (pytest.approx(expected) if expected is not None else None)


def test_parse_number_ambiguous_warns():
    value, warning = parse_number("1.234")
    assert value == 1234
    assert warning and "ambigu" in warning


@pytest.mark.parametrize("raw", ["abc", "=SUM(A1:A3)", "1.2.3,4,5", "12a"])
def test_parse_number_invalid(raw):
    with pytest.raises(ValueError):
        parse_number(raw)


def _csv(text: str) -> bytes:
    return text.encode("utf-8")


def test_csv_import_basic():
    content = _csv(
        "kode,keterangan,periode_berjalan,periode_sebelumnya\n"
        "satuan,,miliar,\n"
        "revenue,Pendapatan,\"1.500\",\"1.200\"\n"
        "net_income,Laba,300,250\n"
        "capital_expenditure,Capex,-50,\n"
        "unknown_code,Apa,1,\n"
    )
    out = parse_upload(content, "laporan.csv", MAX)
    assert out["unit"] == "miliar"
    assert out["current"]["revenue"] == 1500
    assert out["previous"]["revenue"] == 1200
    assert out["current"]["capital_expenditure"] == 50  # negative capex normalised with warning
    assert any("Belanja modal negatif" in w for w in out["warnings"])
    assert any(r["status"] == "ignored" for r in out["rows"])
    assert out["cell_refs"]["current.revenue"].startswith("baris 3")
    assert not out["errors"]
    ambiguous_notes = [w for w in out["warnings"] if "pemisah ribuan" in w]
    assert len(ambiguous_notes) == 1  # aggregated, not one per row


def test_csv_semicolon_and_row_errors():
    content = _csv(
        "kode;periode_berjalan;periode_sebelumnya\n"
        "revenue;1.000.000;abc\n"
        "revenue;5;\n"
        "total_assets;-10;\n"
    )
    out = parse_upload(content, "x.csv", MAX)
    assert out["current"]["revenue"] == 1_000_000
    assert "revenue" not in out["previous"]
    assert len(out["errors"]) == 3  # bad number, duplicate, negative assets


def test_csv_missing_required_columns():
    with pytest.raises(AppError) as e:
        parse_upload(_csv("a,b\n1,2\n"), "x.csv", MAX)
    assert e.value.code == "invalid_template"


def test_csv_formula_rejected():
    out = parse_upload(_csv("kode,periode_berjalan\nrevenue,=1+1\n"), "x.csv", MAX)
    assert out["errors"] and "Formula" in out["errors"][0]
    assert "revenue" not in out["current"]


@pytest.mark.parametrize("name", ["a.pdf", "a.exe", "a.xls", "a.xlsm", "noext"])
def test_unsupported_extensions(name):
    with pytest.raises(AppError) as e:
        parse_upload(b"data", name, MAX)
    assert e.value.status_code == 415


def test_file_too_large():
    with pytest.raises(AppError) as e:
        parse_upload(b"x" * 100, "a.csv", 50)
    assert e.value.status_code == 413


def test_empty_file():
    with pytest.raises(AppError):
        parse_upload(b"", "a.csv", MAX)


def test_fake_xlsx_rejected():
    with pytest.raises(AppError) as e:
        parse_upload(b"not a zip at all", "a.xlsx", MAX)
    assert e.value.status_code == 415


def test_xlsx_with_macro_rejected():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("xl/workbook.xml", "<x/>")
        zf.writestr("xl/vbaProject.bin", "evil")
    with pytest.raises(AppError) as e:
        parse_upload(buf.getvalue(), "a.xlsx", MAX)
    assert e.value.code == "macro_not_allowed"


def test_xlsx_import_and_formula_without_cached_value():
    wb = Workbook()
    ws = wb.active
    ws.title = "Data"
    ws.append(["kode", "keterangan", "periode_berjalan", "periode_sebelumnya"])
    ws.append(["revenue", "Pendapatan", 1500, 1200])
    ws.append(["net_income", "Laba", "=B2*0.2", None])  # openpyxl saves formulas without cached values
    buf = io.BytesIO()
    wb.save(buf)
    out = parse_upload(buf.getvalue(), "lap.xlsx", MAX)
    assert out["sheet"] == "Data"
    assert out["current"]["revenue"] == 1500
    assert out["cell_refs"]["current.revenue"] == "Data!C2"
    assert "net_income" not in out["current"]
    assert any("formula" in e for e in out["errors"])


def test_templates_roundtrip():
    out = parse_upload(template_csv(), "t.csv", MAX)
    assert out["unit"] == "juta" and out["currency"] == "IDR"
    assert out["current"] == {}
    out = parse_upload(template_xlsx(), "t.xlsx", MAX)
    assert out["unit"] == "juta"


def test_safe_file_name_strips_paths():
    assert safe_file_name("../../etc/passwd") == "passwd"
    assert safe_file_name("C:\\x\\..\\evil<>.csv") == "evil__.csv"
    assert safe_file_name(None) == "berkas"
