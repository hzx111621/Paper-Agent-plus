import type { PaperRecord } from "../types/sessions";
import { authHeaders } from "./auth";

type PaperListPayload = { papers: PaperRecord[]; total: number; page: number; page_size: number; pages: number; stats?: { searched: number; selected: number; read_success: number; read_failed: number } };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...authHeaders(), ...(init?.headers ?? {}) },
    ...init,
  });
  const data = (await response.json().catch(() => ({}))) as { error?: { message?: string }; detail?: string } & T;
  if (!response.ok) throw new Error(data.error?.message || data.detail || "请求失败");
  return data as T;
}

function query(params: Record<string, string | number | boolean | undefined>) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value !== undefined && value !== "") search.set(key, String(value));
  return search.toString();
}

export function listSessionPapers(sessionKey: string, params: Record<string, string | number | boolean | undefined> = {}) {
  const suffix = query(params);
  return request<PaperListPayload>(`/api/sessions/${encodeURIComponent(sessionKey)}/papers${suffix ? `?${suffix}` : ""}`);
}

export function listLibrary(params: Record<string, string | number | boolean | undefined> = {}) {
  const suffix = query(params);
  return request<PaperListPayload>(`/api/library${suffix ? `?${suffix}` : ""}`);
}

export function patchPaper(paperId: string, patch: Partial<PaperRecord>) {
  return request<{ paper: PaperRecord }>(`/api/library/${encodeURIComponent(paperId)}`, { method: "PATCH", body: JSON.stringify(patch) });
}

export function patchSessionPaper(sessionKey: string, paperId: string, patch: Partial<PaperRecord>) {
  return request<{ paper: PaperRecord }>(`/api/sessions/${encodeURIComponent(sessionKey)}/papers/${encodeURIComponent(paperId)}`, { method: "PATCH", body: JSON.stringify(patch) });
}

export async function uploadPdf(sessionKey: string, file: File) {
  const contentBase64 = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
    reader.onerror = () => reject(reader.error || new Error("读取 PDF 失败"));
    reader.readAsDataURL(file);
  });
  return request<{ paper: PaperRecord; warnings: string[] }>(`/api/sessions/${encodeURIComponent(sessionKey)}/uploads`, { method: "POST", body: JSON.stringify({ filename: file.name, content_base64: contentBase64 }) });
}

export function exportSessionUrl(sessionKey: string, format: string) {
  return `/api/sessions/${encodeURIComponent(sessionKey)}/exports/${encodeURIComponent(format)}`;
}

export function renameSession(sessionKey: string, title: string) {
  return request<{ session: Record<string, unknown> }>(`/api/sessions/${encodeURIComponent(sessionKey)}/rename`, { method: "PATCH", body: JSON.stringify({ title }) });
}

export function archiveSession(sessionKey: string, archived = true) {
  return request<{ session: Record<string, unknown> }>(`/api/sessions/${encodeURIComponent(sessionKey)}/archive`, { method: "PATCH", body: JSON.stringify({ archived }) });
}

export function reanalyzePaper(sessionKey: string, paperId: string) {
  return request<{ run_id: string; stream_url: string }>(`/api/sessions/${encodeURIComponent(sessionKey)}/reanalyze/${encodeURIComponent(paperId)}`, { method: "POST", body: JSON.stringify({}) });
}
