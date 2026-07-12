import { getSession } from "next-auth/react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export class OperatorApiError extends Error {
  status: number;
  code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = "OperatorApiError";
    this.status = status;
    this.code = code;
  }
}

export async function apiRequest(path: string, options?: RequestInit): Promise<Response> {
  const session = await getSession();
  if (!session?.accessToken || !session.workspaceId) {
    throw new OperatorApiError("Authentication is required.", 401);
  }

  const headers = new Headers(options?.headers);
  if (!headers.has("Content-Type") && options?.body) {
    headers.set("Content-Type", "application/json");
  }
  headers.set("Authorization", `Bearer ${session.accessToken}`);
  headers.set("X-Workspace-ID", session.workspaceId);

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
    cache: options?.cache ?? "no-store",
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    const detail = error.detail;
    const message =
      typeof detail === "string"
        ? detail
        : detail && typeof detail === "object" && typeof detail.message === "string"
          ? detail.message
          : `API error: ${response.status}`;
    const code =
      detail && typeof detail === "object" && typeof detail.code === "string"
        ? detail.code
        : undefined;
    throw new OperatorApiError(message, response.status, code);
  }
  return response;
}

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await apiRequest(path, options);
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export async function apiDownload(path: string): Promise<Blob> {
  const response = await apiRequest(path);
  return response.blob();
}
