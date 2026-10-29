from pathlib import Path

import pytest
from fpdf import FPDF

from app.core.errors import AppError
from app.services.importer import parse_upload

MAX = 2 * 1024 * 1024
MAX_PDF = 20 * 1024 * 1024
FIXTURES = Path(__file__).parent / "fixtures"


def make_pdf(pages: list[list[str]], password: str | None = None) -> bytes:
    pdf = FPDF()
    if password:
        pdf.set_encryption(owner_password="owner", user_password=password)
    pdf.set_font("Helvetica", size=9)
    for lines in pages:
        pdf.add_page()
        for line in lines:
            pdf.cell(0, 6, line, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


IDX_STATEMENT = [
    ["PT CONTOH TBK", "LAPORAN KEUANGAN KONSOLIDASIAN", "31 DESEMBER 2024 DAN 2023"],
    [
        "LAPORAN POSISI KEUANGAN KONSOLIDASIAN / CONSOLIDATED STATEMENT OF FINANCIAL POSITION",
        "(Disajikan dalam jutaan Rupiah, kecuali dinyatakan lain)",
        "Catatan 2024 2023",
        "Kas dan setara kas 4 20.000 18.000 Cash and cash equivalents",
        "JUMLAH ASET LANCAR 56.000 50.000 TOTAL CURRENT ASSETS",
        "JUMLAH ASET 299.675 287.042 TOTAL ASSETS",
        "JUMLAH LIABILITAS JANGKA PENDEK 71.000 65.000 TOTAL CURRENT LIABILITIES",
        "JUMLAH LIABILITAS 130.480 131.042 TOTAL LIABILITIES",
        "Ekuitas yang dapat diatribusikan kepada pemilik entitas induk 131.000 125.000",
        "JUMLAH EKUITAS 169.195 156.000 TOTAL EQUITY",
        "JUMLAH LIABILITAS DAN EKUITAS 299.675 287.042 TOTAL LIABILITIES AND EQUITY",
    ],
    [
        "LAPORAN LABA RUGI DAN PENGHASILAN KOMPREHENSIF LAIN KONSOLIDASIAN",
        "(Disajikan dalam jutaan Rupiah)",
        "Pendapatan 2c,25 149.967 149.216 Revenues",
        "Beban usaha (100.000) (98.000) Operating expenses",
        "Pendapatan bunga 1.200 900 Interest income",
        "LABA TAHUN BERJALAN 33.000 32.208 PROFIT FOR THE YEAR",
        "Laba tahun berjalan yang dapat diatribusikan kepada: Profit for the year attributable to:",
        "Pemilik entitas induk 23.649 24.560 Owners of the parent",
        "Kepentingan nonpengendali 9.351 7.648 Non-controlling interests",
        "Jumlah penghasilan komprehensif yang dapat diatribusikan kepada:",
        "Pemilik entitas induk 22.000 23.000 Owners of the parent",
    ],
    [
        "LAPORAN ARUS KAS KONSOLIDASIAN",
        "(Disajikan dalam jutaan Rupiah)",
        "Arus kas bersih diperoleh dari aktivitas operasi 61.000 65.000",
        "Perolehan aset tetap (33.000) (34.000) Acquisition of fixed assets",
    ],
]


def test_pdf_idx_statement_extraction():
    out = parse_upload(make_pdf(IDX_STATEMENT), "laporan.pdf", MAX, MAX_PDF)
    c, p = out["current"], out["previous"]
    assert out["file_type"] == "pdf" and out["unit"] == "juta" and out["currency"] == "IDR"
    assert c["revenue"] == 149_967 and p["revenue"] == 149_216  # note ref "2c,25" ignored
    assert c["total_assets"] == 299_675 and c["current_assets"] == 56_000
    assert c["total_liabilities"] == 130_480 and c["current_liabilities"] == 71_000
    assert c["total_equity"] == 169_195 and c["equity_attributable"] == 131_000
    assert c["net_income"] == 33_000
    assert c["net_income_attributable"] == 23_649  # first "owners" line (profit), not comprehensive income
    assert c["operating_cash_flow"] == 61_000
    assert c["capital_expenditure"] == 33_000 and p["capital_expenditure"] == 34_000  # made positive
    assert out["cell_refs"]["current.total_assets"] == "PDF hal. 2"
    assert all(r["status"] == "warning" for r in out["rows"])  # every PDF value must be checked
    assert any("Cocokkan" in w for w in out["warnings"])
    assert any("rata-rata tertimbang" in w.lower() for w in out["warnings"])  # not found -> reported


def test_pdf_template_layout():
    pages = [["kode keterangan periode_berjalan periode_sebelumnya", "revenue Pendapatan 1.500 1.200",
              "net_income Laba 300.000 250.000", "Disajikan dalam miliaran Rupiah"]]
    out = parse_upload(make_pdf(pages), "t.pdf", MAX, MAX_PDF)
    assert out["current"]["revenue"] == 1500 and out["previous"]["revenue"] == 1200
    assert out["current"]["net_income"] == 300_000
    assert out["unit"] == "miliar"


def test_pdf_usd_detected():
    pages = [["(Expressed in thousands of US Dollars)", "TOTAL ASSETS 12.345 11.000"]]
    out = parse_upload(make_pdf(pages), "usd.pdf", MAX, MAX_PDF)
    assert out["currency"] == "USD" and out["unit"] == "ribu"


def test_pdf_scanned_rejected():
    out_pdf = make_pdf([[""], [""], [""], [""], [""]])
    with pytest.raises(AppError) as e:
        parse_upload(out_pdf, "scan.pdf", MAX, MAX_PDF)
    assert e.value.code == "pdf_scanned"


def test_pdf_encrypted_rejected():
    with pytest.raises(AppError) as e:
        parse_upload(make_pdf(IDX_STATEMENT, password="rahasia"), "lock.pdf", MAX, MAX_PDF)
    assert e.value.code == "pdf_encrypted"


def test_pdf_fake_rejected():
    with pytest.raises(AppError) as e:
        parse_upload(b"not a pdf", "x.pdf", MAX, MAX_PDF)
    assert e.value.status_code == 415


def test_pdf_size_limit_separate_from_spreadsheets():
    big = b"%PDF-1.4" + b"0" * (3 * 1024 * 1024)
    with pytest.raises(AppError) as e:
        parse_upload(big, "big.csv", MAX, MAX_PDF)
    assert e.value.status_code == 413
    with pytest.raises(AppError) as e:  # same size is allowed for PDF, then fails as malformed, not too large
        parse_upload(big, "big.pdf", MAX, MAX_PDF)
    assert e.value.status_code == 422


def test_pdf_no_known_items():
    out = parse_upload(make_pdf([["Laporan tahunan " * 20, "Visi dan misi perusahaan " * 10]]), "x.pdf", MAX, MAX_PDF)
    assert out["current"] == {} and any("Tidak ada akun" in w for w in out["warnings"])


def test_xls_import():
    out = parse_upload((FIXTURES / "sample.xls").read_bytes(), "lama.xls", MAX)
    assert out["file_type"] == "xls" and out["sheet"] == "Data" and out["unit"] == "miliar"
    assert out["current"]["revenue"] == 1500 and out["previous"]["revenue"] == 1200
    assert out["current"]["capital_expenditure"] == 50  # negative capex normalised
    assert out["cell_refs"]["current.revenue"] == "Data!C3"
    assert any("abc" in e for e in out["errors"])
    assert any("formula tidak dijalankan" in w for w in out["warnings"])


def test_xls_fake_rejected():
    with pytest.raises(AppError) as e:
        parse_upload(b"PK\x03\x04 not ole", "x.xls", MAX)
    assert e.value.status_code == 415


def test_xls_with_macro_rejected():
    content = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64 + "_VBA_PROJECT".encode("utf-16-le")
    with pytest.raises(AppError) as e:
        parse_upload(content, "makro.xls", MAX)
    assert e.value.code == "macro_not_allowed"


def test_import_endpoint_accepts_pdf(client):
    files = {"file": ("lap.pdf", make_pdf(IDX_STATEMENT), "application/pdf")}
    r = client.post("/api/analysis/import", files=files)
    assert r.status_code == 200 and r.json()["current"]["total_assets"] == 299_675
