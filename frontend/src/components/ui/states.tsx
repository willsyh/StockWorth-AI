import type { ReactNode } from "react";
import { AlertTriangle, RefreshCw, type LucideIcon } from "lucide-react";
import { Button } from "./button";
import { cn } from "@/lib/utils";
import { ApiError } from "@/lib/api";

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}: {
  icon: LucideIcon;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center justify-center rounded-lg border border-dashed bg-card px-6 py-12 text-center", className)}>
      <div className="mb-4 flex size-11 items-center justify-center rounded-full bg-accent text-accent-foreground">
        <Icon className="size-5" aria-hidden="true" />
      </div>
      <h2 className="text-base font-semibold">{title}</h2>
      {description && <p className="mt-1.5 max-w-md text-sm text-muted-foreground">{description}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Terjadi kesalahan.";
}

export function ErrorState({ error, onRetry, title = "Gagal memuat data" }: { error: unknown; onRetry?: () => void; title?: string }) {
  return (
    <div role="alert" className="flex flex-col items-center rounded-lg border bg-card px-6 py-10 text-center">
      <AlertTriangle className="mb-3 size-6 text-negative" aria-hidden="true" />
      <h2 className="text-base font-semibold">{title}</h2>
      <p className="mt-1 max-w-md text-sm text-muted-foreground">{errorMessage(error)}</p>
      {onRetry && (
        <Button variant="outline" size="sm" className="mt-4" onClick={onRetry}>
          <RefreshCw /> Coba lagi
        </Button>
      )}
    </div>
  );
}

export function Notice({
  tone = "neutral",
  icon: Icon,
  children,
  className,
}: {
  tone?: "neutral" | "warning" | "negative" | "positive" | "info";
  icon?: LucideIcon;
  children: ReactNode;
  className?: string;
}) {
  const tones = {
    neutral: "bg-muted text-foreground border-border",
    info: "bg-accent text-accent-foreground border-transparent",
    warning: "bg-warning-soft text-warning border-transparent",
    negative: "bg-negative-soft text-negative border-transparent",
    positive: "bg-positive-soft text-positive border-transparent",
  };
  return (
    <div className={cn("flex gap-2.5 rounded-md border px-3 py-2.5 text-sm", tones[tone], className)}>
      {Icon && <Icon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />}
      <div className="min-w-0 [&_p]:leading-relaxed">{children}</div>
    </div>
  );
}
