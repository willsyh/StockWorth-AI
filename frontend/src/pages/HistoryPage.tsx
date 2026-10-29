import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { ArrowDownWideNarrow, ArrowUpNarrowWide, ChevronLeft, ChevronRight, FilePlus2, History, Loader2, Search, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
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
import { EmptyState, ErrorState, PageHeader, errorMessage } from "@/components/ui/states";
import { ScoreChip } from "@/components/analysis/display";
import { useAnalyses, useDeleteAnalysis } from "@/hooks/queries";
import { formatDateTime, formatFixed } from "@/lib/format";
import type { AnalysisSummary } from "@/types/api";

const PAGE_SIZE = 20;

function DeleteButton({ a }: { a: AnalysisSummary }) {
  const del = useDeleteAnalysis();
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button variant="ghost" size="icon" aria-label={`Hapus analisis ${a.ticker} ${a.period_label}`} className="text-muted-foreground hover:text-negative">
          {del.isPending ? <Loader2 className="animate-spin" /> : <Trash2 />}
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogTitle>Hapus analisis {a.ticker}?</AlertDialogTitle>
        <AlertDialogDescription>
          Analisis {a.period_label} yang dibuat {formatDateTime(a.created_at)} akan dihapus permanen beserta insight-nya.
        </AlertDialogDescription>
        <AlertDialogFooter>
          <AlertDialogCancel>Batal</AlertDialogCancel>
          <AlertDialogAction
            onClick={() =>
              del.mutate(a.id, {
                onSuccess: () => toast.success("Analisis dihapus."),
                onError: (e) => toast.error(errorMessage(e)),
              })
            }
          >
            Hapus
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

export default function HistoryPage() {
  const { ticker } = useParams();
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");
  const [debouncedQ, setDebouncedQ] = useState(q);
  const period = params.get("period") ?? "all";
  const year = params.get("year") ?? "";
  const sort = (params.get("sort") as "asc" | "desc") ?? "desc";
  const page = Math.max(0, Number(params.get("page") ?? 0) || 0);

  useEffect(() => {
    setQ(params.get("q") ?? "");
  }, [params]);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q.trim()), 300);
    return () => clearTimeout(t);
  }, [q]);

  const update = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      if (v === null || v === "" || v === "all") next.delete(k);
      else next.set(k, v);
    }
    if (!("page" in patch)) next.delete("page");
    setParams(next, { replace: true });
  };

  useEffect(() => {
    if ((params.get("q") ?? "") !== debouncedQ) update({ q: debouncedQ || null });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedQ]);

  const yearNum = /^\d{4}$/.test(year) ? Number(year) : undefined;
  const list = useAnalyses({
    q: debouncedQ || undefined,
    ticker: ticker?.toUpperCase(),
    period: period === "all" ? undefined : period,
    fiscal_year: yearNum,
    sort,
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  });
  const items = list.data?.items ?? [];
  const total = list.data?.total ?? 0;
  const filtered = Boolean(debouncedQ || period !== "all" || yearNum);
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div>
      <PageHeader
        title={ticker ? `Riwayat ${ticker.toUpperCase()}` : "Riwayat analisis"}
        description={ticker ? "Semua analisis tersimpan untuk emiten ini." : "Semua analisis yang Anda simpan. Hanya Anda yang dapat melihatnya."}
        actions={
          <Button asChild>
            <Link to="/analisis/baru">
              <FilePlus2 /> Analisis baru
            </Link>
          </Button>
        }
      />

      <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-center">
        {!ticker && (
          <div className="relative flex-1 sm:max-w-xs">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cari kode atau nama emiten" aria-label="Cari kode atau nama emiten" className="pl-8" />
          </div>
        )}
        <div className="flex gap-2">
          <Select value={period} onValueChange={(v) => update({ period: v })}>
            <SelectTrigger className="w-36" aria-label="Filter periode">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Semua periode</SelectItem>
              <SelectItem value="FY">Tahunan (FY)</SelectItem>
              <SelectItem value="Q1">Q1</SelectItem>
              <SelectItem value="Q2">Q2</SelectItem>
              <SelectItem value="Q3">Q3</SelectItem>
              <SelectItem value="Q4">Q4</SelectItem>
            </SelectContent>
          </Select>
          <Input
            value={year}
            onChange={(e) => update({ year: e.target.value.replace(/\D/g, "").slice(0, 4) })}
            placeholder="Tahun"
            inputMode="numeric"
            aria-label="Filter tahun fiskal"
            className="w-24"
          />
          <Button
            variant="outline"
            onClick={() => update({ sort: sort === "desc" ? "asc" : "desc" })}
            aria-label={sort === "desc" ? "Urutkan dari terlama" : "Urutkan dari terbaru"}
          >
            {sort === "desc" ? <ArrowDownWideNarrow /> : <ArrowUpNarrowWide />}
            <span className="hidden sm:inline">{sort === "desc" ? "Terbaru" : "Terlama"}</span>
          </Button>
        </div>
      </div>

      {list.isError ? (
        <ErrorState error={list.error} onRetry={() => list.refetch()} />
      ) : list.isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-14" />
          ))}
        </div>
      ) : items.length === 0 ? (
        filtered ? (
          <EmptyState icon={Search} title="Tidak ada hasil" description="Tidak ada analisis yang cocok dengan pencarian atau filter ini." action={<Button variant="outline" onClick={() => { setQ(""); setParams({}, { replace: true }); }}>Hapus filter</Button>} />
        ) : (
          <EmptyState
            icon={History}
            title="Belum ada analisis tersimpan"
            description="Analisis yang Anda simpan akan muncul di sini."
            action={
              <Button asChild>
                <Link to="/analisis/baru">
                  <FilePlus2 /> Mulai analisis
                </Link>
              </Button>
            }
          />
        )
      ) : (
        <>
          {/* Desktop table */}
          <Card className="hidden md:block">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Emiten</TableHead>
                  <TableHead>Periode</TableHead>
                  <TableHead>Fundamental</TableHead>
                  <TableHead>Valuasi</TableHead>
                  <TableHead className="text-right">Kelengkapan</TableHead>
                  <TableHead>Dibuat</TableHead>
                  <TableHead className="w-12">
                    <span className="sr-only">Aksi</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((a) => (
                  <TableRow key={a.id}>
                    <TableCell>
                      <Link to={`/analisis/${a.id}`} className="font-medium hover:text-primary hover:underline">
                        {a.ticker}
                      </Link>
                      <p className="max-w-[220px] truncate text-xs text-muted-foreground">{a.company_name}</p>
                    </TableCell>
                    <TableCell className="whitespace-nowrap">{a.period_label}</TableCell>
                    <TableCell>
                      <ScoreChip score={a.fundamental_score} status={a.fundamental_status} label={a.fundamental_label} />
                    </TableCell>
                    <TableCell>
                      <ScoreChip score={a.valuation_score} status={a.valuation_status} />
                    </TableCell>
                    <TableCell className="tabular text-right">{formatFixed(a.completeness, 0)}%</TableCell>
                    <TableCell className="whitespace-nowrap text-xs text-muted-foreground">{formatDateTime(a.created_at)}</TableCell>
                    <TableCell>
                      <DeleteButton a={a} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Card>

          {/* Mobile list */}
          <ul className="space-y-2 md:hidden">
            {items.map((a) => (
              <li key={a.id}>
                <Card>
                  <CardContent className="flex items-start gap-3 p-4">
                    <Link to={`/analisis/${a.id}`} className="min-w-0 flex-1">
                      <p className="font-medium">
                        {a.ticker} <span className="text-sm font-normal text-muted-foreground">· {a.period_label}</span>
                      </p>
                      <p className="truncate text-xs text-muted-foreground">{a.company_name}</p>
                      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1">
                        <ScoreChip score={a.fundamental_score} status={a.fundamental_status} label={a.fundamental_label} />
                        <span className="text-xs text-muted-foreground">Data {formatFixed(a.completeness, 0)}%</span>
                      </div>
                      <p className="mt-1.5 text-xs text-muted-foreground">{formatDateTime(a.created_at)}</p>
                    </Link>
                    <DeleteButton a={a} />
                  </CardContent>
                </Card>
              </li>
            ))}
          </ul>

          <div className="mt-4 flex items-center justify-between text-sm text-muted-foreground">
            <span>
              {total} analisis · hal. {page + 1} dari {pages}
            </span>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" disabled={page === 0} onClick={() => update({ page: String(page - 1) })}>
                <ChevronLeft /> Sebelumnya
              </Button>
              <Button variant="outline" size="sm" disabled={page + 1 >= pages} onClick={() => update({ page: String(page + 1) })}>
                Berikutnya <ChevronRight />
              </Button>
            </div>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">* Skor sementara karena sebagian data belum tersedia.</p>
        </>
      )}
    </div>
  );
}
