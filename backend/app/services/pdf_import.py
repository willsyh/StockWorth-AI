"""Best-effort extraction of financial-statement values from text-based PDFs.

How it works
* Only PDFs with a text layer are read. Scanned (image-only) PDFs are detected and
  rejected with a clear message: OCR is not supported.
* Each text line is matched against bilingual (Indonesian / English) line-item labels
  used in IDX financial statements, e.g. "Jumlah aset / Total assets". The template
  field keys (e.g. "revenue") are also recognised, so the StockWorth template saved as
  PDF works too.
* From a matched line, the first two grouped numbers are taken as current and previous
  period. Small note references ("5", "2f,7") are ignored.
* The reporting unit and currency are detected from phrases such as "dalam jutaan
  Rupiah" / "in millions of Rupiah", per page.
* Every value is returned as a warning that must be checked against the document; nothing
  is saved until the user confirms it in the preview.
"""

import io
import re
import time
from collections import Counter

import pdfplumber
from pdfminer.pdfdocument import PDFPasswordIncorrect, PDFEncryptionError

from app.core.errors import AppError
from app.schemas.financials import FIELD_LABELS, NON_NEGATIVE_FIELDS, UNIT_MULTIPLIER, VALUE_FIELDS, Unit
from app.services.importer import parse_number
from app.services.metadata_detect import detect_from_text, ticker_from_file_name

MAX_PAGES = 400
SCAN_PAGES = 150  # statements are near the front of annual/interim reports
TIME_BUDGET_SECONDS = 40
MIN_CHARS_PER_PAGE = 25
META_PAGES = 6  # cover + first statement pages carry company name and period

# (field, include pattern, exclude pattern). Order matters: specific labels first.
LINE_ITEMS: list[tuple[str, str, str | None]] = [
    ("current_assets", r"\b(jumlah|total) aset lancar\b|\btotal current assets\b", None),
    ("current_liabilities",
     r"\b(jumlah|total) liabilitas (jangka pendek|lancar)\b|\btotal current liabilities\b", None),
    ("total_assets", r"\b(jumlah|total) aset\b|\btotal assets\b", r"lancar|tidak lancar|current|non-current"),
    ("total_liabilities", r"\b(jumlah|total) liabilitas\b|\btotal liabilities\b",
     r"ekuitas|equity|jangka|lancar|current"),
    ("equity_attributable",
     r"ekuitas yang dapat diatribusikan kepada pemilik entitas induk|"
     r"equity attributable to (the )?(owners|equity holders) of the (parent|company)", None),
    ("total_equity", r"\b(jumlah|total) ekuitas\b|\btotal equity\b", r"liabilitas|liabilities|diatribusikan|attributable"),
    ("operating_cash_flow",
     r"arus kas bersih (yang )?(diperoleh dari|dari|digunakan untuk) aktivitas operasi|"
     r"kas bersih (yang )?(diperoleh dari|digunakan untuk) aktivitas operasi|"
     r"net cash (provided by|from|generated from|used in|flows? from) operating activities", None),
    ("capital_expenditure",
     r"(perolehan|pembelian|penambahan) aset tetap|"
     r"(acquisitions?|purchases?|additions?) of (fixed assets|property,? plant)", None),
    ("revenue",
     r"^(pendapatan usaha|pendapatan bersih|penjualan bersih|penjualan|jumlah pendapatan|pendapatan|"
     r"revenues?|net revenues?|net sales|total revenues?|sales)"
     r"(?=\s+(?:[\d(\-–—]|revenues?\b|net revenues?\b|net sales\b|sales\b)|$)",
     r"bunga|interest|lain|other|komprehensif|comprehensive|diterima|received|beban|expense"),
    # Banks report interest income instead of revenue; used as revenue only for bank statements.
    ("_interest_income", r"^(pendapatan bunga|interest income)\b", r"bersih|net|beban|expense|lain|other"),
    ("net_income",
     r"^(laba|rugi|laba \(rugi\)|laba/rugi) (bersih |neto )?(tahun|periode) berjalan\b|"
     r"^(profit|loss|profit \(loss\)|net income) for the (year|period)\b",
     r"diatribusikan|attributable|komprehensif|comprehensive|per saham|per share|sebelum|before"),
]
ATTRIBUTABLE_HEADER = re.compile(
    r"(laba|rugi|laba \(rugi\)).*(yang )?dapat diatribusikan kepada|"
    r"(profit|loss|income).*attributable to", re.I)
OWNERS_LINE = re.compile(r"^(pemilik entitas induk|owners of the (parent|company)|equity holders of the (parent|company))", re.I)

UNIT_PATTERNS = [
    (Unit.miliar, re.compile(r"(dalam|disajikan dalam) miliar(an)?|in billions", re.I)),
    (Unit.juta, re.compile(r"(dalam|disajikan dalam) juta(an)?|in millions", re.I)),
    (Unit.ribu, re.compile(r"(dalam|disajikan dalam) ribu(an)?|in thousands", re.I)),
]
USD_PATTERN = re.compile(r"dolar (as|amerika)|(united states|us|u\.s\.) dollars?", re.I)
IDR_PATTERN = re.compile(r"rupiah", re.I)

# A value token: grouped number, optional decimals, optional parentheses / minus.
NUM_TOKEN = re.compile(r"\(?-?\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?\)?|\(?-?\d{4,}(?:[.,]\d+)?\)?|(?<![\w.,])[-–—](?![\w.,])")


# Leading list markers such as "1.", "a.", "(b)", "iv." in OJK / IDX statement layouts.
ENUM_PREFIX = re.compile(r"^(?:\(?\d{1,2}[.)]|\(?[a-z][.)]|[ivx]{1,4}[.)])\s+")
# Stand-alone (non-consolidated) statements have no non-controlling interests.
INDIVIDUAL_HINT = re.compile(
    r"^individual$|laporan keuangan individual|\(individual\)|entitas induk saja|bank only|parent(?: entity)? only",
    re.I | re.M,
)
CASH_FLOW_HINT = re.compile(r"arus kas|cash flows?", re.I)
BANK_HINT = re.compile(r"\bpt\.?\s+bank\b|liabilitas kepada bank indonesia|penempatan pada bank indonesia", re.I)


def _norm(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def rebuild_line(chars: list[dict]) -> str:
    """Rebuild a text line from character positions.

    Some statements right-align numbers with padding space glyphs, and plain text extraction
    then splits a number such as 1.596.962.424 into "1 .596.962.424". Here space glyphs are
    ignored and a space is inserted only where there is a visible gap between characters.
    """
    glyphs = sorted((c for c in chars if c.get("text", "").strip()), key=lambda c: c["x0"])
    if not glyphs:
        return ""
    parts = [glyphs[0]["text"]]
    for prev, cur in zip(glyphs, glyphs[1:]):
        size = min(prev.get("size") or 8.0, cur.get("size") or 8.0)
        if cur["x0"] - prev["x1"] > max(0.8, 0.15 * size):
            parts.append(" ")
        parts.append(cur["text"])
    return "".join(parts)


def _page_lines(page) -> list[str]:
    try:
        lines = page.extract_text_lines(return_chars=True, strip=True)
        rebuilt = [_norm(rebuild_line(ln.get("chars", []))) for ln in lines]
        rebuilt = [ln for ln in rebuilt if ln]
        if rebuilt:
            return rebuilt
    except Exception:
        pass
    return [_norm(ln) for ln in (page.extract_text() or "").splitlines() if ln.strip()]


def _values_from_line(line: str) -> list[float | None]:
    vals: list[float | None] = []
    for tok in NUM_TOKEN.findall(line):
        if tok in ("-", "–", "—"):
            vals.append(None)  # a dash means nil / not presented
            continue
        try:
            v, _ = parse_number(tok)
        except ValueError:
            continue
        vals.append(v)
    return vals


def _page_unit(text: str) -> Unit | None:
    for unit, pat in UNIT_PATTERNS:
        if pat.search(text):
            return unit
    return None


def _page_currency(text: str) -> str | None:
    if USD_PATTERN.search(text):
        return "USD"
    if IDR_PATTERN.search(text):
        return "IDR"
    return None


def _template_key(line: str) -> str | None:
    first = line.split(" ", 1)[0].lower()
    return first if first in VALUE_FIELDS else None


def _is_encryption_error(exc: BaseException) -> bool:
    # pdfplumber wraps pdfminer errors: PdfminerException(PDFPasswordIncorrect()).
    candidates = [exc, *getattr(exc, "args", ())]
    return any(isinstance(c, (PDFPasswordIncorrect, PDFEncryptionError)) for c in candidates)


def _open_error(exc: BaseException) -> AppError:
    if _is_encryption_error(exc):
        return AppError(422, "pdf_encrypted", "PDF terkunci kata sandi. Buka kuncinya terlebih dahulu.")
    return AppError(422, "malformed_file", "PDF rusak atau tidak dapat dibaca.")


def _looks_scanned(text_chars: int, pages_read: int) -> bool:
    """Image-only pages yield (almost) no text; a real statement page has hundreds of characters."""
    return pages_read > 0 and text_chars / pages_read < MIN_CHARS_PER_PAGE


def _merge_detected(pages: list[tuple[int, str]], file_name: str) -> dict:
    """First page that yields a value wins for each field; the ticker falls back to the file name."""
    merged: dict = {"company_name": None, "ticker": None, "fiscal_year": None, "period": None, "basis": None,
                    "period_end": None, "sector": None, "period_note": None, "sources": {}}
    for page_no, text in pages:
        d = detect_from_text(text, "", f"PDF hal. {page_no}")
        for k in ("company_name", "ticker", "sector"):
            if merged[k] is None and d.get(k):
                merged[k], merged["sources"][k] = d[k], d["sources"][k]
        if merged["basis"] is None and d["basis"]:
            for k in ("fiscal_year", "period", "basis", "period_end"):
                merged[k], merged["sources"][k] = d[k], d["sources"][k]
            merged["period_note"] = None
        elif merged["basis"] is None and merged["fiscal_year"] is None and d["fiscal_year"]:
            # Period end found but its length isn't a supported annual/quarterly period.
            merged["fiscal_year"], merged["sources"]["fiscal_year"] = d["fiscal_year"], d["sources"]["fiscal_year"]
            merged["period_end"], merged["period_note"] = d["period_end"], d.get("period_note")
    if merged["ticker"] is None and (t := ticker_from_file_name(file_name)):
        merged["ticker"], merged["sources"]["ticker"] = t, "nama berkas"
    return merged


def parse_pdf(content: bytes, file_name: str) -> dict:
    if not content.startswith(b"%PDF"):
        raise AppError(415, "unsupported_file", "Berkas bukan PDF yang valid.")
    started = time.monotonic()
    try:
        pdf = pdfplumber.open(io.BytesIO(content))
    except Exception as exc:  # pdfminer raises many types for corrupt files
        raise _open_error(exc) from exc

    found: dict[str, dict] = {}
    meta_pages: list[tuple[int, str]] = []
    saw_cash_flow = False
    is_individual = False
    pending_attr = False
    text_chars = 0
    pages_read = 0
    with pdf:
        n_pages = len(pdf.pages)
        if n_pages > MAX_PAGES:
            raise AppError(413, "too_many_pages", f"PDF memiliki {n_pages} halaman; batas {MAX_PAGES} halaman.")
        for page_no, page in enumerate(pdf.pages[:SCAN_PAGES], start=1):
            if time.monotonic() - started > TIME_BUDGET_SECONDS:
                break
            try:
                lines = _page_lines(page)
                text = "\n".join(lines)
            except Exception as exc:
                if _is_encryption_error(exc):
                    raise _open_error(exc) from exc
                continue
            pages_read += 1
            text_chars += len(text.strip())
            if page_no == 5 and _looks_scanned(text_chars, pages_read):
                break  # almost certainly a scanned document
            if page_no <= META_PAGES:
                meta_pages.append((page_no, text))
            saw_cash_flow = saw_cash_flow or bool(CASH_FLOW_HINT.search(text))
            is_individual = is_individual or bool(INDIVIDUAL_HINT.search(text))
            unit, currency = _page_unit(text), _page_currency(text)
            for line in lines:
                low = ENUM_PREFIX.sub("", line.lower())
                field = _template_key(line)
                label_used = field
                if field is None:
                    if ATTRIBUTABLE_HEADER.search(low):
                        pending_attr = True
                    if pending_attr and OWNERS_LINE.search(low) and "net_income_attributable" not in found:
                        field, label_used = "net_income_attributable", line
                    else:
                        for f, inc, exc in LINE_ITEMS:
                            if re.search(inc, low) and not (exc and re.search(exc, low)):
                                field, label_used = f, line
                                break
                if field is None or field in found:
                    continue
                vals = _values_from_line(line)
                if not vals or all(v is None for v in vals):
                    continue
                if field == "net_income_attributable":
                    pending_attr = False
                found[field] = {
                    "page": page_no,
                    "label": label_used[:90],
                    "current": vals[0],
                    "previous": vals[1] if len(vals) > 1 else None,
                    "unit": unit,
                    "currency": currency,
                    "extra_numbers": len(vals) > 2,
                }
            if all(f in found for f in ("total_assets", "total_equity", "revenue", "operating_cash_flow")):
                # keep reading a little: attributable lines and capex usually follow
                if all(f in found for f in ("net_income_attributable", "capital_expenditure", "current_assets")):
                    break

    is_bank = any(BANK_HINT.search(t) for _, t in meta_pages)
    interest = found.pop("_interest_income", None)
    bank_revenue_note = None
    if is_bank and "revenue" not in found and interest:
        found["revenue"] = interest
        bank_revenue_note = (
            "Untuk bank, pendapatan diisi dengan pendapatan bunga (bruto); pendapatan non-bunga seperti komisi "
            "tidak termasuk. Sesuaikan jika Anda memakai definisi lain."
        )

    # Stand-alone statements: everything belongs to the entity's own shareholders, so the
    # "attributable to owners of the parent" figures equal the totals. Recorded on the row.
    individual_note = (
        "Laporan individual (tanpa entitas anak): tidak ada kepentingan non-pengendali, sehingga "
        "nilainya sama dengan total."
    )
    derived_attr: set[str] = set()
    if is_individual:
        for attr_field, total_field in (("net_income_attributable", "net_income"),
                                        ("equity_attributable", "total_equity")):
            if attr_field not in found and total_field in found:
                found[attr_field] = dict(found[total_field])
                derived_attr.add(attr_field)

    if pages_read == 0 or _looks_scanned(text_chars, pages_read):
        raise AppError(
            422,
            "pdf_scanned",
            "PDF ini tampaknya hasil pindaian (gambar) tanpa lapisan teks. Pembacaan OCR belum didukung; "
            "gunakan PDF asli dari situs BEI/emiten atau isi data secara manual.",
        )

    detected = _merge_detected(meta_pages, file_name)
    if detected["sector"] is None and is_bank:
        detected["sector"], detected["sources"]["sector"] = "financials_bank", "isi laporan (format bank)"

    # Normalise everything to the most common detected unit.
    units = [v["unit"] for v in found.values() if v["unit"]]
    target_unit = Counter(units).most_common(1)[0][0] if units else None
    currencies = [v["currency"] for v in found.values() if v["currency"]]
    currency = Counter(currencies).most_common(1)[0][0] if currencies else None

    current: dict[str, float] = {}
    previous: dict[str, float] = {}
    cell_refs: dict[str, str] = {}
    rows = []
    warnings = [
        "Nilai dibaca otomatis dari PDF. Cocokkan setiap angka dengan laporan sebelum menyimpan: "
        "urutan kolom, tanda negatif, dan baris yang terpilih bisa keliru.",
    ]
    if target_unit is None:
        warnings.append("Satuan laporan tidak terdeteksi di PDF. Pastikan satuan di langkah 1 sudah benar.")
    for field in VALUE_FIELDS:
        item = found.get(field)
        if not item:
            continue
        msgs = [f"Dari hal. {item['page']}: \"{item['label']}\"."]
        if field == "revenue" and bank_revenue_note:
            msgs.append(bank_revenue_note)
        if field in derived_attr:
            msgs.append(individual_note)
        scale = 1.0
        if target_unit and item["unit"] and item["unit"] != target_unit:
            scale = UNIT_MULTIPLIER[item["unit"]] / UNIT_MULTIPLIER[target_unit]
            msgs.append(f"Dikonversi dari {item['unit'].value} ke {target_unit.value}.")
        cur = item["current"] * scale if item["current"] is not None else None
        prev = item["previous"] * scale if item["previous"] is not None else None
        if field == "capital_expenditure":
            if cur is not None and cur < 0:
                cur = abs(cur)
            if prev is not None and prev < 0:
                prev = abs(prev)
            msgs.append("Belanja modal disimpan sebagai angka positif.")
        if item["extra_numbers"]:
            msgs.append("Baris berisi lebih dari dua angka; dipakai dua angka pertama.")
        status = "warning"
        if field in NON_NEGATIVE_FIELDS and ((cur is not None and cur < 0) or (prev is not None and prev < 0)):
            status = "error"
            msgs.append(f"{FIELD_LABELS[field]} tidak boleh negatif; baris ini tidak digunakan.")
            cur = prev = None
        if cur is not None:
            current[field] = cur
            cell_refs[f"current.{field}"] = f"PDF hal. {item['page']}"
        if prev is not None:
            previous[field] = prev
            cell_refs[f"previous.{field}"] = f"PDF hal. {item['page']}"
        rows.append({
            "row": item["page"], "code": item["label"][:60], "field": field, "label": FIELD_LABELS[field],
            "current": cur, "previous": prev, "status": status, "messages": msgs,
        })

    # Opening balances are rarely printed as separate lines: for annual statements they equal the
    # comparative column's closing balance, which the calculator already uses. Don't list them as missing.
    derived_begin = {"total_assets_begin": "total_assets", "total_equity_begin": "total_equity",
                     "equity_attributable_begin": "equity_attributable"}
    # Explain absent items by why they are absent, instead of one undifferentiated list.
    not_applicable = {"current_assets", "current_liabilities"} if is_bank else set()
    not_in_report: dict[str, str] = {}
    if not saw_cash_flow:
        for f in ("operating_cash_flow", "capital_expenditure"):
            not_in_report[f] = "PDF ini tidak memuat laporan arus kas"
    if not previous:
        for f in ("total_assets_begin", "total_equity_begin", "equity_attributable_begin"):
            not_in_report[f] = "PDF ini hanya memuat satu periode (tanpa kolom pembanding/saldo awal)"
    for f in ("weighted_average_shares", "shares_outstanding"):
        not_in_report.setdefault(f, "jumlah saham biasanya ada di catatan laporan atau situs BEI")
    missing = [
        FIELD_LABELS[f] for f in VALUE_FIELDS
        if f not in found and f not in not_applicable and f not in not_in_report
        and not (f in derived_begin and derived_begin[f] in previous)
    ]
    absent_groups: dict[str, list[str]] = {}
    for f, reason in not_in_report.items():
        if f not in found:
            absent_groups.setdefault(reason, []).append(FIELD_LABELS[f])
    for reason, labels in absent_groups.items():
        warnings.append(f"Isi manual jika diperlukan — {reason}: {', '.join(labels)}.")
    if not_applicable:
        warnings.append("Aset lancar dan liabilitas jangka pendek tidak diterapkan untuk bank, jadi tidak perlu diisi.")
    if any(f in derived_begin and derived_begin[f] in previous for f in VALUE_FIELDS):
        warnings.append(
            "Saldo awal periode tidak dibaca terpisah: untuk laporan tahunan diambil dari kolom pembanding. "
            "Untuk laporan kuartalan, isi saldo awal (31 Desember tahun lalu) secara manual."
        )
    if not current and not previous:
        warnings.append("Tidak ada akun laporan keuangan yang dikenali di PDF ini.")
    elif missing:
        warnings.append("Tidak ditemukan di PDF (periksa apakah ada dengan nama lain): " + ", ".join(missing) + ".")
    if pages_read < min(n_pages, SCAN_PAGES):
        warnings.append(f"Hanya {pages_read} halaman pertama yang dibaca.")

    errors = [f"Hal. {r['row']}: {m}" for r in rows if r["status"] == "error" for m in r["messages"][-1:]]
    return {
        "detected": detected,
        "file_name": file_name,
        "file_type": "pdf",
        "sheet": None,
        "unit": target_unit.value if target_unit else None,
        "currency": currency,
        "current": current,
        "previous": previous,
        "cell_refs": cell_refs,
        "rows": rows,
        "errors": errors,
        "warnings": warnings,
    }
