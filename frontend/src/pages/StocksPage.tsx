import { useMemo } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, FilePlus2, LineChart } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/misc";
import { EmptyState, ErrorState, PageHeader } from "@/components/ui/states";
import { ScoreChip } from "@/components/analysis/display";
import { useAnalyses } from "@/hooks/queries";
import { sectorLabel } from "@/lib/fields";
import { formatDate } from "@/lib/format";
import type { AnalysisSummary } from "@/types/api";

interface CompanyGroup {
  ticker: string;
  name: string;
  sector: AnalysisSummary["sector"];
  count: number;
  latest: AnalysisSummary;
  periods: string[];
}

export default function StocksPage() {
  const list = useAnalyses({ limit: 200, sort: "desc" });

  const groups = useMemo<CompanyGroup[]>(() => {
    const map = new Map<string, CompanyGroup>();
    for (const a of list.data?.items ?? []) {
      const g = map.get(a.ticker);
      if (!g) {
        map.set(a.ticker, { ticker: a.ticker, name: a.company_name, sector: a.sector, count: 1, latest: a, periods: [a.period_label] });
      } else {
        g.count++;
        if (!g.periods.includes(a.period_label)) g.periods.push(a.period_label);
      }
    }
    return [...map.values()].sort((a, b) => a.ticker.localeCompare(b.ticker));
  }, [list.data]);

  return (
    <div>
      <PageHeader
        title="Analisis saham"
        description="Emiten yang pernah Anda analisis, dikelompokkan per kode saham. Metadata emiten diisi pengguna dan belum diverifikasi."
        actions={
          <Button asChild>
            <Link to="/analisis/baru">
              <FilePlus2 /> Analisis baru
            </Link>
          </Button>
        }
      />
      {list.isError ? (
        <ErrorState error={list.error} onRetry={() => list.refetch()} />
      ) : list.isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-44" />
          ))}
        </div>
      ) : groups.length === 0 ? (
        <EmptyState
          icon={LineChart}
          title="Belum ada emiten yang dianalisis"
          description="Setelah Anda menyimpan analisis, emiten akan muncul di sini bersama riwayat periodenya."
          action={
            <Button asChild>
              <Link to="/analisis/baru">Mulai analisis</Link>
            </Button>
          }
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {groups.map((g) => (
            <Card key={g.ticker} className="flex flex-col">
              <CardContent className="flex flex-1 flex-col p-5">
                <div className="flex items-start gap-3">
                  <span className="flex size-10 shrink-0 items-center justify-center rounded-md bg-muted text-sm font-semibold">{g.ticker.slice(0, 2)}</span>
                  <div className="min-w-0">
                    <p className="font-semibold">{g.ticker}</p>
                    <p className="truncate text-sm text-muted-foreground">{g.name}</p>
                    <p className="text-xs text-muted-foreground">{sectorLabel(g.sector)}</p>
                  </div>
                </div>
                <dl className="mt-4 grid grid-cols-2 gap-3 text-xs">
                  <div>
                    <dt className="text-muted-foreground">Skor terbaru</dt>
                    <dd className="mt-1">
                      <ScoreChip score={g.latest.fundamental_score} status={g.latest.fundamental_status} label={g.latest.fundamental_label} />
                    </dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">Analisis</dt>
                    <dd className="mt-1 font-medium">
                      {g.count} · {g.periods.slice(0, 3).join(", ")}
                      {g.periods.length > 3 ? "…" : ""}
                    </dd>
                  </div>
                </dl>
                <p className="mt-3 text-xs text-muted-foreground">Terakhir {formatDate(g.latest.created_at)} · {g.latest.period_label}</p>
                <div className="mt-auto flex gap-2 pt-4">
                  <Button asChild size="sm" variant="outline" className="flex-1">
                    <Link to={`/saham/${g.ticker}`}>Riwayat</Link>
                  </Button>
                  <Button asChild size="sm" className="flex-1">
                    <Link to={`/analisis/${g.latest.id}`}>
                      Laporan terbaru <ArrowRight />
                    </Link>
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
