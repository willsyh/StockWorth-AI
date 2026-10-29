import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type ListParams } from "@/lib/api";
import { useAuth } from "@/app/auth";
import type { AnalysisInput } from "@/types/api";

/** Queries that touch private data wait until auth is resolved (or disabled in local mode). */
function usePrivateEnabled() {
  const auth = useAuth();
  return !auth.loading && (!auth.enabled || Boolean(auth.user));
}

export function useHealth() {
  return useQuery({ queryKey: ["health"], queryFn: api.health, staleTime: 60_000, retry: 1 });
}

export function useAnalyses(params: ListParams = {}) {
  const enabled = usePrivateEnabled();
  return useQuery({ queryKey: ["analyses", params], queryFn: () => api.list(params), enabled });
}

export function useStats() {
  const enabled = usePrivateEnabled();
  return useQuery({ queryKey: ["analyses", "stats"], queryFn: api.stats, enabled });
}

export function useAnalysis(id: string | undefined) {
  const enabled = usePrivateEnabled() && Boolean(id);
  return useQuery({ queryKey: ["analysis", id], queryFn: () => api.get(id!), enabled, retry: false });
}

export function useCreateAnalysis() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: AnalysisInput) => api.create(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["analyses"] }),
  });
}

export function useDeleteAnalysis() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.remove(id),
    onSuccess: (_d, id) => {
      qc.removeQueries({ queryKey: ["analysis", id] });
      return qc.invalidateQueries({ queryKey: ["analyses"] });
    },
  });
}

export function useCreateInsight(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.createInsight(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["analysis", id] }),
  });
}
