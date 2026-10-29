import { AlertTriangle, CheckCircle2, CircleMinus, Loader2, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Notice, errorMessage } from "@/components/ui/states";
import { Skeleton } from "@/components/ui/misc";
import { ALL_FIELDS, FIELD_META, PREVIOUS_FIELDS, UNITS, periodLabel } from "@/lib/fields";
import { formatFixed, formatMoney, formatNumber } from "@/lib/format";
import { ApiError } from "@/lib/api";
import { fieldPathLabel } from "@/schemas/analysisForm";
import { cn } from "@/lib/utils";
import type { AnalysisInput, AnalysisResult } from "@/types/api";

interface Props {
  input: AnalysisInput;
  result: AnalysisResult | undefined;
  loading: boolean;
  error: unknown;
}

export function ReviewStep({ input, result, loading, error }: Props) {
  const { statement, current, previous, company, market, source } = input;
  const unitLabel = UNITS.find((u) => u.value === statement.unit)?.label ?? statement.unit;
  const warningsByField = new Map<string, string[]>();
  for (const i of result?.issues ?? []) {
    if (!i.field) continue;
    warningsByField.set(i.field, [...(warningsByField.get(i.field) ?? []), i.message]);
  }
  const blockedBy = new Map<string, string[]>();
  for (const m of result?.completeness.missing ?? []) blockedBy.set(m.field, m.blocks);
  const generalIssues = (result?.issues ?? []).filter((i) => !i.field?.startsWith("current.") && !i.field?.startsWith("previous."));

  const okCount = result ? Object.values(result.metrics).filter((m) => m.status === "ok").length : 0;
  const totalMetrics = result ? Object.keys(result.metrics).length : 0;

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader>
          <CardTitle>Ringkasan input</CardTitle>
          <CardDescription>Periksa kembali sebelum menyimpan. Nilai keuangan dalam {unitLabel.toLowerCase()} {statement.currency}.</CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <dt className="text-xs text-muted-foreground">Emiten</dt>
              <dd className="font-medium">
                {company.ticker} · {company.name}
              </dd>
              <dd className="mt-0.5">
                <Badge variant="warning">Belum diverifikasi</Badge>
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Periode</dt>
              <dd className="font-medium">{periodLabel(statement.fiscal_year, statement.period, statement.basis)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Harga saham</dt>
              <dd className="font-medium">
                {market.share_price ? `${formatMoney(market.share_price)} (${market.share_price_date})` : "Tidak diisi"}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Sumber data</dt>
              <dd className="font-medium">
                {source.method === "manual" ? "Input manual" : `${source.method.toUpperCase()} · ${source.file_name}`}
              </dd>
              {source.edited_after_import.length > 0 && (
                <dd className="text-xs text-warning">{source.edited_after_import.length} nilai diubah setelah impor</dd>
              )}
            </div>
          </dl>
        </CardContent>
      </Card>

      {error ? (
        <Notice tone="negative" icon={XCircle}>
          <p className="font-medium">{errorMessage(error)}</p>
          {error instanceof ApiError && error.details.length > 0 && (
            <ul className="mt-1 list-disc space-y-0.5 pl-4">
              {error.details.map((d, i) => (
                <li key={i}>
                  <span className="font-medium">{fieldPathLabel(d.field)}:</span> {d.message}
                </li>
              ))}
            </ul>
          )}
        </Notice>
      ) : loading || !result ? (
        <div className="space-y-3" aria-busy="true">
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" aria-hidden="true" /> Menghitung pratinjau di server…
          </p>
          <Skeleton className="h-24" />
          <Skeleton className="h-64" />
        </div>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <Card>
              <CardContent className="p-5">
                <p className="text-xs text-muted-foreground">Metrik dapat dihitung</p>
                <p className="tabular mt-1 text-2xl font-semibold">
                  {okCount}
                  <span className="text-base font-normal text-muted-foreground"> / {totalMetrics}</span>
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-5">
                <p className="text-xs text-muted-foreground">Kelengkapan data</p>
                <p className="tabular mt-1 text-2xl font-semibold">{formatFixed(result.completeness.percent, 0)}%</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-5">
                <p className="text-xs text-muted-foreground">Peringatan</p>
                <p className="tabular mt-1 text-2xl font-semibold">{result.issues.length}</p>
              </CardContent>
            </Card>
          </div>

          {generalIssues.length > 0 && (
            <Notice tone="warning" icon={AlertTriangle}>
              <ul className="space-y-1">
                {generalIssues.map((i) => (
                  <li key={i.message}>
                    <span className="font-medium">{fieldPathLabel(i.field)}:</span> {i.message}
                  </li>
                ))}
              </ul>
            </Notice>
          )}

          <Card>
            <CardHeader>
              <CardTitle>Tabel tinjauan</CardTitle>
              <CardDescription>
                Kolom kosong bersifat opsional, tetapi beberapa metrik tidak dapat dihitung tanpanya. Nilai kosong tidak pernah
                dianggap nol.
              </CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Akun</TableHead>
                    <TableHead className="text-right">Berjalan</TableHead>
                    {previous && <TableHead className="text-right">Pembanding</TableHead>}
                    <TableHead>Catatan</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {ALL_FIELDS.map((f) => {
                    const meta = FIELD_META[f];
                    const v = current[f];
                    const pv = previous?.values[f];
                    const warns = [...(warningsByField.get(`current.${f}`) ?? [])];
                    const isMissing = v === undefined || v === null;
                    const blocks = blockedBy.get(f);
                    const ref = source.cell_refs[`current.${f}`];
                    const edited = source.edited_after_import.includes(`current.${f}`);
                    return (
                      <TableRow key={f} className={cn(warns.length > 0 && "bg-warning-soft/40")}>
                        <TableCell>
                          <p className="font-medium">{meta.label}</p>
                          {ref && (
                            <p className="text-[11px] text-muted-foreground">
                              Sumber: {ref}
                              {edited && <span className="text-warning"> · diubah</span>}
                            </p>
                          )}
                        </TableCell>
                        <TableCell className="tabular text-right">
                          {isMissing ? <span className="text-muted-foreground">Kosong</span> : formatNumber(v)}
                        </TableCell>
                        {previous && (
                          <TableCell className="tabular text-right">
                            {PREVIOUS_FIELDS.includes(f) ? (pv === undefined || pv === null ? <span className="text-muted-foreground">Kosong</span> : formatNumber(pv)) : <span className="text-muted-foreground">n/a</span>}
                          </TableCell>
                        )}
                        <TableCell className="max-w-sm text-xs">
                          {warns.length > 0 ? (
                            <span className="flex gap-1.5 text-warning">
                              <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
                              {warns.join(" ")}
                            </span>
                          ) : isMissing ? (
                            <span className="flex gap-1.5 text-muted-foreground">
                              <CircleMinus className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
                              {blocks ? `Opsional. Tanpa ini: ${blocks.join(", ")} tidak dihitung.` : `Opsional. Dipakai untuk: ${meta.usedFor.join(", ")}.`}
                            </span>
                          ) : (
                            <span className="flex gap-1.5 text-positive">
                              <CheckCircle2 className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" /> Terisi
                            </span>
                          )}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          {result.completeness.missing.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Metrik yang belum dapat dihitung</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="grid gap-2 text-sm sm:grid-cols-2">
                  {result.completeness.missing.map((m) => (
                    <li key={m.field} className="rounded-md border px-3 py-2">
                      <p className="font-medium">{m.label}</p>
                      <p className="text-xs text-muted-foreground">Dibutuhkan untuk: {m.blocks.join(", ")}</p>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
