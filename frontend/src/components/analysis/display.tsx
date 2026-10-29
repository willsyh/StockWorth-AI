import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2, CircleMinus, Info, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { InfoTip } from "@/components/ui/tooltip";
import { Progress } from "@/components/ui/misc";
import { formatFixed, formatMetric } from "@/lib/format";
import { METRIC_HELP } from "@/lib/fields";
import { cn } from "@/lib/utils";
import type { Currency, MetricResult, ScoreResult, Severity } from "@/types/api";

export function scoreTone(score: number | null | undefined): "positive" | "neutral" | "warning" | "negative" {
  if (score === null || score === undefined) return "neutral";
  if (score >= 70) return "positive";
  if (score >= 40) return "neutral";
  if (score >= 25) return "warning";
  return "negative";
}

const STATUS_TEXT: Record<ScoreResult["status"], string> = {
  complete: "Cakupan lengkap",
  provisional: "Sementara",
  insufficient: "Data belum cukup",
  unavailable: "Belum tersedia",
};

export function ScoreStatusBadge({ status }: { status: ScoreResult["status"] }) {
  const variant = status === "complete" ? "positive" : status === "provisional" ? "warning" : "neutral";
  return <Badge variant={variant}>{STATUS_TEXT[status]}</Badge>;
}

/** Compact score chip used in lists: number + text, never color alone. */
export function ScoreChip({ score, status, label }: { score: number | null; status: ScoreResult["status"]; label?: string | null }) {
  if (score === null) {
    return <span className="text-xs text-muted-foreground">{status === "insufficient" ? "Data belum cukup" : "—"}</span>;
  }
  const tone = scoreTone(score);
  const toneCls = {
    positive: "bg-positive-soft text-positive",
    neutral: "bg-neutral-soft text-foreground",
    warning: "bg-warning-soft text-warning",
    negative: "bg-negative-soft text-negative",
  }[tone];
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
      <span className={cn("tabular rounded px-1.5 py-0.5 text-xs font-semibold", toneCls)}>{formatFixed(score, 0)}</span>
      {label && <span className="text-xs text-muted-foreground">{label}{status === "provisional" ? "*" : ""}</span>}
    </span>
  );
}

export function ScoreBar({ score }: { score: number | null }) {
  const tone = scoreTone(score);
  const cls = { positive: "bg-positive", neutral: "bg-neutral", warning: "bg-warning", negative: "bg-negative" }[tone];
  return <Progress value={score ?? 0} indicatorClassName={cls} aria-label={score === null ? "Belum ada skor" : `Skor ${formatFixed(score, 0)} dari 100`} />;
}

const SEVERITY_META: Record<Severity, { icon: typeof Info; cls: string; label: string }> = {
  positive: { icon: CheckCircle2, cls: "text-positive", label: "Positif" },
  negative: { icon: XCircle, cls: "text-negative", label: "Negatif" },
  warning: { icon: AlertTriangle, cls: "text-warning", label: "Perhatian" },
  neutral: { icon: Info, cls: "text-muted-foreground", label: "Info" },
};

export function SeverityIcon({ severity }: { severity: Severity }) {
  const m = SEVERITY_META[severity];
  return (
    <span className={cn("mt-0.5 shrink-0", m.cls)} title={m.label}>
      <m.icon className="size-4" aria-hidden="true" />
      <span className="sr-only">{m.label}: </span>
    </span>
  );
}

export function MetricCard({ metric, currency, compact }: { metric: MetricResult | undefined; currency: Currency; compact?: boolean }) {
  if (!metric) return null;
  const ok = metric.status === "ok" && metric.value !== null;
  const statusLabel =
    metric.status === "not_meaningful" ? "Tidak bermakna" : metric.status === "not_applicable" ? "Tidak diterapkan" : "Belum tersedia";
  const negative = ok && metric.value! < 0 && (metric.unit === "percent" || metric.unit === "currency");
  return (
    <div className={cn("flex flex-col rounded-lg border bg-card p-4 shadow-card", compact && "p-3.5")}>
      <div className="flex items-start justify-between gap-2">
        <span className="text-xs font-medium text-muted-foreground">{metric.label}</span>
        <InfoTip label={`Tentang ${metric.label}`}>
          <p className="font-medium">{METRIC_HELP[metric.key] ?? metric.label}</p>
          <p className="mt-1 text-muted-foreground">Rumus: {metric.formula}</p>
        </InfoTip>
      </div>
      {ok ? (
        <p className={cn("tabular mt-2 text-xl font-semibold tracking-tight", negative && "text-negative")}>
          {formatMetric(metric, currency)}
        </p>
      ) : (
        <p className="mt-2 flex items-center gap-1.5 text-sm font-medium text-muted-foreground">
          <CircleMinus className="size-4" aria-hidden="true" />
          {statusLabel}
        </p>
      )}
      {metric.explanation && <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">{metric.explanation}</p>}
      {metric.assumptions.length > 0 && (
        <ul className="mt-2 space-y-1 border-t pt-2">
          {metric.assumptions.map((a) => (
            <li key={a} className="text-[11px] leading-relaxed text-muted-foreground">
              <span className="font-medium text-warning">Asumsi:</span> {a}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Label that distinguishes measured metrics, rule-based findings and AI output. */
export function SourceLabel({ kind }: { kind: "measured" | "rule" | "ai" }) {
  const meta = {
    measured: { text: "Metrik terukur", variant: "outline" as const },
    rule: { text: "Temuan berbasis aturan", variant: "neutral" as const },
    ai: { text: "Dihasilkan AI", variant: "default" as const },
  }[kind];
  return <Badge variant={meta.variant}>{meta.text}</Badge>;
}

export function Section({ id, title, description, badge, children }: { id?: string; title: string; description?: ReactNode; badge?: ReactNode; children: ReactNode }) {
  return (
    <section id={id} aria-labelledby={id ? `${id}-title` : undefined} className="scroll-mt-20">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h2 id={id ? `${id}-title` : undefined} className="text-base font-semibold tracking-tight">
          {title}
        </h2>
        {badge}
      </div>
      {description && <p className="-mt-1.5 mb-3 text-sm text-muted-foreground">{description}</p>}
      {children}
    </section>
  );
}
