/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import type { Session, User } from "@supabase/supabase-js";
import { useQueryClient } from "@tanstack/react-query";
import { supabase } from "@/lib/supabase";
import { supabaseEnabled } from "@/lib/config";

interface AuthContextValue {
  /** false when Supabase is not configured (local development mode). */
  enabled: boolean;
  loading: boolean;
  user: User | null;
  session: Session | null;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string) => Promise<{ needsConfirmation: boolean }>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function translateAuthError(message: string): string {
  const m = message.toLowerCase();
  if (m.includes("invalid login")) return "Email atau kata sandi salah.";
  if (m.includes("email not confirmed")) return "Email belum dikonfirmasi. Buka link konfirmasi di email Anda, lalu masuk.";
  if (m.includes("already registered") || m.includes("already been registered")) return "Email sudah terdaftar. Silakan masuk.";
  if (m.includes("rate limit") || m.includes("too many"))
    return "Batas pengiriman email Supabase tercapai (SMTP bawaan hanya beberapa email per jam). Tunggu, atau atur SMTP sendiri / matikan 'Confirm email' di Supabase.";
  if (m.includes("sending") && m.includes("email"))
    return "Supabase gagal mengirim email konfirmasi. SMTP bawaan hanya mengirim ke email anggota tim project; atur SMTP sendiri atau matikan 'Confirm email' untuk pengembangan.";
  if (m.includes("not authorized") || (m.includes("email address") && m.includes("invalid")))
    return "Email ditolak Supabase. Dengan SMTP bawaan, hanya email anggota tim project yang bisa menerima email; atur SMTP sendiri atau matikan 'Confirm email'.";
  if (m.includes("signups not allowed") || m.includes("signup is disabled")) return "Pendaftaran akun baru dinonaktifkan di pengaturan Supabase.";
  if (m.includes("password")) return `Kata sandi ditolak: ${message}`;
  if (m.includes("failed to fetch") || m.includes("network")) return "Tidak dapat menghubungi Supabase. Periksa koneksi dan VITE_SUPABASE_URL.";
  // Show the original message instead of hiding it behind a generic one.
  return `Autentikasi gagal: ${message}`;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(supabaseEnabled);
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!supabase) return;
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setLoading(false);
    });
    const { data } = supabase.auth.onAuthStateChange((_event, s) => {
      setSession(s);
      if (!s) queryClient.clear(); // never keep another user's data cached
    });
    return () => data.subscription.unsubscribe();
  }, [queryClient]);

  const value = useMemo<AuthContextValue>(
    () => ({
      enabled: supabaseEnabled,
      loading,
      session,
      user: session?.user ?? null,
      async signIn(email, password) {
        if (!supabase) return;
        const { error } = await supabase.auth.signInWithPassword({ email, password });
        if (error) throw new Error(translateAuthError(error.message));
      },
      async signUp(email, password) {
        if (!supabase) return { needsConfirmation: false };
        const { data, error } = await supabase.auth.signUp({
          email,
          password,
          // Confirmation link returns to this app (add this origin to Supabase Auth > URL Configuration).
          options: { emailRedirectTo: window.location.origin },
        });
        if (error) throw new Error(translateAuthError(error.message));
        return { needsConfirmation: !data.session };
      },
      async signOut() {
        if (!supabase) return;
        await supabase.auth.signOut();
        queryClient.clear();
      },
    }),
    [loading, session, queryClient],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
