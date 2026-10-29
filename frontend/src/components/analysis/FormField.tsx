import type { ReactNode } from "react";
import { FileSpreadsheet } from "lucide-react";
import { Label } from "@/components/ui/label";
import { InfoTip } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

interface FieldShellProps {
  id: string;
  label: string;
  help?: ReactNode;
  error?: string;
  hint?: ReactNode;
  optional?: boolean;
  children: ReactNode;
  className?: string;
}

/** Label + tooltip + control + inline error/hint, wired for screen readers. */
export function FieldShell({ id, label, help, error, hint, optional, children, className }: FieldShellProps) {
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <div className="flex items-center gap-1.5">
        <Label htmlFor={id}>{label}</Label>
        {optional && <span className="text-xs text-muted-foreground">(opsional)</span>}
        {help && <InfoTip label={`Penjelasan ${label}`}>{help}</InfoTip>}
      </div>
      {children}
      {error ? (
        <p id={`${id}-error`} className="text-xs text-negative" role="alert">
          {error}
        </p>
      ) : hint ? (
        <p id={`${id}-hint`} className="text-xs text-muted-foreground">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

export function SourceRef({ refText, edited }: { refText?: string; edited?: boolean }) {
  if (!refText) return null;
  return (
    <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground">
      <FileSpreadsheet className="size-3" aria-hidden="true" />
      {refText}
      {edited && <span className="font-medium text-warning">· diubah</span>}
    </span>
  );
}
