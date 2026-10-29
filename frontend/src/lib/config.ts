// Public, build-time configuration. Only VITE_* variables reach the browser bundle;
// never put service-role keys or AI provider keys here.
export const config = {
  apiBaseUrl: (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") || "http://localhost:8000",
  supabaseUrl: ((import.meta.env.VITE_SUPABASE_URL as string | undefined) || "").trim(),
  supabaseAnonKey: ((import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined) || "").trim(),
};

function validateSupabase(): string | null {
  const { supabaseUrl: url, supabaseAnonKey: key } = config;
  if (!url && !key) return null; // local mode
  if (!url || !key) return "VITE_SUPABASE_URL dan VITE_SUPABASE_ANON_KEY harus diisi keduanya, atau dikosongkan keduanya.";
  if (url.startsWith("sb_") || url.startsWith("eyJ")) {
    return "VITE_SUPABASE_URL berisi API key, bukan URL. Isi dengan Project URL, contoh: https://abcdefgh.supabase.co";
  }
  try {
    const u = new URL(url);
    if (u.protocol !== "https:" && u.hostname !== "localhost" && u.hostname !== "127.0.0.1") {
      return "VITE_SUPABASE_URL harus diawali https://";
    }
    if (u.pathname !== "/" && u.pathname !== "") {
      return "VITE_SUPABASE_URL cukup berisi alamat project tanpa path (hapus /rest/v1 atau sejenisnya).";
    }
  } catch {
    return "VITE_SUPABASE_URL bukan URL yang valid. Contoh: https://abcdefgh.supabase.co";
  }
  return null;
}

/** Non-null when the Supabase settings are present but unusable. */
export const supabaseConfigError = validateSupabase();
export const supabaseEnabled = Boolean(config.supabaseUrl && config.supabaseAnonKey) && !supabaseConfigError;
