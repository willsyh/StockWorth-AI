import type {
  AnalysisInput,
  AnalysisList,
  AnalysisRecord,
  AnalysisResult,
  HealthStatus,
  ImportPreview,
  InsightRecord,
  Quote,
} from "@/types/api";
import { config } from "./config";
import { getAccessToken } from "./supabase";

export interface ApiErrorDetail {
  field?: string | null;
  message: string;
}

export class ApiError extends Error {
  status: number;
  code: string;
  details: ApiErrorDetail[];

  constructor(status: number, code: string, message: string, details: unknown) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = Array.isArray(details) ? (details as ApiErrorDetail[]) : [];
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = await getAccessToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");

  let resp: Response;
  try {
    resp = await fetch(`${config.apiBaseUrl}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "network_error", "Server tidak dapat dihubungi. Pastikan backend berjalan.", null);
  }
  if (resp.status === 204) return undefined as T;
  const text = await resp.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = null;
  }
  if (!resp.ok) {
    const err = (body as { error?: { code?: string; message?: string; details?: unknown } } | null)?.error;
    throw new ApiError(
      resp.status,
      err?.code ?? "http_error",
      err?.message ?? `Permintaan gagal (${resp.status}).`,
      err?.details,
    );
  }
  return body as T;
}

export interface ListParams {
  q?: string;
  ticker?: string;
  fiscal_year?: number;
  period?: string;
  sort?: "asc" | "desc";
  limit?: number;
  offset?: number;
}

function qs(params: object): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export const api = {
  health: () => request<HealthStatus>("/api/health"),
  calculate: (input: AnalysisInput) =>
    request<AnalysisResult>("/api/analysis/calculate", { method: "POST", body: JSON.stringify(input) }),
  create: (input: AnalysisInput) =>
    request<AnalysisRecord>("/api/analysis", { method: "POST", body: JSON.stringify(input) }),
  list: (params: ListParams = {}) => request<AnalysisList>(`/api/analysis${qs(params)}`),
  stats: () => request<{ total_analyses: number; companies: number }>("/api/analysis/stats"),
  get: (id: string) => request<AnalysisRecord>(`/api/analysis/${encodeURIComponent(id)}`),
  remove: (id: string) => request<void>(`/api/analysis/${encodeURIComponent(id)}`, { method: "DELETE" }),
  createInsight: (id: string) =>
    request<InsightRecord>(`/api/analysis/${encodeURIComponent(id)}/insights`, { method: "POST" }),
  importFile: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<ImportPreview>("/api/analysis/import", { method: "POST", body: fd });
  },
  quote: (ticker: string) => request<Quote>(`/api/market/quote${qs({ ticker })}`),
  templateUrl: (format: "csv" | "xlsx") => `${config.apiBaseUrl}/api/analysis/import/template?format=${format}`,
};
