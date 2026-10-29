import { useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Notice } from "@/components/ui/states";
import { FieldShell } from "@/components/analysis/FormField";
import { useAuth } from "@/app/auth";

const schema = z.object({
  email: z.string().trim().email("Masukkan email yang valid."),
  password: z.string().min(8, "Kata sandi minimal 8 karakter."),
});
type Values = z.infer<typeof schema>;

export default function LoginPage() {
  const auth = useAuth();
  const location = useLocation();
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [message, setMessage] = useState<{ tone: "negative" | "positive"; text: string } | null>(null);
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { email: "", password: "" } });
  const from = (location.state as { from?: string } | null)?.from ?? "/";

  if (!auth.enabled || auth.user) return <Navigate to={from} replace />;

  const onSubmit = form.handleSubmit(async (v) => {
    setMessage(null);
    try {
      if (mode === "signin") {
        await auth.signIn(v.email, v.password);
      } else {
        const { needsConfirmation } = await auth.signUp(v.email, v.password);
        if (needsConfirmation) setMessage({ tone: "positive", text: "Akun dibuat. Periksa email Anda untuk konfirmasi, lalu masuk." });
      }
    } catch (e) {
      setMessage({ tone: "negative", text: e instanceof Error ? e.message : "Gagal." });
    }
  });

  const errors = form.formState.errors;
  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center justify-center gap-2.5">
          <img src="/logo-mark.png" alt="" width={44} height={44} className="size-11" />
          <span className="text-lg font-semibold tracking-tight">
            StockWorth <span className="text-primary">AI</span>
          </span>
        </div>
        <Card>
          <CardHeader>
            <CardTitle>{mode === "signin" ? "Masuk" : "Buat akun"}</CardTitle>
            <CardDescription>Analisis Anda tersimpan privat di akun Anda.</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={onSubmit} className="space-y-4" noValidate>
              <FieldShell id="email" label="Email" error={errors.email?.message}>
                <Input id="email" type="email" autoComplete="email" aria-invalid={Boolean(errors.email)} {...form.register("email")} />
              </FieldShell>
              <FieldShell id="password" label="Kata sandi" error={errors.password?.message}>
                <Input
                  id="password"
                  type="password"
                  autoComplete={mode === "signin" ? "current-password" : "new-password"}
                  aria-invalid={Boolean(errors.password)}
                  {...form.register("password")}
                />
              </FieldShell>
              {message && <Notice tone={message.tone}>{message.text}</Notice>}
              <Button type="submit" className="w-full" disabled={form.formState.isSubmitting}>
                {form.formState.isSubmitting && <Loader2 className="animate-spin" />}
                {mode === "signin" ? "Masuk" : "Daftar"}
              </Button>
            </form>
            <p className="mt-4 text-center text-sm text-muted-foreground">
              {mode === "signin" ? "Belum punya akun?" : "Sudah punya akun?"}{" "}
              <button
                type="button"
                className="font-medium text-primary hover:underline"
                onClick={() => {
                  setMode(mode === "signin" ? "signup" : "signin");
                  setMessage(null);
                }}
              >
                {mode === "signin" ? "Daftar" : "Masuk"}
              </button>
            </p>
          </CardContent>
        </Card>
        <p className="mt-6 text-center text-xs leading-relaxed text-muted-foreground">
          Alat bantu analisis fundamental, bukan nasihat investasi.
        </p>
      </div>
    </div>
  );
}
