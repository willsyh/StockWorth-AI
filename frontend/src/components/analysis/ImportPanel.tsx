import { useRef, useState, type DragEvent } from "react";
import { AlertTriangle, CheckCircle2, Download, FileUp, Loader2, MinusCircle, Upload, XCircle } from "lucide-react";
import { useMutation } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Notice, errorMessage } from "@/components/ui/states";
import { api } from "@/lib/api";
import { formatNumber } from "@/lib/format";
import { UNITS } from "@/lib/fields";
import { cn } from "@/lib/utils";
import type { ImportPreview, ImportRow } from "@/types/api";

export type ImportKind = "csv" | "excel" | "pdf";

const KINDS: Record<ImportKind, { title: string; exts: string[]; accept: string; maxMb: number }> = {
  csv: { title: "Unggah CSV", exts: ["csv"], accept: ".csv,text/csv", maxMb: 2 },
  excel: {
    title: "Unggah Excel (XLSX / XLS)",
    exts: ["xlsx", "xls"],
    accept:
      ".xlsx,.xls,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel",
    maxMb: 2,
  },
  pdf: { title: "Unggah PDF laporan keuangan", exts: ["pdf"], accept: ".pdf,application/pdf", maxMb: 20 },
};

function RowStatus({ status }: { status: ImportRow["status"] }) {
  const meta = {
    ok: { icon: CheckCircle2, text: "OK", variant: "positive" as const },
    warning: { icon: AlertTriangle, text: "Periksa", variant: "warning" as const },
    error: { icon: XCircle, text: "Galat", variant: "negative" as const },
    ignored: { icon: MinusCircle, text: "Diabaikan", variant: "neutral" as const },
  }[status];
  return (
    <Badge variant={meta.variant}>
      <meta.icon aria-hidden="true" /> {meta.text}
    </Badge>
  );
}

export function ImportPanel({
  kind,
  onApply,
  formUnit,
}: {
  kind: ImportKind;
  onApply: (preview: ImportPreview) => void;
  formUnit: string;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [clientError, setClientError] = useState<string | null>(null);
  const mutation = useMutation({ mutationFn: (f: File) => api.importFile(f) });
  const preview = mutation.data;
  const cfg = KINDS[kind];

  const handleFile = (file: File | undefined) => {
    setClientError(null);
    mutation.reset();
    if (!file) return;
    const ext = file.name.toLowerCase().split(".").pop();
    if (!ext || !cfg.exts.includes(ext)) {
      setClientError(`Pilih berkas ${cfg.exts.map((x) => `.${x}`).join(" atau ")}.`);
      return;
    }
    if (file.size > cfg.maxMb * 1024 * 1024) {
      setClientError(`Ukuran berkas melebihi ${cfg.maxMb} MB.`);
      return;
    }
    mutation.mutate(file);
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    handleFile(e.dataTransfer.files?.[0]);
  };

  const usable = preview && Object.keys(preview.current).length + Object.keys(preview.previous).length > 0;
  const unitLabel = (u: string | null) => UNITS.find((x) => x.value === u)?.label.toLowerCase() ?? u;

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>{cfg.title}</CardTitle>
          <CardDescription>
            {kind === "pdf"
              ? "Gunakan PDF asli (berbasis teks) dari situs BEI atau emiten. Angka dibaca otomatis dari laporan posisi keuangan, laba rugi, dan arus kas, lalu wajib Anda periksa di pratinjau. Berkas tidak disimpan."
              : "Gunakan templat agar kolom terbaca dengan benar. Berkas hanya dibaca untuk pratinjau dan tidak disimpan. Formula dan makro tidak dijalankan."}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {kind === "pdf" && (
            <Notice tone="neutral" icon={AlertTriangle}>
              <ul className="list-disc space-y-0.5 pl-4">
                <li>PDF hasil scan (gambar) belum bisa dibaca karena OCR belum didukung.</li>
                <li>Jumlah saham biasanya ada di catatan laporan dan tidak dibaca otomatis; isi manual di langkah berikutnya.</li>
                <li>Periksa urutan kolom (tahun berjalan vs pembanding), tanda negatif, dan satuan.</li>
              </ul>
            </Notice>
          )}
          <div className={cn("flex flex-wrap gap-2", kind === "pdf" && "hidden")}>
            <Button asChild variant="outline" size="sm">
              <a href={api.templateUrl("xlsx")} download>
                <Download /> Templat XLSX
              </a>
            </Button>
            <Button asChild variant="outline" size="sm">
              <a href={api.templateUrl("csv")} download>
                <Download /> Templat CSV
              </a>
            </Button>
          </div>
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={cn(
              "flex flex-col items-center justify-center rounded-lg border-2 border-dashed px-6 py-10 text-center transition-colors",
              dragging ? "border-primary bg-accent" : "border-border",
            )}
          >
            <FileUp className="mb-3 size-6 text-muted-foreground" aria-hidden="true" />
            <p className="text-sm font-medium">Seret berkas ke sini, atau</p>
            <Button type="button" variant="secondary" size="sm" className="mt-3" onClick={() => inputRef.current?.click()} disabled={mutation.isPending}>
              {mutation.isPending ? <Loader2 className="animate-spin" /> : <Upload />}
              {mutation.isPending ? "Membaca berkas…" : "Pilih berkas"}
            </Button>
            <input
              ref={inputRef}
              type="file"
              accept={cfg.accept}
              className="sr-only"
              aria-label={cfg.title}
              onChange={(e) => {
                handleFile(e.target.files?.[0]);
                e.target.value = "";
              }}
            />
            <p className="mt-3 text-xs text-muted-foreground">
              Maksimal {cfg.maxMb} MB · {cfg.exts.map((x) => `.${x}`).join(", ")}
            </p>
          </div>
          {(clientError || mutation.isError) && (
            <Notice tone="negative" icon={XCircle}>
              {clientError ?? errorMessage(mutation.error)}
            </Notice>
          )}
        </CardContent>
      </Card>

      {preview && (
        <Card>
          <CardHeader>
            <CardTitle>Pratinjau: {preview.file_name}</CardTitle>
            <CardDescription>
              {preview.sheet ? `Sheet "${preview.sheet}" · ` : ""}
              {Object.keys(preview.current).length} nilai periode berjalan, {Object.keys(preview.previous).length} nilai pembanding.
              {preview.unit && ` Satuan berkas: ${unitLabel(preview.unit)}.`}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {preview.unit && preview.unit !== formUnit && (
              <Notice tone="warning" icon={AlertTriangle}>
                Satuan di berkas ({unitLabel(preview.unit)}) berbeda dengan pilihan Anda di langkah 1 ({unitLabel(formUnit)}).
                Satuan formulir akan disesuaikan dengan berkas.
              </Notice>
            )}
            {preview.errors.length > 0 && (
              <Notice tone="negative" icon={XCircle}>
                <p className="font-medium">{preview.errors.length} baris bermasalah dan tidak digunakan:</p>
                <ul className="mt-1 list-disc space-y-0.5 pl-4">
                  {preview.errors.slice(0, 8).map((e) => (
                    <li key={e}>{e}</li>
                  ))}
                </ul>
              </Notice>
            )}
            {preview.warnings.length > 0 && (
              <Notice tone="warning" icon={AlertTriangle}>
                <p className="font-medium">Perlu diperiksa:</p>
                <ul className="mt-1 list-disc space-y-0.5 pl-4">
                  {preview.warnings.slice(0, 8).map((w) => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
              </Notice>
            )}
            <div className="max-h-[420px] overflow-auto rounded-md border">
              <Table>
                <TableHeader className="sticky top-0 bg-card">
                  <TableRow>
                    <TableHead className="w-14">{kind === "pdf" ? "Hal." : "Baris"}</TableHead>
                    <TableHead>Akun</TableHead>
                    <TableHead className="text-right">Berjalan</TableHead>
                    <TableHead className="text-right">Pembanding</TableHead>
                    <TableHead>Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {preview.rows.map((r) => (
                    <TableRow key={`${r.row}-${r.code}`} className={cn(r.status === "error" && "bg-negative-soft/40")}>
                      <TableCell className="tabular text-muted-foreground">{r.row}</TableCell>
                      <TableCell>
                        <p className="font-medium">{r.label ?? r.code}</p>
                        {r.messages.length > 0 && <p className="mt-0.5 text-xs text-muted-foreground">{r.messages.join(" ")}</p>}
                      </TableCell>
                      <TableCell className="tabular text-right">{r.current !== null ? formatNumber(r.current) : "—"}</TableCell>
                      <TableCell className="tabular text-right">{r.previous !== null ? formatNumber(r.previous) : "—"}</TableCell>
                      <TableCell>
                        <RowStatus status={r.status} />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-xs text-muted-foreground">Anda masih bisa mengubah setiap nilai di langkah berikutnya.</p>
              <Button type="button" onClick={() => onApply(preview)} disabled={!usable}>
                Gunakan data ini
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
