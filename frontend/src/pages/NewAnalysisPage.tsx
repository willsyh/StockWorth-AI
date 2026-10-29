import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Controller, useForm, type FieldPath } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Check,
  Download,
  FileSpreadsheet,
  FileText,
  Info,
  Keyboard,
  Loader2,
  Save,
  Table2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Textarea } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Notice, PageHeader, errorMessage } from "@/components/ui/states";
import { FieldShell, SourceRef } from "@/components/analysis/FormField";
import { ImportPanel, type ImportKind } from "@/components/analysis/ImportPanel";
import { ReviewStep } from "@/components/analysis/ReviewStep";
import { useCreateAnalysis, useHealth } from "@/hooks/queries";
import { api, ApiError } from "@/lib/api";
import { BASES, FIELD_GROUPS, FIELD_META, PERIODS_FOR, PREVIOUS_FIELDS, SECTORS, UNITS, periodLabel } from "@/lib/fields";
import { parseIdNumber, toInputString } from "@/lib/format";
import { cn } from "@/lib/utils";
import {
  analysisFormSchema,
  defaultFormValues,
  fieldPathLabel,
  toAnalysisInput,
  type AnalysisFormValues,
  type FetchedPrice,
} from "@/schemas/analysisForm";
import type { AnalysisInput, ImportPreview, SourceInfo, ValueField } from "@/types/api";

type Method = "manual" | ImportKind;

const STEPS = [
  { title: "Sumber data", description: "Manual atau unggah" },
  { title: "Perusahaan", description: "Emiten & periode" },
  { title: "Data keuangan", description: "Laporan & harga" },
  { title: "Tinjau", description: "Periksa & simpan" },
];

const STEP1_FIELDS: FieldPath<AnalysisFormValues>[] = ["ticker", "name", "sector", "fiscal_year", "basis", "period", "currency", "unit", "fx_rate"];

function Stepper({ step, onJump }: { step: number; onJump: (i: number) => void }) {
  return (
    <ol className="mb-6 grid grid-cols-4 gap-2" aria-label="Langkah analisis">
      {STEPS.map((s, i) => {
        const done = i < step;
        const active = i === step;
        return (
          <li key={s.title}>
            <button
              type="button"
              onClick={() => done && onJump(i)}
              disabled={!done}
              aria-current={active ? "step" : undefined}
              className={cn(
                "flex w-full flex-col gap-2 rounded-md text-left disabled:cursor-default",
                done && "cursor-pointer hover:opacity-80",
              )}
            >
              <span className={cn("h-1 w-full rounded-full", done || active ? "bg-primary" : "bg-muted")} aria-hidden="true" />
              <span className="flex items-center gap-1.5">
                <span
                  className={cn(
                    "flex size-5 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold",
                    done ? "bg-primary text-primary-foreground" : active ? "border-2 border-primary text-primary" : "border text-muted-foreground",
                  )}
                >
                  {done ? <Check className="size-3" aria-hidden="true" /> : i + 1}
                </span>
                <span className={cn("truncate text-xs font-medium sm:text-sm", !active && !done && "text-muted-foreground")}>{s.title}</span>
              </span>
              <span className="hidden pl-[26px] text-xs text-muted-foreground md:block">{s.description}</span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

function MethodCard({
  icon: Icon,
  title,
  description,
  selected,
  disabled,
  onSelect,
  badge,
}: {
  icon: typeof Keyboard;
  title: string;
  description: string;
  selected: boolean;
  disabled?: boolean;
  onSelect: () => void;
  badge?: string;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      disabled={disabled}
      onClick={onSelect}
      className={cn(
        "flex flex-col items-start gap-2 rounded-lg border bg-card p-4 text-left shadow-card transition-colors disabled:cursor-not-allowed disabled:opacity-60",
        selected ? "border-primary ring-1 ring-primary" : "hover:border-primary/40",
      )}
    >
      <span className="flex w-full items-center justify-between">
        <Icon className={cn("size-5", selected ? "text-primary" : "text-muted-foreground")} aria-hidden="true" />
        {badge && <span className="rounded bg-muted px-1.5 py-0.5 text-[11px] font-medium text-muted-foreground">{badge}</span>}
      </span>
      <span className="text-sm font-semibold">{title}</span>
      <span className="text-xs leading-relaxed text-muted-foreground">{description}</span>
    </button>
  );
}

export default function NewAnalysisPage() {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [method, setMethod] = useState<Method>("manual");
  const [imported, setImported] = useState<{ preview: ImportPreview; values: Record<string, number> } | null>(null);
  const [reviewInput, setReviewInput] = useState<AnalysisInput | null>(null);

  const form = useForm<AnalysisFormValues>({
    resolver: zodResolver(analysisFormSchema),
    defaultValues: defaultFormValues(),
    mode: "onTouched",
  });
  const { register, control, watch, setValue, getValues, trigger, formState } = form;
  const errors = formState.errors;

  const basis = watch("basis");
  const currency = watch("currency");
  const unit = watch("unit");
  const includePrevious = watch("include_previous");
  const fiscalYear = watch("fiscal_year");

  const calc = useMutation({ mutationFn: (input: AnalysisInput) => api.calculate(input) });
  const health = useHealth();
  const marketConfigured = Boolean(health.data?.market_data?.configured);
  const quote = useMutation({ mutationFn: (ticker: string) => api.quote(ticker) });
  const [fetchedPrice, setFetchedPrice] = useState<(FetchedPrice & { label: string }) | null>(null);
  const watchedPrice = watch("share_price");
  const watchedPriceDate = watch("share_price_date");
  const priceStillFetched =
    fetchedPrice !== null && parseIdNumber(watchedPrice) === fetchedPrice.price && watchedPriceDate === fetchedPrice.trading_date;

  const fetchPrice = (opts: { auto?: boolean } = {}) => {
    const t = getValues("ticker").trim().toUpperCase();
    if (!/^[A-Z]{4}$/.test(t)) {
      if (!opts.auto) toast.error("Isi kode saham 4 huruf di langkah Perusahaan terlebih dahulu.");
      return;
    }
    quote.mutate(t, {
      onSuccess: (q) => {
        setValue("share_price", toInputString(q.price), { shouldValidate: true });
        setValue("share_price_date", q.trading_date, { shouldValidate: true });
        setValue("price_source", `${q.provider_label} (${q.provider_symbol}), harga terakhir ${q.trading_date}`);
        setFetchedPrice({ ...q, label: q.provider_label });
        if (opts.auto) toast.success(`Harga ${t} terisi otomatis dari ${q.provider_label}.`);
      },
    });
  };

  // Fetch the latest price automatically on entering the financial-data step, once per ticker,
  // and only when the price field is still empty (a price the user typed is never overwritten).
  const autoFetchedFor = useRef<string | null>(null);
  useEffect(() => {
    if (step !== 2 || !marketConfigured) return;
    const t = getValues("ticker").trim().toUpperCase();
    if (!/^[A-Z]{4}$/.test(t) || getValues("share_price").trim() !== "" || autoFetchedFor.current === t) return;
    autoFetchedFor.current = t;
    fetchPrice({ auto: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, marketConfigured]);
  const create = useCreateAnalysis();

  const unitText = `${UNITS.find((u) => u.value === unit)?.label.toLowerCase()} ${currency}`;

  const buildSource = (values: AnalysisFormValues): SourceInfo => {
    if (!imported) return { method: "manual", file_name: null, cell_refs: {}, edited_after_import: [] };
    const edited: string[] = [];
    for (const [key, original] of Object.entries(imported.values)) {
      const [role, field] = key.split(".") as ["current" | "previous", ValueField];
      const raw = role === "current" ? values.current[field] : values.previous[field as (typeof PREVIOUS_FIELDS)[number]];
      const now = parseIdNumber(raw);
      if (now !== original) edited.push(key);
    }
    return {
      method: imported.preview.file_type,
      file_name: imported.preview.file_name,
      cell_refs: {
        ...imported.preview.cell_refs,
        // Where pre-filled company/period info came from (kept only if the user didn't change it).
        ...Object.fromEntries(
          (
            [
              ["ticker", values.ticker.trim().toUpperCase(), "company.ticker"],
              ["company_name", values.name.trim(), "company.name"],
              ["fiscal_year", Number(values.fiscal_year), "statement.fiscal_year"],
              ["basis", values.basis, "statement.basis"],
            ] as const
          )
            .filter(([k, v]) => imported.preview.detected?.[k] != null && imported.preview.detected[k] === v)
            .map(([k, , ref]) => [ref, imported.preview.detected!.sources[k] ?? ""]),
        ),
      },
      edited_after_import: edited,
    };
  };

  const applyImport = (preview: ImportPreview) => {
    const values: Record<string, number> = {};
    for (const [f, v] of Object.entries(preview.current)) {
      if (v === null || v === undefined) continue;
      setValue(`current.${f as ValueField}`, toInputString(v), { shouldDirty: true });
      values[`current.${f}`] = v;
    }
    let prevCount = 0;
    for (const [f, v] of Object.entries(preview.previous)) {
      if (v === null || v === undefined || !PREVIOUS_FIELDS.includes(f as ValueField)) continue;
      setValue(`previous.${f as ValueField}`, toInputString(v), { shouldDirty: true });
      values[`previous.${f}`] = v;
      prevCount++;
    }
    if (prevCount > 0) setValue("include_previous", true);
    if (preview.unit) setValue("unit", preview.unit);
    if (preview.currency) setValue("currency", preview.currency);
    const d = preview.detected;
    const filled: string[] = [];
    if (d?.ticker) {
      setValue("ticker", d.ticker, { shouldDirty: true });
      filled.push("kode saham");
    }
    if (d?.company_name) {
      setValue("name", d.company_name, { shouldDirty: true });
      filled.push("nama");
    }
    if (d?.fiscal_year) {
      setValue("fiscal_year", String(d.fiscal_year), { shouldDirty: true });
      filled.push("tahun");
    }
    if (d?.basis) {
      setValue("basis", d.basis);
      setValue("period", d.period ?? (d.basis === "annual" ? "FY" : "Q3"));
      filled.push("periode");
    }
    if (d?.sector) {
      setValue("sector", d.sector);
      filled.push("sektor");
    }
    syncPreviousPeriod();
    setImported({ preview, values });
    // New report uploaded: refresh the share price right away when the ticker is known.
    if (d?.ticker && marketConfigured) {
      autoFetchedFor.current = d.ticker;
      fetchPrice({ auto: true });
    }
    toast.success(
      `${Object.keys(values).length} nilai diterapkan dari ${preview.file_name}` +
        (filled.length ? `; ${filled.join(", ")} terisi otomatis.` : "."),
    );
    setStep(1);
    if (!d?.ticker) requestAnimationFrame(() => document.getElementById("ticker")?.focus());
  };

  const detected = imported?.preview.detected;
  const detectedSrc = (key: "ticker" | "company_name" | "fiscal_year" | "basis" | "period" | "sector") =>
    detected?.[key] ? detected.sources[key] : undefined;
  const fromFile = (key: Parameters<typeof detectedSrc>[0]) => {
    const src = detectedSrc(key);
    return src ? <SourceRef refText={`Terdeteksi dari ${src}`} /> : undefined;
  };
  const detectedCount = detected
    ? (["ticker", "company_name", "fiscal_year", "basis"] as const).filter((k) => detected[k]).length
    : 0;
  const detectedNotice = imported ? (
    detectedCount > 0 ? (
      <Notice tone="info" icon={Info}>
        Info di bawah terisi otomatis dari <span className="font-medium">{imported.preview.file_name}</span>. Periksa sebelum
        lanjut{detected?.ticker ? "." : "; kode saham tidak tercantum di laporan, jadi isi 4 hurufnya."}
      </Notice>
    ) : (
      <Notice tone="neutral" icon={Info}>
        Nama perusahaan dan periode tidak terdeteksi di berkas. Isi secara manual.
      </Notice>
    )
  ) : null;
  const periodNotice = detected?.period_note ? (
    <Notice tone="warning" icon={AlertTriangle}>
      {detected.period_note} Pilih jenis laporan dan periode secara manual.
    </Notice>
  ) : null;

  /** Comparative period defaults to the same period one year earlier. */
  const syncPreviousPeriod = () => {
    const v = getValues();
    if (!/^\d{4}$/.test(v.fiscal_year)) return;
    if (!v.prev_fiscal_year || Number(v.prev_fiscal_year) !== Number(v.fiscal_year) - 1) {
      setValue("prev_fiscal_year", String(Number(v.fiscal_year) - 1));
    }
    setValue("prev_period", v.period);
  };

  const goNext = async () => {
    if (step === 0) {
      setStep(1);
    } else if (step === 1) {
      const ok = await trigger(STEP1_FIELDS);
      if (!ok) {
        requestAnimationFrame(() => document.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus());
        return;
      }
      syncPreviousPeriod();
      setStep(2);
    } else if (step === 2) {
      const ok = await trigger();
      if (!ok) {
        toast.error("Periksa kembali isian yang ditandai.");
        requestAnimationFrame(() => {
          const el = document.querySelector<HTMLElement>('[aria-invalid="true"]');
          el?.scrollIntoView({ block: "center", behavior: "smooth" });
          el?.focus({ preventScroll: true });
        });
        return;
      }
      const values = getValues();
      const input = toAnalysisInput(values, buildSource(values), fetchedPrice);
      setReviewInput(input);
      calc.mutate(input);
      setStep(3);
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const goBack = () => {
    setStep((s) => Math.max(0, s - 1));
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const save = () => {
    if (!reviewInput) return;
    create.mutate(reviewInput, {
      onSuccess: (rec) => {
        toast.success("Analisis tersimpan.");
        navigate(`/analisis/${rec.id}`);
      },
      onError: (e) => {
        const details = e instanceof ApiError && e.details.length ? `: ${e.details.map((d) => `${fieldPathLabel(d.field)} — ${d.message}`).join("; ")}` : "";
        toast.error(`${errorMessage(e)}${details}`);
      },
    });
  };

  const numberInput = (name: `current.${ValueField}` | `previous.${ValueField}`, field: ValueField, idSuffix = "") => {
    const id = `${name.replace(".", "-")}${idSuffix}`;
    const [role] = name.split(".");
    const err = role === "current" ? errors.current?.[field]?.message : errors.previous?.[field as (typeof PREVIOUS_FIELDS)[number]]?.message;
    const meta = FIELD_META[field];
    const ref = imported?.preview.cell_refs[name];
    const reg = register(name, {
      onBlur: (e) => {
        const n = parseIdNumber(e.target.value);
        if (n !== undefined && !Number.isNaN(n)) setValue(name, toInputString(n));
      },
    });
    return (
      <FieldShell
        key={id}
        id={id}
        label={meta.label}
        help={
          <>
            <p>{meta.help}</p>
            <p className="mt-1 text-muted-foreground">Dipakai untuk: {meta.usedFor.join(", ")}.</p>
          </>
        }
        error={err}
        hint={ref ? <SourceRef refText={ref} edited={imported ? parseIdNumber(watch(name)) !== imported.values[name] : false} /> : undefined}
      >
        <div className="relative">
          <Input
            id={id}
            inputMode="decimal"
            autoComplete="off"
            placeholder="Kosongkan jika tidak ada"
            aria-invalid={Boolean(err)}
            aria-describedby={err ? `${id}-error` : ref ? `${id}-hint` : undefined}
            className="tabular pr-20 text-right"
            {...reg}
          />
          <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">
            {meta.kind === "shares" ? "lembar" : unitText}
          </span>
        </div>
      </FieldShell>
    );
  };

  const reviewTitle = useMemo(() => {
    const v = getValues();
    return `${v.ticker.toUpperCase()} · ${periodLabel(Number(v.fiscal_year), v.period, v.basis)}`;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step]);

  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader title="Analisis baru" description="Unggah laporan keuangan atau isi manual, lalu tinjau sebelum menyimpan." />
      <Stepper step={step} onJump={setStep} />

      <form onSubmit={(e) => e.preventDefault()} noValidate>
        {step === 1 && (
          <div className="space-y-5">
            {detectedNotice}
            {periodNotice}
            <Card>
              <CardHeader>
                <CardTitle>Informasi perusahaan</CardTitle>
                <CardDescription>Kode saham dan nama yang Anda isi belum diverifikasi terhadap data resmi BEI.</CardDescription>
              </CardHeader>
              <CardContent className="grid gap-4 sm:grid-cols-2">
                <FieldShell
                  id="ticker"
                  label="Kode saham"
                  error={errors.ticker?.message}
                  hint={
                    fromFile("ticker") ??
                    (imported ? "Tidak tercantum di laporan. Isi 4 huruf, contoh: BBCA, TLKM" : "4 huruf, contoh: BBCA, TLKM")
                  }
                >
                  <Input
                    id="ticker"
                    maxLength={4}
                    autoComplete="off"
                    className="uppercase"
                    aria-invalid={Boolean(errors.ticker)}
                    {...register("ticker", { setValueAs: (v: string) => v.toUpperCase() })}
                  />
                </FieldShell>
                <FieldShell id="name" label="Nama perusahaan" error={errors.name?.message} hint={fromFile("company_name")}>
                  <Input id="name" autoComplete="off" placeholder="PT ... Tbk" aria-invalid={Boolean(errors.name)} {...register("name")} />
                </FieldShell>
                <FieldShell
                  id="sector"
                  label="Sektor"
                  optional
                  hint={fromFile("sector")}
                  help="Menentukan profil penilaian. Bank dan perusahaan keuangan diperlakukan berbeda (DER dan current ratio tidak diterapkan untuk bank)."
                >
                  <Controller
                    control={control}
                    name="sector"
                    render={({ field }) => (
                      <Select value={field.value || "none"} onValueChange={(v) => field.onChange(v === "none" ? "" : v)}>
                        <SelectTrigger id="sector">
                          <SelectValue placeholder="Pilih sektor" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="none">Tidak diisi (profil umum)</SelectItem>
                          {SECTORS.map((s) => (
                            <SelectItem key={s.value} value={s.value}>
                              {s.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    )}
                  />
                </FieldShell>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Periode & satuan laporan</CardTitle>
                <CardDescription>Semua nilai uang dinormalisasi ke rupiah penuh sebelum dihitung.</CardDescription>
              </CardHeader>
              <CardContent className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                <FieldShell id="fiscal_year" label="Tahun fiskal" error={errors.fiscal_year?.message} hint={fromFile("fiscal_year")}>
                  <Input id="fiscal_year" inputMode="numeric" maxLength={4} aria-invalid={Boolean(errors.fiscal_year)} {...register("fiscal_year")} />
                </FieldShell>
                <FieldShell
                  id="basis"
                  label="Jenis laporan"
                  hint={fromFile("basis")}
                  help="Laporan kuartalan BEI umumnya kumulatif sejak awal tahun (mis. 9 bulan). Pilih 'per kuartal' hanya jika angka mencakup satu kuartal saja."
                >
                  <Controller
                    control={control}
                    name="basis"
                    render={({ field }) => (
                      <Select
                        value={field.value}
                        onValueChange={(v) => {
                          field.onChange(v);
                          setValue("period", v === "annual" ? "FY" : "Q3");
                        }}
                      >
                        <SelectTrigger id="basis">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {BASES.map((b) => (
                            <SelectItem key={b.value} value={b.value}>
                              {b.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    )}
                  />
                </FieldShell>
                <FieldShell id="period" label="Periode" error={errors.period?.message}>
                  <Controller
                    control={control}
                    name="period"
                    render={({ field }) => (
                      <Select value={field.value} onValueChange={field.onChange} disabled={basis === "annual"}>
                        <SelectTrigger id="period">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {PERIODS_FOR[basis].map((p) => (
                            <SelectItem key={p} value={p}>
                              {basis === "ytd" ? `${p} (${{ Q1: 3, Q2: 6, Q3: 9, Q4: 12, FY: 12 }[p]} bulan)` : p === "FY" ? "Setahun penuh (FY)" : p}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    )}
                  />
                </FieldShell>
                <FieldShell id="currency" label="Mata uang laporan" help="Beberapa emiten (mis. sektor energi) melaporkan dalam USD.">
                  <Controller
                    control={control}
                    name="currency"
                    render={({ field }) => (
                      <Select value={field.value} onValueChange={field.onChange}>
                        <SelectTrigger id="currency">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="IDR">IDR — Rupiah</SelectItem>
                          <SelectItem value="USD">USD — Dolar AS</SelectItem>
                        </SelectContent>
                      </Select>
                    )}
                  />
                </FieldShell>
                <FieldShell id="unit" label="Satuan nilai" help="Ikuti satuan di laporan, mis. 'dalam jutaan Rupiah'. Jumlah saham selalu dalam lembar.">
                  <Controller
                    control={control}
                    name="unit"
                    render={({ field }) => (
                      <Select value={field.value} onValueChange={field.onChange}>
                        <SelectTrigger id="unit">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {UNITS.map((u) => (
                            <SelectItem key={u.value} value={u.value}>
                              {u.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    )}
                  />
                </FieldShell>
                {currency !== "IDR" && (
                  <FieldShell
                    id="fx_rate"
                    label={`Kurs IDR per 1 ${currency}`}
                    optional
                    error={errors.fx_rate?.message}
                    help="Dibutuhkan untuk PER dan PBV karena harga saham dalam rupiah. Gunakan kurs yang sesuai dengan tanggal harga."
                  >
                    <Input id="fx_rate" inputMode="decimal" placeholder="contoh: 16.250" className="tabular text-right" {...register("fx_rate")} />
                  </FieldShell>
                )}
              </CardContent>
            </Card>
          </div>
        )}

        {step === 0 && (
          <div className="space-y-5">
            <div role="radiogroup" aria-label="Metode input data" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <MethodCard icon={Keyboard} title="Input manual" description="Ketik angka dari laporan keuangan." selected={method === "manual"} onSelect={() => setMethod("manual")} />
              <MethodCard icon={FileText} title="Unggah CSV" description="Templat CSV dengan satu baris per akun." selected={method === "csv"} onSelect={() => setMethod("csv")} />
              <MethodCard icon={FileSpreadsheet} title="Unggah Excel" description="Templat .xlsx atau .xls (Excel 97-2003), tanpa makro." selected={method === "excel"} onSelect={() => setMethod("excel")} />
              <MethodCard
                icon={Table2}
                title="Unggah PDF"
                description="Laporan keuangan PDF (berbasis teks). Angka dibaca otomatis dan wajib Anda periksa."
                selected={method === "pdf"}
                badge="Beta"
                onSelect={() => setMethod("pdf")}
              />
            </div>
            {method !== "manual" ? (
              <ImportPanel key={method} kind={method} formUnit={unit} onApply={applyImport} />
            ) : (
              <Notice tone="info" icon={Info}>
                Anda akan mengisi angka langsung di langkah berikutnya. Gunakan titik untuk pemisah ribuan dan koma untuk desimal,
                contoh <span className="tabular font-medium">1.234.567,5</span>.
              </Notice>
            )}
            {imported && (
              <Notice tone="positive" icon={Check}>
                Data dari <span className="font-medium">{imported.preview.file_name}</span> sudah diterapkan. Lanjut untuk
                memeriksa info perusahaan.
              </Notice>
            )}
          </div>
        )}

        {step === 2 && (
          <div className="space-y-5">
            <Notice tone="neutral" icon={Info}>
              Nilai uang dalam <span className="font-medium">{unitText}</span>. Kosongkan kolom yang datanya tidak Anda miliki; kolom
              kosong tidak dianggap nol. Angka negatif boleh untuk laba, ekuitas, dan arus kas operasi.
            </Notice>
            {errors.current?.revenue?.message && !getValues("current.revenue") && (
              <Notice tone="negative">{errors.current.revenue.message}</Notice>
            )}
            {FIELD_GROUPS.map((g) => (
              <Card key={g.title}>
                <CardHeader>
                  <CardTitle>{g.title}</CardTitle>
                  <CardDescription>{g.description}</CardDescription>
                </CardHeader>
                <CardContent className="grid gap-4 sm:grid-cols-2">{g.fields.map((f) => numberInput(`current.${f}`, f))}</CardContent>
              </Card>
            ))}

            <Card>
              <CardHeader className="flex-row flex-wrap items-start justify-between gap-3 space-y-0">
                <div>
                  <CardTitle>Harga saham</CardTitle>
                  <CardDescription>
                    Dibutuhkan untuk PER dan PBV. Isi harga beserta tanggalnya
                    {marketConfigured ? ", harga terakhir diambil otomatis dari penyedia data." : "."}
                  </CardDescription>
                </div>
                {marketConfigured && (
                  <Button type="button" variant="outline" size="sm" onClick={() => fetchPrice()} disabled={quote.isPending}>
                    {quote.isPending ? <Loader2 className="animate-spin" /> : <Download />}
                    {quote.isPending ? "Mengambil harga…" : `Ambil harga ${watch("ticker").toUpperCase()}`.trim()}
                  </Button>
                )}
              </CardHeader>
              <CardContent className="grid gap-4 sm:grid-cols-2">
                {quote.isError && (
                  <Notice tone="warning" icon={Info} className="sm:col-span-2">
                    {errorMessage(quote.error)}
                  </Notice>
                )}
                {fetchedPrice && (
                  <Notice tone={priceStillFetched ? "positive" : "neutral"} icon={priceStillFetched ? Check : Info} className="sm:col-span-2">
                    {priceStillFetched ? (
                      <>
                        Harga dari <span className="font-medium">{fetchedPrice.label}</span> ({fetchedPrice.provider_symbol}), harga terakhir{" "}
                        {fetchedPrice.trading_date}. Bisa tertunda; bukan harga real-time.
                      </>
                    ) : (
                      <>Harga atau tanggal sudah Anda ubah, jadi akan disimpan sebagai harga yang diisi manual.</>
                    )}
                  </Notice>
                )}
                <FieldShell id="share_price" label="Harga saham (Rp per lembar)" optional error={errors.share_price?.message}>
                  <Input id="share_price" inputMode="decimal" className="tabular text-right" aria-invalid={Boolean(errors.share_price)} {...register("share_price")} />
                </FieldShell>
                <FieldShell id="share_price_date" label="Tanggal harga" optional error={errors.share_price_date?.message}>
                  <Input
                    id="share_price_date"
                    type="date"
                    max={new Date().toISOString().slice(0, 10)}
                    aria-invalid={Boolean(errors.share_price_date)}
                    {...register("share_price_date")}
                  />
                </FieldShell>
                <FieldShell id="price_source" label="Catatan sumber harga" optional error={errors.price_source?.message} className="sm:col-span-2">
                  <Textarea id="price_source" rows={2} placeholder="mis. harga penutupan dari aplikasi sekuritas" {...register("price_source")} />
                </FieldShell>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex-row items-start justify-between gap-4 space-y-0">
                <div>
                  <CardTitle>Periode pembanding</CardTitle>
                  <CardDescription>
                    Periode yang sama tahun sebelumnya, untuk pertumbuhan dan saldo awal. Biasanya tersedia sebagai kolom pembanding di
                    laporan yang sama.
                  </CardDescription>
                </div>
                <label className="flex shrink-0 cursor-pointer items-center gap-2 text-sm">
                  <input type="checkbox" className="size-4 accent-[hsl(var(--primary))]" {...register("include_previous")} />
                  Sertakan
                </label>
              </CardHeader>
              {includePrevious && (
                <CardContent className="space-y-4">
                  <div className="grid gap-4 sm:grid-cols-2">
                    <FieldShell id="prev_fiscal_year" label="Tahun fiskal pembanding" error={errors.prev_fiscal_year?.message} hint={`Disarankan: ${Number(fiscalYear) - 1}`}>
                      <Input id="prev_fiscal_year" inputMode="numeric" maxLength={4} {...register("prev_fiscal_year")} />
                    </FieldShell>
                    <FieldShell id="prev_period" label="Periode pembanding" hint="Harus sama dengan periode berjalan agar pertumbuhan dihitung.">
                      <Controller
                        control={control}
                        name="prev_period"
                        render={({ field }) => (
                          <Select value={field.value} onValueChange={field.onChange} disabled={basis === "annual"}>
                            <SelectTrigger id="prev_period">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              {PERIODS_FOR[basis].map((p) => (
                                <SelectItem key={p} value={p}>
                                  {p}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        )}
                      />
                    </FieldShell>
                  </div>
                  <div className="grid gap-4 sm:grid-cols-2">{PREVIOUS_FIELDS.map((f) => numberInput(`previous.${f}`, f, "-prev"))}</div>
                </CardContent>
              )}
            </Card>
          </div>
        )}

        {step === 3 && reviewInput && (
          <div>
            <h2 className="mb-4 text-base font-semibold">{reviewTitle}</h2>
            <ReviewStep input={reviewInput} result={calc.data} loading={calc.isPending} error={calc.error} />
          </div>
        )}

        <div className="sticky bottom-0 z-10 -mx-4 mt-6 flex items-center justify-between gap-3 border-t bg-background/95 px-4 py-3 backdrop-blur sm:mx-0 sm:rounded-lg sm:border sm:px-4">
          <Button type="button" variant="outline" onClick={goBack} disabled={step === 0 || create.isPending}>
            <ArrowLeft /> Kembali
          </Button>
          {step < 3 ? (
            <Button type="button" onClick={goNext}>
              {step === 2 ? "Tinjau data" : "Lanjut"} <ArrowRight />
            </Button>
          ) : (
            <Button type="button" onClick={save} disabled={!calc.isSuccess || create.isPending}>
              {create.isPending ? <Loader2 className="animate-spin" /> : <Save />}
              {create.isPending ? "Menyimpan…" : "Simpan & lihat hasil"}
            </Button>
          )}
        </div>
      </form>
    </div>
  );
}
