"""CSV / XLSX import of financial statement values.

Safety rules
* Files are processed entirely in memory; nothing is written to disk and the uploaded
  file name is never used as a path.
* Size, extension and file signature are checked. Macro-enabled or legacy Excel formats
  are rejected, and archives are checked against decompression bombs.
* Spreadsheet formulas are never evaluated. For XLSX, a formula cell's *cached* value
  (computed by Excel when the file was saved) is used and flagged for review; if no
  cached value exists the cell is rejected.
* Every imported value keeps a reference to its source cell/row.

Template layout (one row per account):
    kode | keterangan | periode_berjalan | periode_sebelumnya
Optional metadata rows: `satuan` (unit|ribu|juta|miliar) and `mata_uang` (IDR|USD) with the
value in the `periode_berjalan` column.
"""

import csv
import io
import math
import re
import zipfile
from dataclasses import dataclass, field

import pandas as pd
import xlrd
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from app.core.errors import AppError
from app.schemas.financials import FIELD_LABELS, NON_NEGATIVE_FIELDS, POSITIVE_FIELDS, VALUE_FIELDS, Currency, Unit

MAX_ROWS = 200
MAX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024

HEADER_ALIASES = {
    "code": {"kode", "kode_akun", "field", "key", "akun"},
    "label": {"keterangan", "nama_akun", "label", "deskripsi", "description"},
    "current": {"periode_berjalan", "current", "nilai", "tahun_berjalan", "berjalan"},
    "previous": {"periode_sebelumnya", "previous", "pembanding", "tahun_sebelumnya", "sebelumnya"},
}
META_KEYS = {"satuan": "unit", "unit": "unit", "mata_uang": "currency", "currency": "currency"}
_LABEL_TO_FIELD = {v.lower(): k for k, v in FIELD_LABELS.items()}


@dataclass
class RowResult:
    row: int
    code: str
    field: str | None
    label: str | None
    current: float | None = None
    previous: float | None = None
    status: str = "ok"  # ok | warning | error | ignored
    messages: list[str] = field(default_factory=list)


def safe_file_name(name: str | None) -> str:
    base = re.split(r"[\\/]", name or "")[-1]
    base = re.sub(r"[^\w.\- ()]", "_", base).strip()[:120]
    return base or "berkas"


def parse_number(raw) -> tuple[float | None, str | None]:
    """Parse a cell into a float. Returns (value, warning). Raises ValueError if invalid."""
    if raw is None:
        return None, None
    if isinstance(raw, bool):
        raise ValueError("Nilai boolean bukan angka.")
    if isinstance(raw, (int, float)):
        if isinstance(raw, float) and math.isnan(raw):
            return None, None
        if not math.isfinite(raw):
            raise ValueError("Angka tidak valid.")
        return float(raw), None
    s = str(raw).strip().replace(" ", "").replace(" ", "")
    if s in ("", "-", "–", "—", "n/a", "N/A", "na", "NA"):
        return None, None
    if s.startswith(("=", "+", "@")) and not re.fullmatch(r"\+?[\d.,]+", s):
        raise ValueError("Formula tidak didukung; masukkan angka hasilnya.")
    s = re.sub(r"^(Rp\.?|IDR|USD|\$)", "", s, flags=re.IGNORECASE)
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1]
    if s.startswith("-"):
        negative, s = not negative, s[1:]
    elif s.startswith("+"):
        s = s[1:]
    if not re.fullmatch(r"[\d.,]+", s) or not re.search(r"\d", s):
        raise ValueError(f"'{str(raw)[:40]}' bukan angka yang valid.")
    warning = None
    if "." in s and "," in s:
        dec = "." if s.rfind(".") > s.rfind(",") else ","
        thou = "," if dec == "." else "."
        s = s.replace(thou, "").replace(dec, ".")
    elif "," in s or "." in s:
        sep = "," if "," in s else "."
        if re.fullmatch(r"\d{1,3}(" + re.escape(sep) + r"\d{3})+", s):
            if s.count(sep) == 1:
                warning = (f"'{raw}' ambigu; dibaca sebagai {s.replace(sep, '')} "
                           f"('{sep}' sebagai pemisah ribuan). Periksa kembali.")
            s = s.replace(sep, "")
        elif s.count(sep) == 1:
            s = s.replace(sep, ".")
        else:
            raise ValueError(f"'{str(raw)[:40]}' bukan angka yang valid.")
    value = float(s)
    return (-value if negative else value), warning


def _norm_header(h) -> str:
    return re.sub(r"\s+", "_", str(h or "").strip().lower())


def _resolve_field(code: str, label: str | None) -> str | None:
    c = code.strip().lower()
    if c in VALUE_FIELDS:
        return c
    if c in _LABEL_TO_FIELD:
        return _LABEL_TO_FIELD[c]
    if label and label.strip().lower() in _LABEL_TO_FIELD:
        return _LABEL_TO_FIELD[label.strip().lower()]
    return None


def _find_columns(header: list) -> dict[str, int] | None:
    normed = [_norm_header(h) for h in header]
    cols: dict[str, int] = {}
    for role, aliases in HEADER_ALIASES.items():
        for idx, h in enumerate(normed):
            if h in aliases:
                cols[role] = idx
                break
    if "code" in cols and "current" in cols:
        return cols
    return None


@dataclass
class _Cell:
    value: object
    ref: str
    is_formula: bool = False


def _process_rows(rows: list[tuple[int, list[_Cell]]], file_name: str, file_type: str, sheet: str | None) -> dict:
    header_idx = None
    cols = None
    for i, (_, cells) in enumerate(rows[:15]):
        cols = _find_columns([c.value for c in cells])
        if cols:
            header_idx = i
            break
    if cols is None:
        raise AppError(422, "invalid_template",
                       "Kolom wajib tidak ditemukan. Berkas harus memiliki kolom 'kode' dan 'periode_berjalan'. "
                       "Unduh templat untuk format yang benar.")

    data_rows = rows[header_idx + 1:]
    if len(data_rows) > MAX_ROWS:
        raise AppError(422, "too_many_rows", f"Berkas memiliki lebih dari {MAX_ROWS} baris data.")

    results: list[RowResult] = []
    current: dict[str, float] = {}
    previous: dict[str, float] = {}
    cell_refs: dict[str, str] = {}
    meta: dict[str, str] = {}
    seen: dict[str, int] = {}
    file_warnings: list[str] = []
    ambiguous: list[str] = []

    def get(cells: list[_Cell], role: str) -> _Cell | None:
        idx = cols.get(role)
        return cells[idx] if idx is not None and idx < len(cells) else None

    for row_no, cells in data_rows:
        code_cell = get(cells, "code")
        code = str(code_cell.value).strip() if code_cell and code_cell.value is not None else ""
        label_cell = get(cells, "label")
        label = str(label_cell.value).strip() if label_cell and label_cell.value is not None else None
        cur_cell, prev_cell = get(cells, "current"), get(cells, "previous")
        if not code and (cur_cell is None or cur_cell.value in (None, "")) and (prev_cell is None or prev_cell.value in (None, "")):
            continue  # blank row
        if not code:
            results.append(RowResult(row=row_no, code="", field=None, label=label, status="error",
                                     messages=["Kolom kode kosong."]))
            continue

        meta_key = META_KEYS.get(code.lower())
        if meta_key:
            raw = str(cur_cell.value).strip().lower() if cur_cell and cur_cell.value is not None else ""
            r = RowResult(row=row_no, code=code, field=None, label="Metadata")
            if meta_key == "unit":
                if raw in {u.value for u in Unit}:
                    meta["unit"] = raw
                    r.messages.append(f"Satuan berkas: {raw}.")
                else:
                    r.status, r.messages = "error", [f"Satuan '{raw}' tidak dikenal. Gunakan unit, ribu, juta, atau miliar."]
            else:
                if raw.upper() in {c.value for c in Currency}:
                    meta["currency"] = raw.upper()
                    r.messages.append(f"Mata uang berkas: {raw.upper()}.")
                else:
                    r.status, r.messages = "error", [f"Mata uang '{raw}' tidak didukung. Gunakan IDR atau USD."]
            results.append(r)
            continue

        fld = _resolve_field(code, label)
        if fld is None:
            results.append(RowResult(row=row_no, code=code[:60], field=None, label=label, status="ignored",
                                     messages=["Kode akun tidak dikenal; baris diabaikan."]))
            continue
        r = RowResult(row=row_no, code=code[:60], field=fld, label=FIELD_LABELS[fld])
        if fld in seen:
            r.status = "error"
            r.messages.append(f"Kode duplikat (sudah ada di baris {seen[fld]}). Baris ini tidak digunakan.")
            results.append(r)
            continue
        seen[fld] = row_no

        for role, cell, target in (("current", cur_cell, current), ("previous", prev_cell, previous)):
            if cell is None:
                continue
            try:
                value, warn = parse_number(cell.value)
            except ValueError as exc:
                r.status = "error"
                r.messages.append(f"{'Periode berjalan' if role == 'current' else 'Periode sebelumnya'}: {exc}")
                continue
            if cell.is_formula:
                if value is None:
                    r.status = "error"
                    r.messages.append(f"Sel {cell.ref} berisi formula tanpa nilai tersimpan. Simpan ulang di Excel "
                                      "atau ketik angkanya langsung.")
                    continue
                r.messages.append(f"Sel {cell.ref} berisi formula; digunakan nilai tersimpan (formula tidak dijalankan).")
                if r.status == "ok":
                    r.status = "warning"
            if value is None:
                continue
            if warn:
                # Reported once per file below; per-row repetition would bury real problems.
                ambiguous.append(cell.ref)
            if fld == "capital_expenditure" and value < 0:
                value = abs(value)
                r.messages.append("Belanja modal negatif diubah menjadi angka positif (arus kas keluar).")
                if r.status == "ok":
                    r.status = "warning"
            if fld in NON_NEGATIVE_FIELDS and value < 0:
                r.status = "error"
                r.messages.append(f"{FIELD_LABELS[fld]} tidak boleh negatif.")
                continue
            if fld in POSITIVE_FIELDS and value <= 0:
                r.status = "error"
                r.messages.append(f"{FIELD_LABELS[fld]} harus lebih besar dari nol.")
                continue
            if abs(value) > 1e18:
                r.status = "error"
                r.messages.append("Nilai di luar rentang yang wajar.")
                continue
            target[fld] = value
            if role == "current":
                r.current = value
            else:
                r.previous = value
            cell_refs[f"{role}.{fld}"] = cell.ref
        results.append(r)

    if ambiguous:
        file_warnings.append(
            f"{len(ambiguous)} nilai (mis. {ambiguous[0]}) memakai format seperti '1.234' dan dibaca dengan titik "
            "sebagai pemisah ribuan (format Indonesia). Periksa jika berkas memakai titik sebagai desimal."
        )
    if not current and not previous:
        file_warnings.append("Tidak ada nilai keuangan yang berhasil dibaca dari berkas.")

    errors = [m for r in results if r.status == "error" for m in (f"Baris {r.row}: {x}" for x in r.messages)]
    warnings = file_warnings + [
        f"Baris {r.row}: {x}" for r in results if r.status == "warning" for x in r.messages
    ]
    return {
        "file_name": file_name,
        "file_type": file_type,
        "sheet": sheet,
        "unit": meta.get("unit"),
        "currency": meta.get("currency"),
        "current": current,
        "previous": previous,
        "cell_refs": cell_refs,
        "rows": [r.__dict__ for r in results],
        "errors": errors,
        "warnings": warnings,
    }


def _decode_text(content: bytes) -> str:
    if b"\x00" in content[:4096]:
        raise AppError(415, "unsupported_file", "Berkas CSV tampaknya bukan teks.")
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    raise AppError(422, "invalid_encoding", "Encoding berkas tidak dikenali. Simpan sebagai CSV UTF-8.")


def parse_csv(content: bytes, file_name: str) -> dict:
    text = _decode_text(content)
    try:
        delimiter = csv.Sniffer().sniff(text[:4096], delimiters=",;\t").delimiter
    except csv.Error:
        delimiter = ","
    try:
        df = pd.read_csv(io.StringIO(text), sep=delimiter, header=None, dtype=str, keep_default_na=False,
                         engine="python", skip_blank_lines=False, nrows=MAX_ROWS + 20)
    except (pd.errors.ParserError, pd.errors.EmptyDataError, ValueError) as exc:
        raise AppError(422, "malformed_file", "Berkas CSV tidak dapat dibaca. Periksa format dan pemisah kolom.") from exc
    rows = []
    for i, values in enumerate(df.itertuples(index=False), start=1):
        cells = [_Cell(value=(v if v != "" else None), ref=f"baris {i}, kolom {get_column_letter(j + 1)}")
                 for j, v in enumerate(values)]
        rows.append((i, cells))
    return _process_rows(rows, file_name, "csv", None)


def _check_xlsx_archive(content: bytes) -> None:
    if not content.startswith(b"PK\x03\x04"):
        raise AppError(415, "unsupported_file", "Berkas bukan XLSX yang valid.")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            infos = zf.infolist()
            total = sum(i.file_size for i in infos)
            names = {i.filename.lower() for i in infos}
    except zipfile.BadZipFile as exc:
        raise AppError(422, "malformed_file", "Berkas XLSX rusak atau tidak dapat dibuka.") from exc
    if total > MAX_UNCOMPRESSED_BYTES:
        raise AppError(413, "file_too_large", "Isi berkas XLSX terlalu besar setelah diekstrak.")
    if any(n.endswith("vbaproject.bin") for n in names):
        raise AppError(415, "macro_not_allowed", "Berkas mengandung makro. Simpan ulang sebagai .xlsx tanpa makro.")
    if "xl/workbook.xml" not in names:
        raise AppError(422, "malformed_file", "Struktur berkas XLSX tidak valid.")


def parse_xlsx(content: bytes, file_name: str) -> dict:
    _check_xlsx_archive(content)
    try:
        wb_values = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        wb_formulas = load_workbook(io.BytesIO(content), read_only=True, data_only=False)
    except Exception as exc:  # openpyxl raises many types for corrupt files
        raise AppError(422, "malformed_file", "Berkas XLSX tidak dapat dibaca.") from exc
    try:
        names = wb_values.sheetnames
        sheet = next((n for n in names if n.strip().lower() in ("data", "template", "templat")), names[0])
        ws_v, ws_f = wb_values[sheet], wb_formulas[sheet]
        rows = []
        for i, (rv, rf) in enumerate(zip(ws_v.iter_rows(max_row=MAX_ROWS + 20, max_col=10),
                                         ws_f.iter_rows(max_row=MAX_ROWS + 20, max_col=10)), start=1):
            cells = []
            for j, (cv, cf) in enumerate(zip(rv, rf)):
                is_formula = isinstance(cf.value, str) and cf.value.startswith("=")
                cells.append(_Cell(value=cv.value, ref=f"{sheet}!{get_column_letter(j + 1)}{i}", is_formula=is_formula))
            rows.append((i, cells))
    finally:
        wb_values.close()
        wb_formulas.close()
    return _process_rows(rows, file_name, "xlsx", sheet)


OLE2_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def parse_xls(content: bytes, file_name: str) -> dict:
    """Legacy Excel 97-2003 (.xls). xlrd only reads stored values; it never runs formulas or macros."""
    if not content.startswith(OLE2_SIGNATURE):
        raise AppError(415, "unsupported_file", "Berkas bukan XLS (Excel 97-2003) yang valid.")
    if "_VBA_PROJECT".encode("utf-16-le") in content:
        raise AppError(415, "macro_not_allowed", "Berkas mengandung makro. Simpan ulang tanpa makro.")
    try:
        book = xlrd.open_workbook(file_contents=content, on_demand=True)
    except Exception as exc:  # xlrd raises XLRDError and others for corrupt files
        raise AppError(422, "malformed_file", "Berkas XLS rusak atau tidak dapat dibaca.") from exc
    try:
        names = book.sheet_names()
        sheet = next((n for n in names if n.strip().lower() in ("data", "template", "templat")), names[0])
        ws = book.sheet_by_name(sheet)
        rows = []
        for i in range(min(ws.nrows, MAX_ROWS + 20)):
            cells = []
            for j in range(min(ws.ncols, 10)):
                c = ws.cell(i, j)
                if c.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                    value = None
                elif c.ctype == xlrd.XL_CELL_ERROR:
                    value = "#ERROR"
                elif c.ctype == xlrd.XL_CELL_BOOLEAN:
                    value = bool(c.value)
                else:
                    value = c.value
                cells.append(_Cell(value=value, ref=f"{sheet}!{get_column_letter(j + 1)}{i + 1}"))
            rows.append((i + 1, cells))
    finally:
        book.release_resources()
    result = _process_rows(rows, file_name, "xls", sheet)
    result["warnings"].insert(0, "Format XLS: nilai dibaca dari hasil yang tersimpan di berkas; formula tidak dijalankan.")
    return result


# Per-type size limits: annual-report PDFs are much larger than spreadsheets.
SPREADSHEET_EXTS = ("csv", "xlsx", "xls")
SUPPORTED_TEXT = "Gunakan .pdf, .csv, .xlsx, atau .xls."


def parse_upload(content: bytes, file_name: str | None, max_bytes: int, max_pdf_bytes: int | None = None) -> dict:
    name = safe_file_name(file_name)
    if not content:
        raise AppError(422, "empty_file", "Berkas kosong.")
    ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""
    limit = (max_pdf_bytes or max_bytes) if ext == "pdf" else max_bytes
    if len(content) > limit:
        raise AppError(413, "file_too_large", f"Ukuran berkas melebihi batas {limit // (1024 * 1024)} MB untuk .{ext or 'berkas'}.")
    if ext == "csv":
        return parse_csv(content, name)
    if ext == "xlsx":
        return parse_xlsx(content, name)
    if ext == "xls":
        return parse_xls(content, name)
    if ext == "pdf":
        from app.services.pdf_import import parse_pdf  # local import avoids a circular import

        return parse_pdf(content, name)
    if ext in ("xlsm", "xlsb"):
        raise AppError(415, "unsupported_file", "Excel dengan makro tidak didukung. Simpan sebagai .xlsx atau .xls tanpa makro.")
    raise AppError(415, "unsupported_file", f"Format berkas tidak didukung. {SUPPORTED_TEXT}")


# --- Templates ----------------------------------------------------------------------

TEMPLATE_HEADER = ["kode", "keterangan", "periode_berjalan", "periode_sebelumnya"]


def template_rows() -> list[list[str]]:
    rows = [["satuan", "Satuan nilai: unit / ribu / juta / miliar", "juta", ""],
            ["mata_uang", "Mata uang laporan: IDR / USD", "IDR", ""]]
    rows += [[f, FIELD_LABELS[f], "", ""] for f in VALUE_FIELDS]
    return rows


def template_csv() -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(TEMPLATE_HEADER)
    w.writerows(template_rows())
    return buf.getvalue().encode("utf-8-sig")


def template_xlsx() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Data"
    ws.append(TEMPLATE_HEADER)
    for r in template_rows():
        ws.append(r)
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="E7EAF0")
    for col, width in zip("ABCD", (30, 62, 20, 20)):
        ws.column_dimensions[col].width = width
    info = wb.create_sheet("Petunjuk")
    for line in [
        "Petunjuk pengisian templat StockWorth AI",
        "",
        "1. Isi kolom 'periode_berjalan' dan, jika ada, 'periode_sebelumnya' (periode yang sama tahun lalu).",
        "2. Semua nilai uang mengikuti 'satuan' dan 'mata_uang' di baris atas. Jumlah saham diisi dalam lembar.",
        "3. Belanja modal diisi sebagai angka positif.",
        "4. Biarkan kosong jika data tidak tersedia. Jangan isi 0 untuk data yang tidak diketahui.",
        "5. Ketik angka langsung. Formula tidak dijalankan; hanya nilai tersimpan yang dibaca.",
        "6. Harga saham, tanggal harga, kode saham, dan periode diisi di aplikasi.",
    ]:
        info.append([line])
    info.column_dimensions["A"].width = 110
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
