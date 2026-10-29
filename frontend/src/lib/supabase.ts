import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { config, supabaseEnabled } from "./config";

// The anon key is public by design; Row Level Security protects the data.
export const supabase: SupabaseClient | null = supabaseEnabled
  ? createClient(config.supabaseUrl, config.supabaseAnonKey, {
      auth: { persistSession: true, autoRefreshToken: true },
    })
  : null;

export async function getAccessToken(): Promise<string | null> {
  if (!supabase) return null;
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ?? null;
}
