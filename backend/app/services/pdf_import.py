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

MAX_PAGES = 400
SCAN_PAGES = 150  # statements are near the front of annual/interim reports
TIME_BUDGET_SECONDS = 40
MIN_CHARS_PER_PAGE = 25

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
     r"^(pendapatan usaha|pendapatan bersih|penjualan bersih|pendapatan|jumlah pendapatan|"
     r"revenues?|net revenues?|net sales|total revenues?)\b",
     r"bunga|interest|lain|other|komprehensif|comprehensive|diterima|received|beban|expense"),
    ("net_income",
     r"^(laba|rugi|laba \(rugi\)) (bersih )?(tahun|periode) berjalan\b|"
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


def _norm(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


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


def parse_pdf(content: bytes, file_name: str) -> dict:
    if not content.startswith(b"%PDF"):
        raise AppError(415, "unsupported_file", "Berkas bukan PDF yang valid.")
    started = time.monotonic()
    try:
        pdf = pdfplumber.open(io.BytesIO(content))
    except Exception as exc:  # pdfminer raises many types for corrupt files
        raise _open_error(exc) from exc

    found: dict[str, dict] = {}
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
                text = page.extract_text() or ""
            except Exception as exc:
                if _is_encryption_error(exc):
                    raise _open_error(exc) from exc
                continue
            pages_read += 1
            text_chars += len(text.strip())
            if page_no == 5 and _looks_scanned(text_chars, pages_read):
                break  # almost certainly a scanned document
            unit, currency = _page_unit(text), _page_currency(text)
            for raw in text.splitlines():
                line = _norm(raw)
                if not line:
                    continue
                low = line.lower()
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

    if pages_read == 0 or _looks_scanned(text_chars, pages_read):
        raise AppError(
            422,
            "pdf_scanned",
            "PDF ini tampaknya hasil pindaian (gambar) tanpa lapisan teks. Pembacaan OCR belum didukung; "
            "gunakan PDF asli dari situs BEI/emiten atau isi data secara manual.",
        )

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
    missing = [
        FIELD_LABELS[f] for f in VALUE_FIELDS
        if f not in found and not (f in derived_begin and derived_begin[f] in previous)
    ]
    if any(f in derived_begin and derived_begin[f] in previous for f in VALUE_FIELDS):
        warnings.append(
            "Saldo awal periode tidak dibaca terpisah: untuk laporan tahunan diambil dari kolom pembanding. "
            "Untuk laporan kuartalan, isi saldo awal (31 Desember tahun lalu) secara manual."
        )
    if not current and not previous:
        warnings.append("Tidak ada akun laporan keuangan yang dikenali di PDF ini.")
    elif missing:
        warnings.append("Tidak ditemukan di PDF (isi manual jika ada): " + ", ".join(missing) + ".")
    if pages_read < min(n_pages, SCAN_PAGES):
        warnings.append(f"Hanya {pages_read} halaman pertama yang dibaca.")

    errors = [f"Hal. {r['row']}: {m}" for r in rows if r["status"] == "error" for m in r["messages"][-1:]]
    return {
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
