import { useMemo, useState, type ReactNode } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { LineChart as LineChartIcon, Table2 } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyState } from "@/components/ui/states";
import { useTheme } from "@/app/theme";
import { formatAxisMoney, formatFixed, formatMoneyCompact, formatPercent } from "@/lib/format";
import type { AnalysisRecord, AnalysisSummary, Currency, Period } from "@/types/api";

// Validated categorical palette (green, violet, amber), stepped per theme and checked for colour-blind separation.
const PALETTE = {
  light: { s1: "#138a52", s2: "#6250d6", s3: "#eda100", grid: "#e7eaf0", axis: "#5f6675", surface: "#ffffff" },
  dark: { s1: "#25a366", s2: "#9085e9", s3: "#c98500", grid: "#263149", axis: "#a0aac0", surface: "#121a2b" },
};

export interface TrendPoint {
  key: string;
  label: string;
  fiscal_year: number;
  period: Period;
  revenue: number | null;
  net_income: number | null;
  operating_cash_flow: number | null;
  free_cash_flow: number | null;
  npm: number | null;
  roe: number | null;
  roa: number | null;
  der: number | null;
  source: string;
}

const PERIOD_ORDER: Record<Period, number> = { Q1: 1, Q2: 2, Q3: 3, Q4: 4, FY: 5 };

/**
 * Build chart points from actual saved data only:
 *  - each saved analysis of the same ticker, basis and currency contributes its own period;
 *  - the open analysis's comparative period contributes the values the user entered for it.
 * No values are interpolated or generated.
 */
export function buildTrendPoints(current: AnalysisRecord, history: AnalysisSummary[]): TrendPoint[] {
  const currency = current.input.statement.currency;
  const basis = current.basis;
  const map = new Map<string, TrendPoint>();
  const label = (fy: number, p: Period) => (basis === "annual" ? `FY${fy}` : basis === "ytd" ? `${p} ${fy} (kum.)` : `${p} ${fy}`);

  const comparable = history
    .filter((h) => h.ticker === current.ticker && h.basis === basis && h.currency === currency)
    .sort((a, b) => a.created_at.localeCompare(b.created_at)); // newest wins below
  for (const h of comparable) {
    const key = `${h.fiscal_year}-${h.period}`;
    map.set(key, {
      key,
      label: label(h.fiscal_year, h.period),
      fiscal_year: h.fiscal_year,
      period: h.period,
      revenue: h.key_figures.revenue,
      net_income: h.key_figures.net_income,
      operating_cash_flow: h.key_figures.operating_cash_flow,
      free_cash_flow: h.key_figures.free_cash_flow,
      npm: h.key_figures.npm,
      roe: h.key_figures.roe,
      roa: h.key_figures.roa,
      der: h.key_figures.der,
      source: h.id === current.id ? "Analisis ini" : "Analisis tersimpan",
    });
  }

  const prev = current.result.normalized?.previous;
  if (prev) {
    const key = `${prev.fiscal_year}-${prev.period}`;
    if (!map.has(key)) {
      const v = prev.values;
      const ni = v.net_income ?? v.net_income_attributable ?? null;
      const ocf = v.operating_cash_flow ?? null;
      const capex = v.capital_expenditure ?? null;
      map.set(key, {
        key,
        label: label(prev.fiscal_year, prev.period),
        fiscal_year: prev.fiscal_year,
        period: prev.period,
        revenue: v.revenue ?? null,
        net_income: ni,
        operating_cash_flow: ocf,
        free_cash_flow: ocf !== null && capex !== null ? ocf - capex : null,
        npm: null,
        roe: null,
        roa: null,
        der: null,
        source: "Data pembanding yang Anda masukkan",
      });
    }
  }

  return [...map.values()].sort((a, b) => a.fiscal_year - b.fiscal_year || PERIOD_ORDER[a.period] - PERIOD_ORDER[b.period]);
}

const countWith = (pts: TrendPoint[], keys: (keyof TrendPoint)[]) =>
  pts.filter((p) => keys.some((k) => p[k] !== null && p[k] !== undefined)).length;

function ChartTooltip({
  active,
  payload,
  label,
  formatter,
}: {
  active?: boolean;
  payload?: { name: string; value: number | null; color: string; payload: TrendPoint }[];
  label?: string;
  formatter: (v: number) => string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border bg-popover px-3 py-2 text-xs shadow-md">
      <p className="mb-1 font-medium">{label}</p>
      {payload.map((p) => (
        <p key={p.name} className="flex items-center gap-2">
          <span className="size-2 rounded-full" style={{ background: p.color }} aria-hidden="true" />
          <span className="text-muted-foreground">{p.name}:</span>
          <span className="tabular font-medium">{p.value === null || p.value === undefined ? "Belum tersedia" : formatter(p.value)}</span>
        </p>
      ))}
      <p className="mt-1 text-[11px] text-muted-foreground">Sumber: {payload[0].payload.source}</p>
    </div>
  );
}

function ChartCard({ title, description, children }: { title: string; description: string; children: ReactNode }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="h-64 pt-2">{children}</CardContent>
    </Card>
  );
}

export function TrendCharts({ points, currency }: { points: TrendPoint[]; currency: Currency }) {
  const { resolvedTheme } = useTheme();
  const c = PALETTE[resolvedTheme];
  const [showTable, setShowTable] = useState(false);
  const axisProps = { stroke: c.axis, fontSize: 11, tickLine: false, axisLine: false } as const;
  const money = (v: number | null) => formatMoneyCompact(v, currency);

  const counts = useMemo(
    () => ({
      income: countWith(points, ["revenue", "net_income"]),
      profitability: countWith(points, ["npm", "roe", "roa"]),
      cash: countWith(points, ["operating_cash_flow", "free_cash_flow"]),
      der: countWith(points, ["der"]),
    }),
    [points],
  );

  if (counts.income < 2 && counts.profitability < 2 && counts.cash < 2) {
    return (
      <EmptyState
        icon={LineChartIcon}
        title="Belum ada data historis untuk grafik"
        description="Grafik tren hanya ditampilkan dari data yang benar-benar tersimpan. Tambahkan data periode pembanding atau simpan analisis periode lain untuk emiten ini."
      />
    );
  }

  const legend = (
    <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 12 }} formatter={(value: string) => <span style={{ color: c.axis }}>{value}</span>} />
  );
  const bar = { radius: [4, 4, 0, 0] as [number, number, number, number], maxBarSize: 36 };

  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-2">
        {counts.income >= 2 && (
          <ChartCard title="Pendapatan & laba bersih" description={`Dalam ${currency}, per periode yang tersimpan.`}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={points} barGap={2} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                <CartesianGrid vertical={false} stroke={c.grid} />
                <XAxis dataKey="label" {...axisProps} />
                <YAxis tickFormatter={formatAxisMoney} width={56} {...axisProps} />
                <ReferenceLine y={0} stroke={c.axis} strokeOpacity={0.5} />
                <Tooltip cursor={{ fill: c.grid, opacity: 0.4 }} content={<ChartTooltip formatter={money} />} />
                {legend}
                <Bar dataKey="revenue" name="Pendapatan" fill={c.s1} {...bar} />
                <Bar dataKey="net_income" name="Laba bersih" fill={c.s2} {...bar} />
              </BarChart>
            </ResponsiveContainer>
          </ChartCard>
        )}
        {counts.cash >= 2 && (
          <ChartCard title="Arus kas" description="Arus kas operasi dan free cash flow.">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={points} barGap={2} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                <CartesianGrid vertical={false} stroke={c.grid} />
                <XAxis dataKey="label" {...axisProps} />
                <YAxis tickFormatter={formatAxisMoney} width={56} {...axisProps} />
                <ReferenceLine y={0} stroke={c.axis} strokeOpacity={0.5} />
                <Tooltip cursor={{ fill: c.grid, opacity: 0.4 }} content={<ChartTooltip formatter={money} />} />
                {legend}
                <Bar dataKey="operating_cash_flow" name="Arus kas operasi" fill={c.s1} {...bar} />
                <Bar dataKey="free_cash_flow" name="Free cash flow" fill={c.s3} {...bar} />
              </BarChart>
            </ResponsiveContainer>
          </ChartCard>
        )}
        {counts.profitability >= 2 && (
          <ChartCard title="Tren profitabilitas" description="NPM, ROE, dan ROA (%), hanya dari analisis tersimpan.">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={points} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                <CartesianGrid vertical={false} stroke={c.grid} />
                <XAxis dataKey="label" {...axisProps} />
                <YAxis tickFormatter={(v: number) => `${formatFixed(v, 0)}%`} width={44} {...axisProps} />
                <Tooltip content={<ChartTooltip formatter={(v) => formatPercent(v)} />} />
                {legend}
                {(["npm", "roe", "roa"] as const).map((k, i) => (
                  <Line
                    key={k}
                    type="monotone"
                    dataKey={k}
                    name={k.toUpperCase()}
                    stroke={[c.s1, c.s2, c.s3][i]}
                    strokeWidth={2}
                    dot={{ r: 4, strokeWidth: 2, stroke: c.surface }}
                    activeDot={{ r: 5 }}
                    connectNulls={false}
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </ChartCard>
        )}
        {counts.der >= 2 && (
          <ChartCard title="Debt to equity historis" description="DER (x) dari analisis tersimpan.">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={points} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                <CartesianGrid vertical={false} stroke={c.grid} />
                <XAxis dataKey="label" {...axisProps} />
                <YAxis tickFormatter={(v: number) => `${formatFixed(v, 1)}x`} width={44} {...axisProps} />
                <Tooltip content={<ChartTooltip formatter={(v) => `${formatFixed(v, 2)}x`} />} />
                <Line type="monotone" dataKey="der" name="DER" stroke={c.s1} strokeWidth={2} dot={{ r: 4, strokeWidth: 2, stroke: c.surface }} />
              </LineChart>
            </ResponsiveContainer>
          </ChartCard>
        )}
      </div>

      <div>
        <Button variant="ghost" size="sm" onClick={() => setShowTable((s) => !s)} aria-expanded={showTable}>
          <Table2 /> {showTable ? "Sembunyikan tabel data" : "Tampilkan tabel data & perbandingan rasio"}
        </Button>
        {showTable && (
          <Card className="mt-2">
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Periode</TableHead>
                    <TableHead className="text-right">Pendapatan</TableHead>
                    <TableHead className="text-right">Laba bersih</TableHead>
                    <TableHead className="text-right">OCF</TableHead>
                    <TableHead className="text-right">FCF</TableHead>
                    <TableHead className="text-right">NPM</TableHead>
                    <TableHead className="text-right">ROE</TableHead>
                    <TableHead className="text-right">ROA</TableHead>
                    <TableHead className="text-right">DER</TableHead>
                    <TableHead>Sumber</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {points.map((p) => (
                    <TableRow key={p.key}>
                      <TableCell className="font-medium">{p.label}</TableCell>
                      <TableCell className="tabular text-right">{money(p.revenue)}</TableCell>
                      <TableCell className="tabular text-right">{money(p.net_income)}</TableCell>
                      <TableCell className="tabular text-right">{money(p.operating_cash_flow)}</TableCell>
                      <TableCell className="tabular text-right">{money(p.free_cash_flow)}</TableCell>
                      <TableCell className="tabular text-right">{formatPercent(p.npm)}</TableCell>
                      <TableCell className="tabular text-right">{formatPercent(p.roe)}</TableCell>
                      <TableCell className="tabular text-right">{formatPercent(p.roa)}</TableCell>
                      <TableCell className="tabular text-right">{p.der === null ? "—" : `${formatFixed(p.der, 2)}x`}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">{p.source}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
