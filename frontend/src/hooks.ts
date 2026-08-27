import { useQuery, type QueryKey } from "@tanstack/react-query";
import { api } from "./api";

export function pollingInterval(): number {
  return typeof document !== "undefined" && document.visibilityState === "hidden"
    ? 30_000
    : 5_000;
}

export function usePollingQuery<T>(key: QueryKey, path: string) {
  return useQuery({
    queryKey: key,
    queryFn: () => api<T>(path),
    refetchInterval: pollingInterval,
    refetchIntervalInBackground: true,
  });
}
