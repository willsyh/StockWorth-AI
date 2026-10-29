import { lazy, Suspense, type ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AppShell } from "@/components/layout/AppShell";
import { Skeleton } from "@/components/ui/misc";
import { ApiError } from "@/lib/api";
import { AuthProvider, useAuth } from "./auth";
import { ThemeProvider, useTheme } from "./theme";

const DashboardPage = lazy(() => import("@/pages/DashboardPage"));
const StocksPage = lazy(() => import("@/pages/StocksPage"));
const NewAnalysisPage = lazy(() => import("@/pages/NewAnalysisPage"));
const AnalysisReportPage = lazy(() => import("@/pages/AnalysisReportPage"));
const HistoryPage = lazy(() => import("@/pages/HistoryPage"));
const SettingsPage = lazy(() => import("@/pages/SettingsPage"));
const LoginPage = lazy(() => import("@/pages/LoginPage"));
const NotFoundPage = lazy(() => import("@/pages/NotFoundPage"));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      retry: (count, error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 2,
    },
  },
});

function PageFallback() {
  return (
    <div className="space-y-4" aria-busy="true" aria-label="Memuat">
      <Skeleton className="h-8 w-56" />
      <Skeleton className="h-4 w-80" />
      <div className="grid gap-4 sm:grid-cols-3">
        <Skeleton className="h-28" />
        <Skeleton className="h-28" />
        <Skeleton className="h-28" />
      </div>
    </div>
  );
}

function RequireAuth({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const location = useLocation();
  if (!auth.enabled) return <>{children}</>;
  if (auth.loading) return <PageFallback />;
  if (!auth.user) return <Navigate to="/masuk" replace state={{ from: location.pathname }} />;
  return <>{children}</>;
}

function ThemedToaster() {
  const { resolvedTheme } = useTheme();
  return <Toaster theme={resolvedTheme} position="top-center" richColors closeButton />;
}

export function App() {
  return (
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <TooltipProvider delayDuration={200}>
            <BrowserRouter>
              <Suspense fallback={<div className="p-8"><PageFallback /></div>}>
                <Routes>
                  <Route path="/masuk" element={<LoginPage />} />
                  <Route
                    element={
                      <RequireAuth>
                        <AppShell />
                      </RequireAuth>
                    }
                  >
                    <Route index element={<Suspense fallback={<PageFallback />}><DashboardPage /></Suspense>} />
                    <Route path="saham" element={<Suspense fallback={<PageFallback />}><StocksPage /></Suspense>} />
                    <Route path="saham/:ticker" element={<Suspense fallback={<PageFallback />}><HistoryPage /></Suspense>} />
                    <Route path="analisis/baru" element={<Suspense fallback={<PageFallback />}><NewAnalysisPage /></Suspense>} />
                    <Route path="analisis/:id" element={<Suspense fallback={<PageFallback />}><AnalysisReportPage /></Suspense>} />
                    <Route path="riwayat" element={<Suspense fallback={<PageFallback />}><HistoryPage /></Suspense>} />
                    <Route path="pengaturan" element={<Suspense fallback={<PageFallback />}><SettingsPage /></Suspense>} />
                    <Route path="*" element={<NotFoundPage />} />
                  </Route>
                </Routes>
              </Suspense>
            </BrowserRouter>
            <ThemedToaster />
          </TooltipProvider>
        </AuthProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}
