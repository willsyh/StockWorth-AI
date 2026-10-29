import { Bot, Info, ListChecks, Loader2, RefreshCw, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Notice, errorMessage } from "@/components/ui/states";
import { useCreateInsight, useHealth } from "@/hooks/queries";
import { formatDateTime } from "@/lib/format";
import type { InsightRecord } from "@/types/api";
import { SourceLabel } from "./display";

function List({ title, items, empty }: { title: string; items: string[]; empty: string }) {
  return (
    <div>
      <h4 className="mb-1.5 text-sm font-semibold">{title}</h4>
      {items.length ? (
        <ul className="list-disc space-y-1 pl-5 text-sm leading-relaxed">
          {items.map((i, idx) => (
            <li key={idx}>{i}</li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">{empty}</p>
      )}
    </div>
  );
}

export function InsightsPanel({ analysisId, insight }: { analysisId: string; insight: InsightRecord | null | undefined }) {
  const health = useHealth();
  const mutation = useCreateInsight(analysisId);
  const aiConfigured = health.data?.ai.configured;

  const run = () =>
    mutation.mutate(undefined, {
      onSuccess: (r) => toast.success(r.source === "ai" ? "Insight AI dibuat." : "Insight berbasis aturan dibuat (AI tidak digunakan)."),
      onError: (e) => toast.error(errorMessage(e)),
    });

  const isAi = insight?.source === "ai";

  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-3 space-y-0">
        <div className="flex flex-wrap items-center gap-2">
          {insight ? <SourceLabel kind={isAi ? "ai" : "rule"} /> : null}
          {insight && (
            <span className="text-xs text-muted-foreground">
              {formatDateTime(insight.created_at)}
              {isAi && insight.model ? ` · ${insight.provider} ${insight.model}` : ""}
            </span>
          )}
        </div>
        <Button size="sm" variant={insight ? "outline" : "default"} onClick={run} disabled={mutation.isPending}>
          {mutation.isPending ? <Loader2 className="animate-spin" /> : insight ? <RefreshCw /> : aiConfigured ? <Sparkles /> : <ListChecks />}
          {mutation.isPending
            ? aiConfigured
              ? "AI sedang menganalisis…"
              : "Menyusun…"
            : insight
              ? "Buat ulang"
              : aiConfigured
                ? "Buat insight AI"
                : "Buat insight berbasis aturan"}
        </Button>
      </CardHeader>
      <CardContent className="space-y-5">
        {!insight && !mutation.isPending && (
          <div className="flex gap-3 rounded-md border border-dashed p-4">
            <Bot className="mt-0.5 size-5 shrink-0 text-muted-foreground" aria-hidden="true" />
            <div className="text-sm text-muted-foreground">
              {aiConfigured ? (
                <p>
                  AI akan menjelaskan metrik yang sudah dihitung. AI tidak menghitung ulang angka, tidak mengakses data pasar
                  langsung, dan tidak memberi rekomendasi beli/jual.
                </p>
              ) : (
                <p>
                  Penyedia AI belum dikonfigurasi di server. Anda tetap bisa membuat ringkasan berbasis aturan yang deterministik;
                  hasilnya akan diberi label jelas sebagai bukan hasil AI.
                </p>
              )}
            </div>
          </div>
        )}
        {mutation.isPending && !insight && <p className="text-sm text-muted-foreground">Ini dapat memakan waktu hingga satu menit.</p>}
        {insight && (
          <>
            {!isAi && (
              <Notice tone="neutral" icon={Info}>
                Ringkasan ini <span className="font-medium">bukan hasil AI</span>. Disusun dari aturan deterministik atas metrik yang
                dihitung.
                {insight.fallback_reason && <> Alasan: {insight.fallback_reason}</>}
              </Notice>
            )}
            {isAi && (
              <Notice tone="info" icon={Sparkles}>
                Dihasilkan AI dari metrik terukur di laporan ini. AI dapat keliru; angka di kartu metrik adalah acuan resmi.
              </Notice>
            )}
            <div>
              <h4 className="mb-1.5 text-sm font-semibold">Ringkasan</h4>
              <p className="text-sm leading-relaxed">{insight.content.summary}</p>
            </div>
            <div className="grid gap-5 md:grid-cols-2">
              <List title="Kekuatan" items={insight.content.strengths} empty="Tidak ada kekuatan menonjol yang didukung data." />
              <List title="Risiko" items={insight.content.risks} empty="Tidak ada risiko menonjol dari data yang tersedia." />
              <List title="Observasi valuasi" items={insight.content.valuation_observations} empty="Valuasi belum dapat diamati." />
              <List title="Informasi yang belum tersedia" items={insight.content.missing_information} empty="Tidak ada data inti yang kurang." />
            </div>
            <div>
              <h4 className="mb-1.5 text-sm font-semibold">Kesimpulan</h4>
              <p className="text-sm leading-relaxed">{insight.content.conclusion}</p>
            </div>
            <List title="Keterbatasan" items={insight.content.limitations} empty="—" />
          </>
        )}
      </CardContent>
    </Card>
  );
}
