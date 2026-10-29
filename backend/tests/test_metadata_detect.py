import pytest

from app.core.errors import AppError
from app.services.importer import parse_upload
from app.services.metadata_detect import detect_from_text, ticker_from_file_name
from tests.test_import_pdf_xls import IDX_STATEMENT, MAX, MAX_PDF, make_pdf


@pytest.mark.parametrize("text,basis,period,year,end", [
    ("LAPORAN KEUANGAN KONSOLIDASIAN UNTUK TAHUN YANG BERAKHIR 31 DESEMBER 2024", "annual", "FY", 2024, "2024-12-31"),
    ("For the year ended December 31, 2023", "annual", "FY", 2023, "2023-12-31"),
    ("untuk periode sembilan bulan yang berakhir 30 September 2024", "ytd", "Q3", 2024, "2024-09-30"),
    ("For the six months ended June 30, 2025", "ytd", "Q2", 2025, "2025-06-30"),
    ("periode tiga bulan yang berakhir pada tanggal 31 Maret 2024", "ytd", "Q1", 2024, "2024-03-31"),
])
def test_period_detection(text, basis, period, year, end):
    d = detect_from_text(text, "", "PDF hal. 1")
    assert (d["basis"], d["period"], d["fiscal_year"], d["period_end"]) == (basis, period, year, end)
    assert d["sources"]["fiscal_year"] == "PDF hal. 1"


def test_no_period_is_none():
    d = detect_from_text("Laporan tahunan 2024. Visi dan misi.", "", "PDF hal. 1")
    assert d["basis"] is None and d["fiscal_year"] is None and "fiscal_year" not in d["sources"]


@pytest.mark.parametrize("text,name", [
    ("PT BANK CENTRAL ASIA TBK DAN ENTITAS ANAK", "PT Bank Central Asia Tbk"),
    ("PT Telkom Indonesia (Persero) Tbk and subsidiaries", "PT Telkom Indonesia (Persero) Tbk"),
    ("PT XL AXIATA TBK", "PT XL Axiata Tbk"),
])
def test_company_name(text, name):
    assert detect_from_text(text, "", "PDF hal. 1")["company_name"] == name


def test_ticker_from_text_beats_file_name():
    d = detect_from_text("Kode saham: TLKM", "BBCA_LK_2024.pdf", "PDF hal. 2")
    assert d["ticker"] == "TLKM" and d["sources"]["ticker"] == "PDF hal. 2"


@pytest.mark.parametrize("name,ticker", [
    ("BBCA_LK_2024.pdf", "BBCA"),
    ("FinancialStatement-2024-Tahunan-TLKM.pdf", "TLKM"),
    ("laporan keuangan 2024.pdf", None),
    ("FULL_DATA_2024.pdf", None),
    ("bbca.pdf", None),  # lower case is too ambiguous
])
def test_ticker_from_file_name(name, ticker):
    assert ticker_from_file_name(name) == ticker


def _with_cover(cover_lines):
    return [cover_lines] + IDX_STATEMENT[1:]


def test_pdf_returns_detected_metadata():
    pages = _with_cover(["PT CONTOH TBK DAN ENTITAS ANAK", "LAPORAN KEUANGAN KONSOLIDASIAN",
                         "UNTUK TAHUN YANG BERAKHIR 31 DESEMBER 2024 DAN 2023"])
    out = parse_upload(make_pdf(pages), "ABCD_LK_2024.pdf", MAX, MAX_PDF)
    d = out["detected"]
    assert d["company_name"] == "PT Contoh Tbk"
    assert (d["fiscal_year"], d["basis"], d["period"]) == (2024, "annual", "FY")
    assert d["ticker"] == "ABCD" and d["sources"]["ticker"] == "nama berkas"
    assert d["sources"]["company_name"] == "PDF hal. 1"
    assert out["current"]["total_assets"] == 299_675  # values still extracted


def test_pdf_interim_metadata():
    pages = _with_cover(["PT CONTOH TBK", "LAPORAN KEUANGAN INTERIM",
                         "UNTUK PERIODE SEMBILAN BULAN YANG BERAKHIR 30 SEPTEMBER 2025"])
    d = parse_upload(make_pdf(pages), "laporan.pdf", MAX, MAX_PDF)["detected"]
    assert (d["fiscal_year"], d["basis"], d["period"]) == (2025, "ytd", "Q3")
    assert d["ticker"] is None  # not guessed


def test_template_company_rows():
    csv = (
        "kode,keterangan,periode_berjalan,periode_sebelumnya\n"
        "kode_saham,,bbca,\n"
        "nama_perusahaan,,PT Bank Central Asia Tbk,\n"
        "tahun_fiskal,,2024,\n"
        "jenis_laporan,,tahunan,\n"
        "periode,,,\n"
        "revenue,,100,\n"
    ).encode()
    out = parse_upload(csv, "x.csv", MAX)
    d = out["detected"]
    assert d["ticker"] == "BBCA" and d["company_name"] == "PT Bank Central Asia Tbk"
    assert (d["fiscal_year"], d["basis"], d["period"]) == (2024, "annual", "FY")
    assert d["sources"]["ticker"].startswith("baris 2")
    assert not out["errors"]


def test_template_company_rows_invalid():
    csv = ("kode,periode_berjalan\nkode_saham,BB\ntahun_fiskal,1850\njenis_laporan,bulanan\nrevenue,100\n").encode()
    out = parse_upload(csv, "x.csv", MAX)
    assert len(out["errors"]) == 3
    assert out["detected"]["ticker"] is None and out["detected"]["fiscal_year"] is None


def test_template_still_roundtrips():
    from app.services.importer import template_csv

    out = parse_upload(template_csv(), "t.csv", MAX)
    assert not out["errors"] and out["detected"]["ticker"] is None


def test_scanned_still_rejected():
    with pytest.raises(AppError):
        parse_upload(make_pdf([[""]] * 5), "BBCA.pdf", MAX, MAX_PDF)


def test_quarter_end_from_balance_sheet_date():
    d = detect_from_text("Laporan posisi keuangan pada tanggal 30 Juni 2025", "", "PDF hal. 1")
    assert (d["basis"], d["period"], d["fiscal_year"]) == ("ytd", "Q2", 2025)


def test_bank_sector_from_name():
    assert detect_from_text("PT BANK RAKYAT INDONESIA (PERSERO) TBK", "", "p")["sector"] == "financials_bank"
    assert detect_from_text("PT TELKOM INDONESIA TBK", "", "p")["sector"] is None
