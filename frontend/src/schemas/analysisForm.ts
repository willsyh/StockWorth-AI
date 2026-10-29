import { z } from "zod";
import { ALL_FIELDS, FIELD_META, PREVIOUS_FIELDS } from "@/lib/fields";
import { parseIdNumber } from "@/lib/format";
import type { AnalysisInput, Basis, Currency, FinancialValues, Period, Sector, SourceInfo, Unit, ValueField } from "@/types/api";

const NON_NEGATIVE = new Set<ValueField>([
  "revenue",
  "total_assets",
  "total_assets_begin",
  "total_liabilities",
  "current_assets",
  "current_liabilities",
  "capital_expenditure",
]);
const POSITIVE = new Set<ValueField>(["weighted_average_shares", "shares_outstanding"]);

const valuesShape = (fields: ValueField[]) =>
  z.object(Object.fromEntries(fields.map((f) => [f, z.string()])) as Record<ValueField, z.ZodString>);

export const analysisFormSchema = z
  .object({
    ticker: z
      .string()
      .trim()
      .regex(/^[A-Za-z]{4}$/, "Kode saham harus 4 huruf, contoh: BBCA."),
    name: z.string().trim().min(2, "Nama perusahaan minimal 2 karakter.").max(160, "Nama terlalu panjang."),
    sector: z.string(),
    fiscal_year: z.string().regex(/^\d{4}$/, "Isi tahun fiskal 4 digit."),
    basis: z.enum(["annual", "quarterly", "ytd"]),
    period: z.enum(["FY", "Q1", "Q2", "Q3", "Q4"]),
    currency: z.enum(["IDR", "USD"]),
    unit: z.enum(["unit", "ribu", "juta", "miliar"]),
    fx_rate: z.string(),
    current: valuesShape(ALL_FIELDS),
    include_previous: z.boolean(),
    prev_fiscal_year: z.string(),
    prev_period: z.enum(["FY", "Q1", "Q2", "Q3", "Q4"]),
    previous: valuesShape(PREVIOUS_FIELDS),
    share_price: z.string(),
    share_price_date: z.string(),
    price_source: z.string().max(200, "Maksimal 200 karakter."),
  })
  .superRefine((v, ctx) => {
    const year = Number(v.fiscal_year);
    if (v.fiscal_year && (year < 1990 || year > new Date().getFullYear() + 1)) {
      ctx.addIssue({ code: "custom", path: ["fiscal_year"], message: "Tahun fiskal di luar rentang yang wajar." });
    }
    if (v.basis === "annual" && v.period !== "FY") {
      ctx.addIssue({ code: "custom", path: ["period"], message: "Laporan tahunan menggunakan periode FY." });
    }
    if (v.basis !== "annual" && v.period === "FY") {
      ctx.addIssue({ code: "custom", path: ["period"], message: "Pilih kuartal Q1–Q4." });
    }

    const checkNum = (path: (string | number)[], raw: string, field?: ValueField) => {
      const n = parseIdNumber(raw);
      if (n === undefined) return;
      if (Number.isNaN(n)) {
        ctx.addIssue({ code: "custom", path, message: "Format angka tidak valid. Gunakan titik untuk ribuan dan koma untuk desimal." });
      } else if (Math.abs(n) > 1e18) {
        ctx.addIssue({ code: "custom", path, message: "Nilai di luar rentang yang wajar." });
      } else if (field && NON_NEGATIVE.has(field) && n < 0) {
        ctx.addIssue({
          code: "custom",
          path,
          message: field === "capital_expenditure" ? "Isi belanja modal sebagai angka positif." : "Nilai tidak boleh negatif.",
        });
      } else if (field && POSITIVE.has(field) && n <= 0) {
        ctx.addIssue({ code: "custom", path, message: "Harus lebih besar dari nol." });
      }
    };
    for (const f of ALL_FIELDS) checkNum(["current", f], v.current[f], f);
    if (v.include_previous) {
      for (const f of PREVIOUS_FIELDS) checkNum(["previous", f], v.previous[f], f);
      if (!/^\d{4}$/.test(v.prev_fiscal_year)) {
        ctx.addIssue({ code: "custom", path: ["prev_fiscal_year"], message: "Isi tahun fiskal pembanding." });
      }
    }

    if (v.currency !== "IDR") {
      checkNum(["fx_rate"], v.fx_rate);
      const fx = parseIdNumber(v.fx_rate);
      if (fx !== undefined && !Number.isNaN(fx) && fx <= 0) {
        ctx.addIssue({ code: "custom", path: ["fx_rate"], message: "Kurs harus lebih besar dari nol." });
      }
    }

    checkNum(["share_price"], v.share_price);
    const price = parseIdNumber(v.share_price);
    if (price !== undefined && !Number.isNaN(price)) {
      if (price <= 0) ctx.addIssue({ code: "custom", path: ["share_price"], message: "Harga saham harus lebih besar dari nol." });
      if (!v.share_price_date) {
        ctx.addIssue({ code: "custom", path: ["share_price_date"], message: "Tanggal harga wajib diisi jika harga diisi." });
      }
    }
    if (v.share_price_date) {
      const today = new Date().toISOString().slice(0, 10);
      if (v.share_price_date > today) {
        ctx.addIssue({ code: "custom", path: ["share_price_date"], message: "Tanggal harga tidak boleh di masa depan." });
      }
    }

    const hasIncome = ["revenue", "net_income", "net_income_attributable"].some(
      (f) => parseIdNumber(v.current[f as ValueField]) !== undefined,
    );
    if (!hasIncome) {
      ctx.addIssue({ code: "custom", path: ["current", "revenue"], message: "Isi minimal pendapatan atau laba bersih." });
    }
  });

export type AnalysisFormValues = z.infer<typeof analysisFormSchema>;

const emptyValues = (fields: ValueField[]) => Object.fromEntries(fields.map((f) => [f, ""])) as Record<ValueField, string>;

export function defaultFormValues(): AnalysisFormValues {
  const lastYear = new Date().getFullYear() - 1;
  return {
    ticker: "",
    name: "",
    sector: "",
    fiscal_year: String(lastYear),
    basis: "annual",
    period: "FY",
    currency: "IDR",
    unit: "juta",
    fx_rate: "",
    current: emptyValues(ALL_FIELDS),
    include_previous: true,
    prev_fiscal_year: String(lastYear - 1),
    prev_period: "FY",
    previous: emptyValues(PREVIOUS_FIELDS),
    share_price: "",
    share_price_date: "",
    price_source: "",
  };
}

function toValues(raw: Record<string, string>, fields: ValueField[]): FinancialValues {
  const out: FinancialValues = {};
  for (const f of fields) {
    const n = parseIdNumber(raw[f]);
    if (n !== undefined && !Number.isNaN(n)) out[f] = n;
  }
  return out;
}

export interface FetchedPrice {
  provider: string;
  provider_symbol: string;
  price: number;
  trading_date: string;
  fetched_at: string;
}

export function toAnalysisInput(v: AnalysisFormValues, source: SourceInfo, fetched?: FetchedPrice | null): AnalysisInput {
  const prevValues = toValues(v.previous, PREVIOUS_FIELDS);
  const price = parseIdNumber(v.share_price);
  const fx = parseIdNumber(v.fx_rate);
  return {
    company: {
      ticker: v.ticker.trim().toUpperCase(),
      name: v.name.trim(),
      sector: (v.sector || null) as Sector | null,
    },
    statement: {
      fiscal_year: Number(v.fiscal_year),
      period: v.period as Period,
      basis: v.basis as Basis,
      currency: v.currency as Currency,
      unit: v.unit as Unit,
      fx_rate_to_idr: v.currency !== "IDR" && fx !== undefined && !Number.isNaN(fx) ? fx : null,
    },
    current: toValues(v.current, ALL_FIELDS),
    previous: v.include_previous
      ? { fiscal_year: Number(v.prev_fiscal_year), period: v.prev_period as Period, values: prevValues }
      : null,
    market: {
      share_price: price !== undefined && !Number.isNaN(price) ? price : null,
      share_price_date: v.share_price_date || null,
      price_source: v.price_source.trim() || null,
      // Provider origin only if the price and date are still exactly what was fetched;
      // the server re-verifies this claim before saving.
      ...(fetched && price === fetched.price && v.share_price_date === fetched.trading_date
        ? {
            price_origin: "provider" as const,
            price_provider: fetched.provider,
            price_provider_symbol: fetched.provider_symbol,
            price_fetched_at: fetched.fetched_at,
          }
        : { price_origin: "manual" as const }),
    },
    source,
  };
}

/** Map a backend field path (e.g. "current.revenue") to a human label. */
export function fieldPathLabel(path: string | null | undefined): string {
  if (!path) return "Umum";
  const parts = path.split(".");
  const last = parts[parts.length - 1] as ValueField;
  const prefix = parts[0] === "previous" ? "Pembanding — " : "";
  if (FIELD_META[last]) return prefix + FIELD_META[last].label;
  const misc: Record<string, string> = {
    ticker: "Kode saham",
    name: "Nama perusahaan",
    sector: "Sektor",
    fiscal_year: "Tahun fiskal",
    period: "Periode",
    unit: "Satuan",
    fx_rate_to_idr: "Kurs ke IDR",
    share_price: "Harga saham",
    share_price_date: "Tanggal harga",
  };
  return prefix + (misc[last] ?? path);
}
