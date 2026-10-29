import type { Basis, Period, Sector, Unit, ValueField } from "@/types/api";

export interface FieldMeta {
  key: ValueField;
  label: string;
  short: string;
  help: string;
  kind: "money" | "shares";
  /** Metrics that need this field, shown so users know what an empty field costs them. */
  usedFor: string[];
}

export const FIELD_META: Record<ValueField, FieldMeta> = {
  revenue: {
    key: "revenue",
    label: "Pendapatan",
    short: "Pendapatan",
    help: "Pendapatan usaha / penjualan bersih pada laporan laba rugi.",
    kind: "money",
    usedFor: ["NPM", "Pertumbuhan pendapatan", "Margin FCF"],
  },
  net_income: {
    key: "net_income",
    label: "Laba bersih (total)",
    short: "Laba bersih",
    help: "Laba tahun/periode berjalan, termasuk bagian kepentingan non-pengendali. Isi angka negatif jika rugi.",
    kind: "money",
    usedFor: ["NPM", "ROA", "Kualitas arus kas"],
  },
  net_income_attributable: {
    key: "net_income_attributable",
    label: "Laba yang diatribusikan ke pemilik entitas induk",
    short: "Laba ke entitas induk",
    help: "Bagian laba untuk pemegang saham biasa entitas induk. Dipakai untuk ROE dan EPS. Jika kosong, laba bersih total dipakai dan dicatat sebagai asumsi.",
    kind: "money",
    usedFor: ["ROE", "EPS", "PER"],
  },
  total_assets: {
    key: "total_assets",
    label: "Total aset (akhir periode)",
    short: "Total aset akhir",
    help: "Jumlah aset pada tanggal laporan posisi keuangan.",
    kind: "money",
    usedFor: ["ROA"],
  },
  total_assets_begin: {
    key: "total_assets_begin",
    label: "Total aset (awal periode)",
    short: "Total aset awal",
    help: "Saldo awal periode, untuk menghitung rata-rata aset. Untuk laporan tahunan, boleh dikosongkan jika total aset tahun lalu diisi pada periode pembanding.",
    kind: "money",
    usedFor: ["ROA"],
  },
  total_liabilities: {
    key: "total_liabilities",
    label: "Total liabilitas",
    short: "Total liabilitas",
    help: "Jumlah liabilitas jangka pendek dan jangka panjang.",
    kind: "money",
    usedFor: ["DER"],
  },
  total_equity: {
    key: "total_equity",
    label: "Total ekuitas (akhir periode)",
    short: "Total ekuitas akhir",
    help: "Total ekuitas, termasuk kepentingan non-pengendali. Bisa negatif (defisiensi modal).",
    kind: "money",
    usedFor: ["DER", "ROE (cadangan)", "BVPS (cadangan)"],
  },
  total_equity_begin: {
    key: "total_equity_begin",
    label: "Total ekuitas (awal periode)",
    short: "Total ekuitas awal",
    help: "Saldo awal periode untuk rata-rata ekuitas.",
    kind: "money",
    usedFor: ["ROE (cadangan)"],
  },
  equity_attributable: {
    key: "equity_attributable",
    label: "Ekuitas pemilik entitas induk (akhir)",
    short: "Ekuitas induk akhir",
    help: "Ekuitas yang dapat diatribusikan kepada pemilik entitas induk, tidak termasuk kepentingan non-pengendali.",
    kind: "money",
    usedFor: ["ROE", "BVPS", "PBV"],
  },
  equity_attributable_begin: {
    key: "equity_attributable_begin",
    label: "Ekuitas pemilik entitas induk (awal)",
    short: "Ekuitas induk awal",
    help: "Saldo awal periode, untuk rata-rata ekuitas pada ROE.",
    kind: "money",
    usedFor: ["ROE"],
  },
  current_assets: {
    key: "current_assets",
    label: "Aset lancar",
    short: "Aset lancar",
    help: "Aset yang diharapkan terealisasi dalam 12 bulan. Tidak diterapkan untuk sektor keuangan.",
    kind: "money",
    usedFor: ["Current ratio"],
  },
  current_liabilities: {
    key: "current_liabilities",
    label: "Liabilitas jangka pendek",
    short: "Liabilitas lancar",
    help: "Kewajiban yang jatuh tempo dalam 12 bulan.",
    kind: "money",
    usedFor: ["Current ratio"],
  },
  operating_cash_flow: {
    key: "operating_cash_flow",
    label: "Arus kas dari aktivitas operasi",
    short: "Arus kas operasi",
    help: "Kas bersih yang diperoleh dari (atau digunakan untuk) aktivitas operasi. Bisa negatif.",
    kind: "money",
    usedFor: ["Arus kas operasi", "FCF", "Kualitas arus kas"],
  },
  capital_expenditure: {
    key: "capital_expenditure",
    label: "Belanja modal (capex)",
    short: "Capex",
    help: "Perolehan aset tetap dan aset tak berwujud, diisi sebagai angka positif.",
    kind: "money",
    usedFor: ["FCF", "Margin FCF"],
  },
  weighted_average_shares: {
    key: "weighted_average_shares",
    label: "Rata-rata tertimbang saham biasa beredar",
    short: "Saham rata-rata tertimbang",
    help: "Dalam lembar (tidak mengikuti satuan laporan). Lihat catatan laba per saham.",
    kind: "shares",
    usedFor: ["EPS", "PER"],
  },
  shares_outstanding: {
    key: "shares_outstanding",
    label: "Jumlah saham beredar (akhir periode)",
    short: "Saham beredar",
    help: "Dalam lembar, setelah dikurangi saham treasuri.",
    kind: "shares",
    usedFor: ["BVPS", "PBV"],
  },
};

export const FIELD_GROUPS: { title: string; description: string; fields: ValueField[] }[] = [
  {
    title: "Laba rugi",
    description: "Dari laporan laba rugi dan penghasilan komprehensif lain.",
    fields: ["revenue", "net_income", "net_income_attributable"],
  },
  {
    title: "Posisi keuangan",
    description: "Saldo akhir dan awal periode dari laporan posisi keuangan (neraca).",
    fields: [
      "total_assets",
      "total_assets_begin",
      "total_liabilities",
      "total_equity",
      "total_equity_begin",
      "equity_attributable",
      "equity_attributable_begin",
      "current_assets",
      "current_liabilities",
    ],
  },
  {
    title: "Arus kas",
    description: "Dari laporan arus kas.",
    fields: ["operating_cash_flow", "capital_expenditure"],
  },
  {
    title: "Saham",
    description: "Jumlah saham dalam lembar. Tidak mengikuti satuan laporan.",
    fields: ["weighted_average_shares", "shares_outstanding"],
  },
];

export const PREVIOUS_FIELDS: ValueField[] = [
  "revenue",
  "net_income",
  "net_income_attributable",
  "total_assets",
  "total_liabilities",
  "total_equity",
  "equity_attributable",
  "operating_cash_flow",
  "capital_expenditure",
];

export const ALL_FIELDS = Object.keys(FIELD_META) as ValueField[];

export const SECTORS: { value: Sector; label: string }[] = [
  { value: "energy", label: "Energi" },
  { value: "basic_materials", label: "Barang Baku" },
  { value: "industrials", label: "Perindustrian" },
  { value: "consumer_non_cyclicals", label: "Barang Konsumen Primer" },
  { value: "consumer_cyclicals", label: "Barang Konsumen Non-Primer" },
  { value: "healthcare", label: "Kesehatan" },
  { value: "financials_bank", label: "Keuangan — Perbankan" },
  { value: "financials_non_bank", label: "Keuangan — Non-Bank" },
  { value: "properties", label: "Properti & Real Estat" },
  { value: "technology", label: "Teknologi" },
  { value: "infrastructures", label: "Infrastruktur" },
  { value: "transportation", label: "Transportasi & Logistik" },
];

export const sectorLabel = (s: Sector | null | undefined) => SECTORS.find((x) => x.value === s)?.label ?? "Sektor tidak diisi";

export const UNITS: { value: Unit; label: string }[] = [
  { value: "unit", label: "Satuan penuh" },
  { value: "ribu", label: "Ribuan" },
  { value: "juta", label: "Jutaan" },
  { value: "miliar", label: "Miliaran" },
];

export const BASES: { value: Basis; label: string; description: string }[] = [
  { value: "annual", label: "Tahunan", description: "Laporan setahun penuh (12 bulan)." },
  { value: "ytd", label: "Kuartalan — kumulatif", description: "Akumulasi sejak awal tahun buku (3, 6, 9, atau 12 bulan)." },
  { value: "quarterly", label: "Kuartalan — per kuartal", description: "Satu kuartal saja (3 bulan)." },
];

export const PERIODS_FOR: Record<Basis, Period[]> = {
  annual: ["FY"],
  ytd: ["Q1", "Q2", "Q3", "Q4"],
  quarterly: ["Q1", "Q2", "Q3", "Q4"],
};

export function periodLabel(fy: number, period: Period, basis: Basis): string {
  if (basis === "annual") return `FY${fy}`;
  if (basis === "ytd") {
    const months = { Q1: 3, Q2: 6, Q3: 9, Q4: 12, FY: 12 }[period];
    return `${months}M${fy} (kumulatif)`;
  }
  return `${period} ${fy}`;
}

export const METRIC_HELP: Record<string, string> = {
  npm: "Berapa persen pendapatan yang tersisa menjadi laba bersih.",
  roe: "Seberapa efisien perusahaan menghasilkan laba dari modal pemegang saham, memakai rata-rata ekuitas.",
  roa: "Seberapa efisien aset menghasilkan laba, memakai rata-rata total aset.",
  der: "Besar utang relatif terhadap modal sendiri. Wajar tidaknya bergantung pada sektor.",
  current_ratio: "Kemampuan membayar kewajiban jangka pendek dengan aset lancar.",
  revenue_growth: "Perubahan pendapatan dibanding periode yang sama tahun sebelumnya.",
  net_income_growth: "Perubahan laba dibanding periode yang sama tahun sebelumnya.",
  eps: "Laba bersih per lembar saham biasa (EPS dasar).",
  per: "Berapa kali laba tahunan yang dibayar investor per lembar saham.",
  bvps: "Nilai buku ekuitas per lembar saham.",
  pbv: "Harga saham dibanding nilai bukunya.",
  operating_cash_flow: "Kas yang dihasilkan dari kegiatan usaha inti.",
  free_cash_flow: "Kas operasi setelah belanja modal; dana yang tersedia untuk dividen, utang, atau ekspansi.",
  fcf_margin: "Free cash flow sebagai persentase pendapatan.",
  cash_flow_quality: "Arus kas operasi dibanding laba bersih; menunjukkan seberapa besar laba didukung kas.",
};
