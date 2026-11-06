import type {
  BenchResults,
  CaseDetailResponse,
  CaseListItem,
  VerdictLabel,
} from "./types";

export const API_BASE: string = (
  import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8787"
).replace(/\/+$/, "");

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function errorMessage(res: Response): Promise<string> {
  try {
    const body: unknown = await res.json();
    if (body && typeof body === "object" && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      return typeof detail === "string" ? detail : JSON.stringify(detail);
    }
  } catch {
    // fall through to the status text
  }
  return res.statusText || `HTTP ${res.status}`;
}

async function request(path: string, init?: RequestInit): Promise<Response> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) throw new ApiError(res.status, await errorMessage(res));
  return res;
}

export async function listCases(verdict?: VerdictLabel): Promise<CaseListItem[]> {
  const query = verdict ? `?verdict=${encodeURIComponent(verdict)}` : "";
  return (await request(`/api/cases${query}`)).json() as Promise<CaseListItem[]>;
}

export async function getCase(id: string): Promise<CaseDetailResponse> {
  return (await request(`/api/cases/${encodeURIComponent(id)}`)).json() as Promise<CaseDetailResponse>;
}

export function evidenceUrl(id: string): string {
  return `${API_BASE}/api/cases/${encodeURIComponent(id)}/evidence.md`;
}

export async function getEvidenceMarkdown(id: string): Promise<string> {
  return (await request(`/api/cases/${encodeURIComponent(id)}/evidence.md`)).text();
}

export async function getBenchmark(): Promise<BenchResults> {
  return (await request("/api/benchmark/latest")).json() as Promise<BenchResults>;
}
