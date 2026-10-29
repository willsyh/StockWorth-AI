import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Bot, Database, LineChart, Loader2, Monitor, Moon, ShieldCheck, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/misc";
import { FieldShell } from "@/components/analysis/FormField";
import { PageHeader, errorMessage } from "@/components/ui/states";
import { useTheme, type ThemePreference } from "@/app/theme";
import { useAuth } from "@/app/auth";
import { useHealth } from "@/hooks/queries";
import { supabase } from "@/lib/supabase";
import { supabaseEnabled } from "@/lib/config";
import { cn } from "@/lib/utils";

function ProfileCard() {
  const auth = useAuth();
  const qc = useQueryClient();
  const userId = auth.user?.id;
  const profile = useQuery({
    queryKey: ["profile", userId],
    enabled: Boolean(supabase && userId),
    queryFn: async () => {
      // RLS restricts this to the signed-in user's own row.
      const { data, error } = await supabase!.from("profiles").select("display_name").eq("id", userId!).maybeSingle();
      if (error) throw new Error("Profil tidak dapat dimuat.");
      return data;
    },
  });
  const [name, setName] = useState("");
  useEffect(() => setName(profile.data?.display_name ?? ""), [profile.data]);
  const save = useMutation({
    mutationFn: async () => {
      const clean = name.trim().slice(0, 80);
      const { error } = await supabase!.from("profiles").upsert({ id: userId!, display_name: clean || null });
      if (error) throw new Error("Profil gagal disimpan.");
    },
    onSuccess: () => {
      toast.success("Profil disimpan.");
      qc.invalidateQueries({ queryKey: ["profile", userId] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  if (!auth.enabled) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Profil</CardTitle>
          <CardDescription>Autentikasi tidak aktif. Aplikasi berjalan dalam mode lokal dengan satu pengguna lokal.</CardDescription>
        </CardHeader>
      </Card>
    );
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle>Profil</CardTitle>
        <CardDescription>{auth.user?.email}</CardDescription>
      </CardHeader>
      <CardContent>
        {profile.isLoading ? (
          <Skeleton className="h-16" />
        ) : (
          <form
            className="flex flex-col gap-3 sm:flex-row sm:items-end"
            onSubmit={(e) => {
              e.preventDefault();
              save.mutate();
            }}
          >
            <FieldShell id="display_name" label="Nama tampilan" optional className="flex-1">
              <Input id="display_name" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} />
            </FieldShell>
            <Button type="submit" disabled={save.isPending}>
              {save.isPending && <Loader2 className="animate-spin" />} Simpan
            </Button>
          </form>
        )}
      </CardContent>
    </Card>
  );
}

export default function SettingsPage() {
  const { theme, setTheme } = useTheme();
  const health = useHealth();
  const options: { value: ThemePreference; label: string; icon: typeof Sun }[] = [
    { value: "light", label: "Terang", icon: Sun },
    { value: "dark", label: "Gelap", icon: Moon },
    { value: "system", label: "Ikuti sistem", icon: Monitor },
  ];
  const h = health.data;

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title="Pengaturan" description="Tampilan, profil, dan status konfigurasi." />
      <div className="space-y-5">
        <Card>
          <CardHeader>
            <CardTitle>Tema</CardTitle>
            <CardDescription>Disimpan di peramban ini.</CardDescription>
          </CardHeader>
          <CardContent>
            <div role="radiogroup" aria-label="Pilihan tema" className="grid grid-cols-3 gap-2">
              {options.map((o) => (
                <button
                  key={o.value}
                  type="button"
                  role="radio"
                  aria-checked={theme === o.value}
                  onClick={() => setTheme(o.value)}
                  className={cn(
                    "flex flex-col items-center gap-2 rounded-lg border px-3 py-4 text-sm font-medium transition-colors",
                    theme === o.value ? "border-primary bg-accent text-accent-foreground" : "hover:bg-muted",
                  )}
                >
                  <o.icon className="size-5" aria-hidden="true" />
                  {o.label}
                </button>
              ))}
            </div>
          </CardContent>
        </Card>

        <ProfileCard />

        <Card>
          <CardHeader>
            <CardTitle>Status konfigurasi</CardTitle>
            <CardDescription>Kunci rahasia tidak pernah ditampilkan atau dikirim ke peramban.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {health.isLoading ? (
              <Skeleton className="h-28" />
            ) : health.isError ? (
              <p className="text-sm text-negative">Server tidak dapat dihubungi: {errorMessage(health.error)}</p>
            ) : h ? (
              <>
                <div className="flex items-start gap-3">
                  <Bot className="mt-0.5 size-5 text-muted-foreground" aria-hidden="true" />
                  <div className="flex-1">
                    <p className="flex flex-wrap items-center gap-2 text-sm font-medium">
                      Penyedia AI
                      {h.ai.configured ? <Badge variant="positive">Terkonfigurasi</Badge> : <Badge variant="neutral">Belum dikonfigurasi</Badge>}
                    </p>
                    <p className="mt-0.5 text-sm text-muted-foreground">
                      {h.ai.configured
                        ? `${h.ai.provider} · model ${h.ai.model}. Kunci API tersimpan di server.`
                        : "Insight disusun dengan aturan deterministik dan diberi label 'berbasis aturan'. Atur GEMINI_API_KEY (AI_PROVIDER=gemini) atau ANTHROPIC_API_KEY di backend untuk mengaktifkan AI."}
                    </p>
                  </div>
                </div>
                <div className="flex items-start gap-3">
                  <LineChart className="mt-0.5 size-5 text-muted-foreground" aria-hidden="true" />
                  <div className="flex-1">
                    <p className="flex flex-wrap items-center gap-2 text-sm font-medium">
                      Data harga saham
                      {h.market_data?.configured ? <Badge variant="positive">Terkonfigurasi</Badge> : <Badge variant="neutral">Belum dikonfigurasi</Badge>}
                    </p>
                    <p className="mt-0.5 text-sm text-muted-foreground">
                      {h.market_data?.configured
                        ? `Penyedia: ${h.market_data.provider === "alpha_vantage" ? "Alpha Vantage" : h.market_data.provider}. ${h.market_data.coverage_note} Jika penyedia tidak punya data BEI, harga tetap diisi manual.`
                        : "Harga saham diisi manual. Atur ALPHA_VANTAGE_API_KEY di backend untuk mengaktifkan tombol 'Ambil harga'."}
                    </p>
                  </div>
                </div>
                <div className="flex items-start gap-3">
                  <Database className="mt-0.5 size-5 text-muted-foreground" aria-hidden="true" />
                  <div className="flex-1">
                    <p className="flex flex-wrap items-center gap-2 text-sm font-medium">
                      Penyimpanan
                      {h.storage === "supabase" ? <Badge variant="positive">Supabase</Badge> : <Badge variant="warning">Lokal (SQLite)</Badge>}
                    </p>
                    <p className="mt-0.5 text-sm text-muted-foreground">
                      {h.storage === "supabase"
                        ? "Data disimpan di Supabase PostgreSQL dengan Row Level Security per pengguna."
                        : "Mode pengembangan: data disimpan di berkas SQLite pada server lokal, tanpa login."}
                    </p>
                    {h.auth_required !== supabaseEnabled && (
                      <p className="mt-1 text-sm text-warning">
                        Konfigurasi frontend dan backend tidak cocok: {h.auth_required ? "backend memerlukan login tetapi frontend belum dikonfigurasi Supabase." : "frontend memakai Supabase tetapi backend dalam mode lokal."}
                      </p>
                    )}
                  </div>
                </div>
                <p className="text-xs text-muted-foreground">
                  API v{h.version} · metodologi v{h.methodology_version} · batas unggah {h.max_upload_mb} MB
                </p>
              </>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ShieldCheck className="size-4" aria-hidden="true" /> Data & privasi
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="list-disc space-y-1.5 pl-5 text-sm leading-relaxed text-muted-foreground">
              <li>Analisis Anda hanya dapat dibaca oleh akun Anda (Row Level Security di database).</li>
              <li>Berkas CSV/XLSX hanya dibaca di memori untuk pratinjau dan tidak disimpan. Nilai yang Anda simpan mencatat sel sumbernya.</li>
              <li>Jika AI aktif, hanya metrik terhitung dan temuan terstruktur yang dikirim ke penyedia AI, tanpa email atau catatan bebas Anda.</li>
              <li>Harga saham berasal dari input Anda atau, jika diaktifkan, dari penyedia data harga; sumber dan tanggalnya selalu ditampilkan. Tidak ada harga real-time.</li>
              <li>Menghapus analisis juga menghapus laporan keuangan dan insight terkait.</li>
            </ul>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
