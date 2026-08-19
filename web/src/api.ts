export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export interface Check {
  ok: boolean;
  detail: string;
}

export interface Health {
  status: "ok" | "degraded";
  version: string;
  checks: Record<string, Check>;
}

export async function fetchHealth(): Promise<Health> {
  // /health answers 503 when degraded, and that body is exactly what we want to
  // render, so this deliberately does not throw on a non-2xx status.
  const response = await fetch(`${API_BASE_URL}/health`);
  return (await response.json()) as Health;
}
