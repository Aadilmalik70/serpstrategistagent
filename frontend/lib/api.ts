import { getSession } from "next-auth/react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export class OperatorApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "OperatorApiError";
    this.status = status;
  }
}

export async function apiRequest(path: string, options?: RequestInit): Promise<Response> {
  const session = await getSession();
  if (!session?.accessToken || !session.workspaceId) {
    throw new OperatorApiError(
      session?.legacy
        ? "This temporary admin session cannot access tenant-scoped APIs. Sign in with a registered account."
        : "Authentication is required.",
      401,
    );
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
    throw new OperatorApiError(error.detail || `API error: ${response.status}`, response.status);
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
