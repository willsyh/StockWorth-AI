import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/inter";
import "./index.css";
import { App } from "./app/App";
import { supabaseConfigError } from "./lib/config";

function ConfigError({ message }: { message: string }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div role="alert" className="w-full max-w-lg rounded-lg border bg-card p-6 shadow-card">
        <h1 className="text-lg font-semibold">Konfigurasi Supabase belum benar</h1>
        <p className="mt-2 text-sm text-negative">{message}</p>
        <p className="mt-4 text-sm text-muted-foreground">
          Perbaiki di <code className="rounded bg-muted px-1">frontend/.env</code> atau{" "}
          <code className="rounded bg-muted px-1">frontend/.env.local</code>, lalu restart <code className="rounded bg-muted px-1">npm run dev</code>.
          Kosongkan kedua variabel Supabase untuk memakai mode lokal.
        </p>
      </div>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>{supabaseConfigError ? <ConfigError message={supabaseConfigError} /> : <App />}</StrictMode>,
);
