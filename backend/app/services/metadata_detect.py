"""Detect company and period information from statement text and file names.

Everything here is a suggestion for the user to confirm, never ground truth. A value that
cannot be found is returned as None; nothing is guessed.
"""

import re

MONTHS = {
    # Indonesian
    "januari": 1, "februari": 2, "maret": 3, "april": 4, "mei": 5, "juni": 6, "juli": 7,
    "agustus": 8, "september": 9, "oktober": 10, "november": 11, "desember": 12,
    # English
    "january": 1, "february": 2, "march": 3, "may": 5, "june": 6, "july": 7, "august": 8,
    "october": 10, "december": 12,
}
_MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))
_NUM_WORDS = {"tiga": 3, "three": 3, "enam": 6, "six": 6, "sembilan": 9, "nine": 9, "dua belas": 12, "twelve": 12}
_NUM_RE = "|".join(sorted(_NUM_WORDS, key=len, reverse=True))

# "31 Desember 2024" or "December 31, 2024"
_DATE_ID = rf"(?P<d1>\d{{1,2}})\s+(?P<m1>{_MONTH_RE})\s+(?P<y1>(19|20)\d{{2}})"
_DATE_EN = rf"(?P<m2>{_MONTH_RE})\s+(?P<d2>\d{{1,2}}),?\s+(?P<y2>(19|20)\d{{2}})"
_DATE = rf"(?:{_DATE_ID}|{_DATE_EN})"

ANNUAL_RE = re.compile(rf"(tahun yang berakhir|tahun berakhir|years? ended)\s+(pada\s+(tanggal\s+)?)?{_DATE}", re.I)
INTERIM_RE = re.compile(
    rf"(?:periode\s+)?(?P<n>{_NUM_RE}|\d{{1,2}})\s+(bulan|months)\s+(yang\s+)?(berakhir|ended)\s+(pada\s+(tanggal\s+)?)?{_DATE}",
    re.I,
)
PERIOD_END_RE = re.compile(
    rf"(periode yang berakhir|berakhir pada tanggal|pada tanggal|per tanggal|as of|as at|ended)\s+"
    rf"(pada\s+)?(tanggal\s+)?{_DATE}",
    re.I,
)
MONTH_NAMES_ID = ["", "Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September",
                  "Oktober", "November", "Desember"]
COMPANY_RE = re.compile(r"\bPT\.?\s+([A-Z0-9][A-Za-z0-9&.,'()\- ]{2,90}?)\s*,?\s+(Tbk|TBK)\b")
TICKER_TEXT_RE = re.compile(
    r"(?:kode\s+(?:saham|emiten|efek|perusahaan)|stock\s+code|ticker(?:\s+code)?|idx\s*(?:code)?)\s*[:\-]?\s*\(?([A-Z]{4})\b"
    r"|\((?:IDX|BEI)\s*[:\-]\s*([A-Z]{4})\)",
    re.I,
)
# Four-letter upper-case words that commonly appear in file names but are not tickers.
NOT_TICKERS = {
    "FULL", "DATA", "FILE", "COPY", "SCAN", "PAGE", "LAPK", "TAHN", "AKHR", "NOTE", "INFO", "MAIN", "BOOK",
    "AUDI", "LKKT", "LKTA", "YEAR", "PART", "FINL", "REPT", "TEMP", "TEST", "DRAF", "FINA",
}


def _parse_date(m: re.Match) -> tuple[int, int, int] | None:
    g = m.groupdict()
    if g.get("y1"):
        day, month, year = g["d1"], g["m1"], g["y1"]
    elif g.get("y2"):
        day, month, year = g["d2"], g["m2"], g["y2"]
    else:
        return None
    mon = MONTHS.get(month.lower())
    if not mon:
        return None
    return int(year), mon, int(day)


def _clean_company(raw: str) -> str:
    name = re.sub(r"\s+", " ", raw).strip(" ,.-")
    name = re.sub(r"\s+(dan entitas anak|and subsidiaries?|dan anak perusahaan)\b.*$", "", name, flags=re.I)
    if name.isupper():
        # Title-case shouty names but keep short all-caps tokens (e.g. "BCA", "XL") as they are.
        name = " ".join(w if len(w) <= 3 and w.isalpha() else w.capitalize() for w in name.split())
    return f"PT {name} Tbk"


def ticker_from_file_name(file_name: str) -> str | None:
    stem = file_name.rsplit(".", 1)[0]
    for tok in re.split(r"[^A-Za-z]+", stem):
        if len(tok) == 4 and tok.isupper() and tok not in NOT_TICKERS:
            return tok
    return None


def detect_from_text(text: str, file_name: str, source_label: str) -> dict:
    """Return detected metadata plus where each value came from."""
    out: dict = {"company_name": None, "ticker": None, "fiscal_year": None, "period": None, "basis": None,
                 "period_end": None, "sector": None, "period_note": None, "sources": {}}

    m = COMPANY_RE.search(text)
    if m:
        out["company_name"] = _clean_company(m.group(1))
        out["sources"]["company_name"] = source_label
        if re.match(r"bank\b", m.group(1).strip(), re.I):
            out["sector"], out["sources"]["sector"] = "financials_bank", source_label

    m = TICKER_TEXT_RE.search(text)
    tick = (m.group(1) or m.group(2)).upper() if m else None
    if tick and tick not in NOT_TICKERS:
        out["ticker"], out["sources"]["ticker"] = tick, source_label
    else:
        tick = ticker_from_file_name(file_name)
        if tick:
            out["ticker"], out["sources"]["ticker"] = tick, "nama berkas"

    # Interim wording is more specific, so check it first ("sembilan bulan yang berakhir ...").
    m = INTERIM_RE.search(text)
    if m and (d := _parse_date(m)):
        n_raw = m.group("n").lower()
        months = _NUM_WORDS.get(n_raw) or (int(n_raw) if n_raw.isdigit() else None)
        year, month, day = d
        if months == 12:
            out.update(basis="annual", period="FY")
        elif months in (3, 6, 9):
            out.update(basis="ytd", period={3: "Q1", 6: "Q2", 9: "Q3"}[months])
        if out["basis"]:
            out["fiscal_year"] = year
            out["period_end"] = f"{year:04d}-{month:02d}-{day:02d}"
    if out["basis"] is None:
        m = ANNUAL_RE.search(text)
        if m and (d := _parse_date(m)):
            year, month, day = d
            out.update(basis="annual", period="FY", fiscal_year=year, period_end=f"{year:04d}-{month:02d}-{day:02d}")
    if out["basis"] is None:
        m = PERIOD_END_RE.search(text)
        if m and (d := _parse_date(m)):
            year, month, day = d
            out["fiscal_year"], out["period_end"] = year, f"{year:04d}-{month:02d}-{day:02d}"
            out["sources"]["fiscal_year"] = source_label
            if month == 12:
                out.update(basis="annual", period="FY")
            elif month in (3, 6, 9):
                out.update(basis="ytd", period={3: "Q1", 6: "Q2", 9: "Q3"}[month])
            else:
                out["period_note"] = (
                    f"Laporan ini mencakup periode s.d. {day} {MONTH_NAMES_ID[month]} {year} ({month} bulan). "
                    "Aplikasi baru mendukung laporan tahunan dan kuartalan (3, 6, 9 bulan), jadi jenis laporan "
                    "belum diisi otomatis. Rasio yang disetahunkan dan PER tidak akan tepat untuk periode ini."
                )
    if out["basis"]:
        for k in ("fiscal_year", "period", "basis", "period_end"):
            out["sources"][k] = source_label
    return out
