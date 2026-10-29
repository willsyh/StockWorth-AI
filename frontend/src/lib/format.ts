// Indonesian-locale number, currency and date formatting.
import type { Currency, MetricResult } from "@/types/api";

const LOCALE = "id-ID";

export function formatNumber(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return new Intl.NumberFormat(LOCALE, { minimumFractionDigits: 0, maximumFractionDigits: digits }).format(v);
}

export function formatFixed(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return new Intl.NumberFormat(LOCALE, { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(v);
}

export function formatPercent(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return `${formatFixed(v, digits)}%`;
}

/** Compact money: "Rp 1,23 triliun". */
export function formatMoneyCompact(v: number | null | undefined, currency: Currency = "IDR"): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  const sign = v < 0 ? "-" : "";
  const a = Math.abs(v);
  const prefix = currency === "IDR" ? "Rp" : "US$";
  const scales: [number, string][] = [
    [1e12, "triliun"],
    [1e9, "miliar"],
    [1e6, "juta"],
  ];
  for (const [size, word] of scales) {
    if (a >= size) return `${sign}${prefix} ${formatFixed(a / size, 2)} ${word}`;
  }
  return `${sign}${prefix} ${formatNumber(a, 0)}`;
}

export function formatMoney(v: number | null | undefined, currency: Currency = "IDR", digits = 0): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return new Intl.NumberFormat(LOCALE, {
    style: "currency",
    currency,
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(v);
}

/** Short axis label for charts: "1,2 T" / "350 M" (triliun/miliar). */
export function formatAxisMoney(v: number): string {
  const a = Math.abs(v);
  if (a >= 1e12) return `${formatNumber(v / 1e12, 1)} T`;
  if (a >= 1e9) return `${formatNumber(v / 1e9, 1)} M`;
  if (a >= 1e6) return `${formatNumber(v / 1e6, 1)} jt`;
  return formatNumber(v, 0);
}

export function formatMetric(m: MetricResult | undefined, currency: Currency = "IDR"): string {
  if (!m || m.value === null || m.status !== "ok") return "Belum tersedia";
  switch (m.unit) {
    case "percent":
      return formatPercent(m.value);
    case "ratio":
      return `${formatFixed(m.value, 2)}x`;
    case "currency":
      return formatMoneyCompact(m.value, currency);
    case "currency_per_share":
      return currency === "IDR" ? formatMoney(m.value, "IDR", 2) : `${formatNumber(m.value, 4)} ${currency}`;
    case "idr_per_share":
      return formatMoney(m.value, "IDR", 2);
  }
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat(LOCALE, { day: "numeric", month: "short", year: "numeric" }).format(d);
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat(LOCALE, {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(d);
}

/**
 * Parse a number typed in Indonesian format: "." groups thousands, "," is the decimal mark.
 * Returns undefined for empty input, NaN for invalid input.
 */
export function parseIdNumber(raw: string | null | undefined): number | undefined {
  if (raw === null || raw === undefined) return undefined;
  let s = raw.trim().replace(/\s| /g, "");
  if (s === "") return undefined;
  let negative = false;
  if (s.startsWith("(") && s.endsWith(")")) {
    negative = true;
    s = s.slice(1, -1);
  }
  if (s.startsWith("-")) {
    negative = !negative;
    s = s.slice(1);
  }
  if (!/^[\d.,]+$/.test(s) || !/\d/.test(s)) return NaN;
  const [intPart, decPart, ...rest] = s.split(",");
  if (rest.length) return NaN;
  if (intPart.includes(".") && !/^\d{1,3}(\.\d{3})+$/.test(intPart)) return NaN;
  const normalized = intPart.replace(/\./g, "") + (decPart !== undefined ? `.${decPart}` : "");
  if (normalized === "" || normalized === ".") return NaN;
  const v = Number(normalized);
  if (!Number.isFinite(v)) return NaN;
  return negative ? -v : v;
}

/** Format a number for display inside an editable input. */
export function toInputString(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "";
  return new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 6, useGrouping: true }).format(v);
}
