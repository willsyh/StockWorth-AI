import { Link } from "react-router-dom";
import { ArrowRight, Building2, Calculator, FilePlus2, FileSpreadsheet, FileText, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/misc";
import { ErrorState, PageHeader } from "@/components/ui/states";
import { ScoreChip, ScoreBar } from "@/components/analysis/display";
import { useAnalyses, useHealth, useStats } from "@/hooks/queries";
import { useAuth } from "@/app/auth";
import { formatDate, formatDateTime, formatFixed } from "@/lib/format";
import type { AnalysisSummary } from "@/types/api";

function StatCard({ label, value, hint, loading }: { label: string; value: string; hint?: string; loading?: boolean }) {
  return (
    <Card>
      <CardContent className="p-5">
        <p className="text-xs font-medium text-muted-foreground">{label}</p>
        {loading ? <Skeleton className="mt-2 h-7 w-16" /> : <p className="tabular mt-1.5 text-2xl font-semibold tracking-tight">{value}</p>}
        {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
      </CardContent>
    </Card>
  );
}

function Onboarding() {
  const steps = [
    { icon: Building2, title: "Isi data emiten", text: "Kode saham, periode laporan, satuan, dan mata uang." },
    { icon: FileSpreadsheet, title: "Masukkan laporan keuangan", text: "Ketik manual atau impor dari templat CSV/XLSX." },
    { icon: Calculator, title: "Tinjau hasil", text: "Rasio, skor transparan, risiko, dan data yang masih kurang." },
  ];
  return (
    <Card className="overflow-hidden">
      <div className="grid gap-0 lg:grid-cols-[1.1fr_1fr]">
        <div className="p-6 sm:p-8">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-accent px-2.5 py-1 text-xs font-medium text-accent-foreground">
            <Sparkles className="size-3.5" aria-hidden="true" /> Mulai di sini
          </span>
          <h2 className="mt-4 text-xl font-semibold tracking-tight">Buat analisis fundamental pertama Anda</h2>
          <p className="mt-2 max-w-md text-sm leading-relaxed text-muted-foreground">
            StockWorth AI menghitung rasio dari laporan keuangan yang Anda masukkan, memisahkan kualitas bisnis dari valuasi,
            dan menunjukkan dengan jelas data mana yang masih kurang.
          </p>
          <Button asChild className="mt-6">
            <Link to="/analisis/baru">
              <FilePlus2 /> Mulai analisis pertama
            </Link>
          </Button>
        </div>
        <ol className="space-y-4 border-t bg-muted/40 p-6 sm:p-8 lg:border-l lg:border-t-0">
          {steps.map((s, i) => (
            <li key={s.title} className="flex gap-3">
              <span className="flex size-8 shrink-0 items-center justify-center rounded-full border bg-card text-sm font-semibold">{i + 1}</span>
              <div>
                <p className="flex items-center gap-1.5 text-sm font-medium">
                  <s.icon className="size-4 text-muted-foreground" aria-hidden="true" /> {s.title}
                </p>
                <p className="mt-0.5 text-sm text-muted-foreground">{s.text}</p>
              </div>
            </li>
          ))}
        </ol>
      </div>
    </Card>
  );
}

function LatestSummaryCard({ a }: { a: AnalysisSummary }) {
  return (
    <Link
      to={`/analisis/${a.id}`}
      className="group flex flex-col rounded-lg border bg-card p-5 shadow-card transition-colors hover:border-primary/40"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-semibold">{a.ticker}</p>
          <p className="truncate text-xs text-muted-foreground">{a.company_name}</p>
        </div>
        <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-xs font-medium text-muted-foreground">{a.period_label}</span>
      </div>
      <div className="mt-4 space-y-3">
        <div>
          <div className="mb-1.5 flex items-center justify-between text-xs">
            <span className="text-muted-foreground">Fundamental</span>
            <ScoreChip score={a.fundamental_score} status={a.fundamental_status} label={a.fundamental_label} />
          </div>
          <ScoreBar score={a.fundamental_score} />
        </div>
        <div className="flex items-center justify-between text-xs">
          <span className="text-muted-foreground">Valuasi</span>
          <ScoreChip score={a.valuation_score} status={a.valuation_status} />
        </div>
        <div className="flex items-center justify-between text-xs">
          <span className="text-muted-foreground">Kelengkapan data</span>
          <span className="tabular font-medium">{formatFixed(a.completeness, 0)}%</span>
        </div>
      </div>
      <p className="mt-4 flex items-center gap-1 text-xs font-medium text-primary">
        Buka laporan <ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
      </p>
    </Link>
  );
}

export default function DashboardPage() {
  const auth = useAuth();
  const stats = useStats();
  const recent = useAnalyses({ limit: 6, sort: "desc" });
  const health = useHealth();

  const items = recent.data?.items ?? [];
  const isEmpty = recent.isSuccess && items.length === 0;
  const name = auth.user?.email?.split("@")[0];

  return (
    <div>
      <PageHeader
        title={name ? `Selamat datang, ${name}` : "Selamat datang"}
        description="Ringkasan analisis fundamental yang telah Anda simpan."
        actions={
          !isEmpty && (
            <Button asChild>
              <Link to="/analisis/baru">
                <FilePlus2 /> Analisis baru
              </Link>
            </Button>
          )
        }
      />

      {recent.isError ? (
        <ErrorState error={recent.error} onRetry={() => recent.refetch()} />
      ) : isEmpty ? (
        <Onboarding />
      ) : (
        <div className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label="Analisis tersimpan" value={String(stats.data?.total_analyses ?? 0)} loading={stats.isLoading} />
            <StatCard label="Emiten dianalisis" value={String(stats.data?.companies ?? 0)} loading={stats.isLoading} />
            <StatCard
              label="Analisis terakhir"
              value={items[0] ? formatDate(items[0].created_at) : "—"}
              hint={items[0] ? `${items[0].ticker} · ${items[0].period_label}` : undefined}
              loading={recent.isLoading}
            />
            <StatCard
              label="Insight"
              value={health.data?.ai.configured ? "AI aktif" : "Berbasis aturan"}
              hint={health.data?.ai.configured ? "Penyedia AI dikonfigurasi di server" : "AI belum dikonfigurasi"}
              loading={health.isLoading}
            />
          </div>

          <section aria-labelledby="latest-title">
            <h2 id="latest-title" className="mb-3 text-base font-semibold tracking-tight">
              Ringkasan terbaru
            </h2>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {recent.isLoading
                ? Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-52" />)
                : items.slice(0, 3).map((a) => <LatestSummaryCard key={a.id} a={a} />)}
            </div>
          </section>

          <Card>
            <CardHeader className="flex-row items-center justify-between space-y-0">
              <div>
                <CardTitle>Analisis terbaru</CardTitle>
                <CardDescription>Enam analisis yang terakhir disimpan.</CardDescription>
              </div>
              <Button asChild variant="ghost" size="sm">
                <Link to="/riwayat">
                  Lihat semua <ArrowRight />
                </Link>
              </Button>
            </CardHeader>
            <CardContent className="p-0">
              {recent.isLoading ? (
                <div className="space-y-2 p-5">
                  {Array.from({ length: 4 }).map((_, i) => (
                    <Skeleton key={i} className="h-10" />
                  ))}
                </div>
              ) : (
                <ul className="divide-y">
                  {items.map((a) => (
                    <li key={a.id}>
                      <Link to={`/analisis/${a.id}`} className="flex items-center gap-4 px-5 py-3 transition-colors hover:bg-muted/40">
                        <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-muted text-xs font-semibold">
                          {a.ticker.slice(0, 2)}
                        </span>
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-medium">
                            {a.ticker} <span className="font-normal text-muted-foreground">· {a.company_name}</span>
                          </p>
                          <p className="text-xs text-muted-foreground">
                            {a.period_label} · {formatDateTime(a.created_at)}
                            {a.source_method !== "manual" && (
                              <span className="ml-1 inline-flex items-center gap-0.5">
                                · <FileText className="size-3" aria-hidden="true" /> {a.source_method.toUpperCase()}
                              </span>
                            )}
                          </p>
                        </div>
                        <ScoreChip score={a.fundamental_score} status={a.fundamental_status} label={a.fundamental_label} />
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
          <p className="text-xs text-muted-foreground">* Skor sementara karena sebagian data belum tersedia.</p>
        </div>
      )}
    </div>
  );
}
