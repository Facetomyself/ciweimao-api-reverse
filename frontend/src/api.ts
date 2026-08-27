import type { paths } from "./api/schema";

export type KnownApiPath = keyof paths;

export class ApiRequestError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
  }
}

export async function api<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, { ...init, headers });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) message = payload.detail;
    } catch {
      // 非 JSON 错误仍保留 HTTP 状态。
    }
    throw new ApiRequestError(response.status, message);
  }
  return (await response.json()) as T;
}

export function post<T>(path: string, body: unknown = {}): Promise<T> {
  return api<T>(path, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function downloadUrl(downloadId: string): string {
  return `/api/downloads/${encodeURIComponent(downloadId)}/file`;
}
