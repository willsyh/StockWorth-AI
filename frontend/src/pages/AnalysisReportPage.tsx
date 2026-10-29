import { useMemo } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { AlertTriangle, CalendarClock, Database, FilePlus2, FileSearch, ShieldAlert, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/misc";
import { EmptyState, ErrorState, Notice, errorMessage } from "@/components/ui/states";
import { MetricCard, ScoreBar, ScoreStatusBadge, Section, SeverityIcon, SourceLabel } from "@/components/analysis/display";
import { InsightsPanel } from "@/components/analysis/InsightsPanel";
import { TrendCharts, buildTrendPoints } from "@/components/charts/TrendCharts";
import { useAnalyses, useAnalysis, useDeleteAnalysis } from "@/hooks/queries";
import { ApiError } from "@/lib/api";
import { marketProviderLabel, sectorLabel } from "@/lib/fields";
import { formatDate, formatDateTime, formatFixed } from "@/lib/format";
import type { AnalysisRecord, DimensionScore, Finding, FindingSection, ScoreResult } from "@/types/api";

const SECTIONS: { id: string; title: string }[] = [
  { id: "ringkasan", title: "Ringkasan Fundamental" },
  { id: "profitabilitas", title: "Profitabilitas" },
  { id: "pertumbuhan", title: "Pertumbuhan" },
  { id: "utang", title: "Utang dan Likuiditas" },
  { id: "arus-kas", title: "Arus Kas" },
  { id: "valuasi", title: "Valuasi" },
  { id: "risiko", title: "Risiko Utama" },
  { id: "data", title: "Data yang Masih Dibutuhkan" },
  { id: "tren", title: "Grafik Tren" },
  { id: "insight", title: "AI Insights" },
];

function ScoreCard({ title, score, description }: { title: string; score: ScoreResult; description: string }) {
  return (
    <Card>
      <CardContent className="p-5">
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs font-medium text-muted-foreground">{title}</p>
          <ScoreStatusBadge status={score.status} />
        </div>
        {score.score !== null ? (
          <>
            <p className="tabular mt-2 text-3xl font-semibold tracking-tight">
              {formatFixed(score.score, 0)}
              <span className="text-base font-normal text-muted-foreground"> / 100</span>
            </p>
            <p className="mb-3 text-sm font-medium">{score.label}</p>
            <ScoreBar score={score.score} />
          </>
        ) : (
          <>
            <p className="mt-2 text-lg font-semibold text-muted-foreground">Belum tersedia</p>
            <p className="mt-1 text-xs text-muted-foreground">{score.notes[score.notes.length - 1]}</p>
          </>
        )}
        <p className="mt-3 text-xs text-muted-foreground">{description}</p>
      </CardContent>
    </Card>
  );
}

function FindingList({ findings, empty = "Tidak ada temuan untuk bagian ini." }: { findings: Finding[]; empty?: string }) {
  if (!findings.length) return <p className="text-sm text-muted-foreground">{empty}</p>;
  return (
    <ul className="space-y-2">
      {findings.map((f, i) => (
        <li key={i} className="flex gap-2.5 text-sm leading-relaxed">
          <SeverityIcon severity={f.severity} />
          <span>{f.text}</span>
        </li>
      ))}
    </ul>
  );
}

function DimensionTable({ dims }: { dims: DimensionScore[] }) {
  return (
    <div className="divide-y rounded-lg border">
      {dims.map((d) => (
        <details key={d.key} className="group px-4 py-3">
          <summary className="flex cursor-pointer list-none items-center gap-3 [&::-webkit-details-marker]:hidden">
            <span className="w-36 shrink-0 text-sm font-medium sm:w-44">{d.label}</span>
            <span className="tabular hidden w-14 shrink-0 text-xs text-muted-foreground sm:inline">Bobot {formatFixed(d.weight * 100, 0)}%</span>
            <div className="min-w-0 flex-1">{d.applicable ? <ScoreBar score={d.score} /> : <span className="text-xs text-muted-foreground">Tidak diterapkan</span>}</div>
            <span className="tabular w-16 shrink-0 text-right text-sm font-semibold">
              {d.score !== null ? formatFixed(d.score, 0) : d.applicable ? "—" : "n/a"}
            </span>
          </summary>
          <div className="mt-3 space-y-2 pl-0 sm:pl-44">
            {d.note && <p className="text-xs text-muted-foreground">{d.note}</p>}
            {d.applicable && <p className="text-xs text-muted-foreground">Cakupan metrik: {formatFixed(d.coverage * 100, 0)}%</p>}
            {d.metrics.map((m) => (
              <div key={m.metric} className="rounded-md bg-muted/50 px-3 py-2 text-xs">
                <p className="flex justify-between gap-2">
                  <span className="font-medium">{m.label}</span>
                  <span className="tabular font-semibold">{m.score !== null ? `${formatFixed(m.score, 0)}/100` : "Tidak dinilai"}</span>
                </p>
                <p className="mt-0.5 text-muted-foreground">{m.rule}</p>
                {m.note && <p className="mt-0.5 text-muted-foreground">{m.note}</p>}
              </div>
            ))}
          </div>
        </details>
      ))}
    </div>
  );
}

function Report({ rec }: { rec: AnalysisRecord }) {
  const navigate = useNavigate();
  const del = useDeleteAnalysis();
  const history = useAnalyses({ ticker: rec.ticker, limit: 200, sort: "asc" });
  const r = rec.result;
  const currency = rec.input.statement.currency;
  const m = r.metrics;
  const by = (s: FindingSection) => r.findings.filter((f) => f.section === s);
  // One list feeds both the risk indicator card and the "Risiko Utama" section.
  const risks = r.findings.filter(
    (f) => f.section !== "summary" && f.section !== "missing" && (f.section === "risk" || f.severity === "negative" || (f.severity === "warning" && f.section !== "valuation")),
  );
  const fundamentalOk = r.fundamental_score.score !== null;
  const points = useMemo(() => buildTrendPoints(rec, history.data?.items ?? []), [rec, history.data]);
  const src = rec.input.source;

  const onDelete = () =>
    del.mutate(rec.id, {
      onSuccess: () => {
        toast.success("Analisis dihapus.");
        navigate("/riwayat");
      },
      onError: (e) => toast.error(errorMessage(e)),
    });

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-semibold tracking-tight">{rec.ticker}</h1>
            <Badge variant="outline">{r.period_label}</Badge>
            <Badge variant="warning" title="Kode saham dan nama dimasukkan pengguna dan belum diverifikasi terhadap data BEI">
              Metadata belum diverifikasi
            </Badge>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">
            {rec.company_name} · {sectorLabel(rec.sector)}
          </p>
          <dl className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5 text-xs text-muted-foreground">
            <div className="flex items-center gap-1.5">
              <Database className="size-3.5" aria-hidden="true" />
              <dt className="sr-only">Sumber data</dt>
              <dd>
                {src.method === "manual" ? "Input manual" : `Impor ${src.method.toUpperCase()}: ${src.file_name}`}
                {src.edited_after_import.length > 0 && ` (${src.edited_after_import.length} nilai diubah)`}
              </dd>
            </div>
            <div className="flex items-center gap-1.5">
              <CalendarClock className="size-3.5" aria-hidden="true" />
              <dt className="sr-only">Waktu analisis</dt>
              <dd>Dianalisis {formatDateTime(rec.created_at)}</dd>
            </div>
            <div>
              <dt className="sr-only">Metodologi</dt>
              <dd>Metodologi v{rec.methodology_version} · profil {r.scoring_profile}</dd>
            </div>
            {rec.input.market.share_price_date && (
              <div>
                <dt className="sr-only">Tanggal harga</dt>
                <dd>
                  Harga per {formatDate(rec.input.market.share_price_date)}{" "}
                  {rec.input.market.price_origin === "provider"
                    ? `(dari ${marketProviderLabel(rec.input.market.price_provider)}, ${rec.input.market.price_provider_symbol})`
                    : "(diisi pengguna)"}
                </dd>
              </div>
            )}
          </dl>
        </div>
        <div className="flex shrink-0 gap-2">
          <Button asChild variant="outline" size="sm">
            <Link to="/analisis/baru">
              <FilePlus2 /> Analisis baru
            </Link>
          </Button>
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button variant="outline" size="sm" className="text-negative hover:text-negative">
                <Trash2 /> Hapus
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogTitle>Hapus analisis {rec.ticker}?</AlertDialogTitle>
              <AlertDialogDescription>
                Analisis {r.period_label} beserta insight-nya akan dihapus permanen. Tindakan ini tidak dapat dibatalkan.
              </AlertDialogDescription>
              <AlertDialogFooter>
                <AlertDialogCancel>Batal</AlertDialogCancel>
                <AlertDialogAction onClick={onDelete}>Hapus</AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      </div>

      {r.issues.length > 0 && (
        <Notice tone="warning" icon={AlertTriangle}>
          <p className="font-medium">Catatan data ({r.issues.length})</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-4">
            {r.issues.map((i) => (
              <li key={i.message}>{i.message}</li>
            ))}
          </ul>
        </Notice>
      )}

      {/* Scores */}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <ScoreCard title="Skor Fundamental" score={r.fundamental_score} description="Kualitas bisnis: profitabilitas, pertumbuhan, leverage, likuiditas, arus kas." />
        <ScoreCard title="Skor Valuasi" score={r.valuation_score} description="PER/PBV dibanding rentang acuan. Bukan estimasi nilai wajar." />
        <Card>
          <CardContent className="p-5">
            <p className="text-xs font-medium text-muted-foreground">Kelengkapan Data</p>
            <p className="tabular mt-2 text-3xl font-semibold tracking-tight">{formatFixed(r.completeness.percent, 0)}%</p>
            <p className="mb-3 text-sm font-medium">
              {r.completeness.provided} dari {r.completeness.applicable} data inti
            </p>
            <ScoreBar score={r.completeness.percent} />
            <p className="mt-3 text-xs text-muted-foreground">Cakupan skor fundamental: {formatFixed(r.fundamental_score.coverage * 100, 0)}%.</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-5">
            <p className="text-xs font-medium text-muted-foreground">Indikator Risiko</p>
            <p className="tabular mt-2 text-3xl font-semibold tracking-tight">{risks.length}</p>
            <p className="mb-2 text-sm font-medium">{risks.length ? "temuan perlu perhatian" : "Tidak ada sinyal risiko utama"}</p>
            <ul className="space-y-1">
              {risks.slice(0, 2).map((f, i) => (
                <li key={i} className="flex gap-1.5 text-xs text-muted-foreground">
                  <ShieldAlert className="mt-0.5 size-3.5 shrink-0 text-warning" aria-hidden="true" />
                  <span className="line-clamp-2">{f.text}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-8 lg:grid-cols-[200px_minmax(0,1fr)]">
        <nav aria-label="Bagian laporan" className="hidden lg:block">
          <ul className="sticky top-20 space-y-0.5 text-sm">
            {SECTIONS.map((s) => (
              <li key={s.id}>
                <a href={`#${s.id}`} className="block rounded-md px-2.5 py-1.5 text-muted-foreground hover:bg-muted hover:text-foreground">
                  {s.title}
                </a>
              </li>
            ))}
          </ul>
        </nav>

        <div className="min-w-0 space-y-10">
          <Section id="ringkasan" title="1. Ringkasan Fundamental" badge={<SourceLabel kind="rule" />}>
            {fundamentalOk ? (
              <div className="space-y-4">
                <FindingList findings={by("summary")} />
                <DimensionTable dims={r.fundamental_score.dimensions} />
                <ul className="space-y-1 text-xs text-muted-foreground">
                  {r.fundamental_score.notes.map((n) => (
                    <li key={n}>· {n}</li>
                  ))}
                </ul>
              </div>
            ) : (
              <div className="space-y-4">
                <Notice tone="warning" icon={AlertTriangle}>
                  Ringkasan keseluruhan tidak diterbitkan karena data inti belum cukup. {r.fundamental_score.notes[r.fundamental_score.notes.length - 1]}
                </Notice>
                <DimensionTable dims={r.fundamental_score.dimensions} />
              </div>
            )}
          </Section>

          <Section id="rasio" title="Rasio fundamental" badge={<SourceLabel kind="measured" />}>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {(["npm", "roe", "roa", "der", "current_ratio", "revenue_growth", "eps", "operating_cash_flow", "free_cash_flow", "per", "pbv"] as const).map((k) => (
                <MetricCard key={k} metric={m[k]} currency={currency} />
              ))}
            </div>
          </Section>

          <Section id="profitabilitas" title="2. Profitabilitas" badge={<SourceLabel kind="rule" />}>
            <FindingList findings={by("profitability")} empty="Metrik profitabilitas belum dapat dinilai." />
          </Section>

          <Section id="pertumbuhan" title="3. Pertumbuhan" badge={<SourceLabel kind="rule" />} description={r.comparability.comparable ? `Dibandingkan dengan ${r.comparability.previous_label}.` : r.comparability.reason ?? undefined}>
            <div className="mb-3 grid gap-3 sm:grid-cols-2">
              <MetricCard metric={m.revenue_growth} currency={currency} compact />
              <MetricCard metric={m.net_income_growth} currency={currency} compact />
            </div>
            <FindingList findings={by("growth")} empty="Pertumbuhan belum dapat dinilai." />
          </Section>

          <Section id="utang" title="4. Utang dan Likuiditas" badge={<SourceLabel kind="rule" />}>
            <FindingList findings={by("leverage_liquidity")} empty={r.is_financial_sector ? "Sebagian metrik tidak diterapkan untuk sektor keuangan." : "Metrik utang dan likuiditas belum dapat dinilai."} />
          </Section>

          <Section id="arus-kas" title="5. Arus Kas" badge={<SourceLabel kind="rule" />}>
            <div className="mb-3 grid gap-3 sm:grid-cols-2">
              <MetricCard metric={m.cash_flow_quality} currency={currency} compact />
              <MetricCard metric={m.fcf_margin} currency={currency} compact />
            </div>
            <FindingList findings={by("cash_flow")} empty="Arus kas belum dapat dinilai." />
          </Section>

          <Section id="valuasi" title="6. Valuasi" badge={<SourceLabel kind="rule" />} description="Valuasi dinilai terpisah dari kualitas bisnis. Tidak ada data emiten sejenis atau estimasi nilai wajar.">
            <div className="mb-3 grid gap-3 sm:grid-cols-3">
              <MetricCard metric={m.per} currency={currency} compact />
              <MetricCard metric={m.pbv} currency={currency} compact />
              <MetricCard metric={m.bvps} currency={currency} compact />
            </div>
            <FindingList findings={by("valuation")} />
            <ul className="mt-3 space-y-1 text-xs text-muted-foreground">
              {r.valuation_score.notes.map((n) => (
                <li key={n}>· {n}</li>
              ))}
            </ul>
          </Section>

          <Section id="risiko" title="7. Risiko Utama" badge={<SourceLabel kind="rule" />}>
            <FindingList findings={risks} empty="Tidak ada sinyal risiko utama dari data yang tersedia. Ini tidak berarti tanpa risiko." />
          </Section>

          <Section id="data" title="8. Data yang Masih Dibutuhkan">
            {r.completeness.missing.length ? (
              <ul className="grid gap-2 sm:grid-cols-2">
                {r.completeness.missing.map((mf) => (
                  <li key={mf.field} className="rounded-md border bg-card px-3 py-2.5 text-sm">
                    <p className="font-medium">{mf.label}</p>
                    <p className="text-xs text-muted-foreground">Untuk: {mf.blocks.join(", ")}</p>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">Semua data inti sudah terisi.</p>
            )}
            {r.is_financial_sector && (
              <p className="mt-3 text-sm text-muted-foreground">
                Untuk sektor keuangan, metrik khusus (mis. CAR, NPL, LDR, NIM) belum didukung di versi ini.
              </p>
            )}
          </Section>

          <Section id="tren" title="Grafik Tren" description="Hanya dari data yang tersimpan: analisis lain untuk emiten ini dan data periode pembanding yang Anda masukkan.">
            {history.isLoading ? <Skeleton className="h-64" /> : <TrendCharts points={points} currency={currency} />}
          </Section>

          <Section id="insight" title="9. AI Insights">
            <InsightsPanel analysisId={rec.id} insight={rec.latest_insight} />
          </Section>

          <Card className="bg-muted/40 shadow-none">
            <CardHeader>
              <CardTitle className="text-sm">Penafian metodologi</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-xs leading-relaxed text-muted-foreground">
              <p>{r.disclaimer}</p>
              <p>
                Bobot skor fundamental (profitabilitas 30%, pertumbuhan 20%, leverage 20%, likuiditas 15%, arus kas 15%) dan ambang batasnya
                adalah heuristik MVP sementara yang dapat dikonfigurasi, bukan ambang investasi yang tervalidasi secara empiris.
              </p>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

export default function AnalysisReportPage() {
  const { id } = useParams();
  const q = useAnalysis(id);
  if (q.isLoading) {
    return (
      <div className="space-y-6" aria-busy="true" aria-label="Memuat laporan">
        <Skeleton className="h-9 w-64" />
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-40" />
          ))}
        </div>
        <Skeleton className="h-96" />
      </div>
    );
  }
  if (q.isError) {
    if (q.error instanceof ApiError && q.error.status === 404) {
      return (
        <EmptyState
          icon={FileSearch}
          title="Analisis tidak ditemukan"
          description="Analisis mungkin sudah dihapus atau bukan milik akun Anda."
          action={
            <Button asChild variant="outline">
              <Link to="/riwayat">Ke riwayat analisis</Link>
            </Button>
          }
        />
      );
    }
    return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  }
  if (!q.data) return null;
  return <Report rec={q.data} />;
}

