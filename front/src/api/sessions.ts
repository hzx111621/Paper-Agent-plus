import type {
  SessionCreatePayload,
  SessionListPayload,
  SessionRunAccepted,
  SessionRunStartPayload,
  SessionRuntimeEvent,
  SessionThreadPayload,
} from "../types/sessions";
import { authHeaders } from "./auth";

type JsonObject = Record<string, unknown>;

export class ApiRequestError extends Error {
  status: number;

  /** 中文注释：把后端状态码一起保存下来，页面就能判断是 404、409 还是普通网络错误。 */
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
  }
}

const STREAM_EVENTS = [
  "runtime_event",
  "message",
  "reasoning_delta",
  "reasoning_end",
  "delta",
  "tool",
  "artifact",
  "status",
  "error",
  "turn_end",
] as const;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(init?.headers ?? {}),
    },
    ...init,
  });

  const data = (await response.json().catch(() => ({}))) as {
    error?: { message?: string };
    detail?: string | { message?: string };
  } & T;

  if (!response.ok) {
    const detailMessage = typeof data.detail === "string" ? data.detail : data.detail?.message;
    // 中文注释：这里保留 HTTP 状态码，调用方遇到“会话不存在”时可以主动把界面切回空白页。
    throw new ApiRequestError(data.error?.message || detailMessage || "请求失败", response.status);
  }

  return data as T;
}

export function listSessions(includeArchived = true): Promise<SessionListPayload> {
  return request<SessionListPayload>(`/api/sessions${includeArchived ? "?include_archived=1" : ""}`);
}

export function createSession(payload?: JsonObject): Promise<SessionCreatePayload> {
  return request<SessionCreatePayload>("/api/sessions", {
    method: "POST",
    body: JSON.stringify(payload ?? {}),
  });
}

export function fetchSessionThread(sessionKey: string): Promise<SessionThreadPayload> {
  return request<SessionThreadPayload>(`/api/sessions/${encodeURIComponent(sessionKey)}/webui-thread`);
}

export function deleteSession(sessionKey: string): Promise<{ deleted: boolean; key: string }> {
  return request<{ deleted: boolean; key: string }>(`/api/sessions/${encodeURIComponent(sessionKey)}`, {
    method: "DELETE",
  });
}

export function startSessionRun(
  sessionKey: string,
  payload: SessionRunStartPayload,
): Promise<SessionRunAccepted> {
  return request<SessionRunAccepted>(`/api/sessions/${encodeURIComponent(sessionKey)}/runs`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function cancelSessionRun(
  sessionKey: string,
  runId: string,
): Promise<{ session_key: string; run_id: string; status: string }> {
  return request<{ session_key: string; run_id: string; status: string }>(
    `/api/sessions/${encodeURIComponent(sessionKey)}/runs/${encodeURIComponent(runId)}/cancel`,
    { method: "POST", body: JSON.stringify({}) },
  );
}

export interface AuthenticatedEventStream {
  close: () => void;
}

export function subscribeSessionRun(
  streamUrl: string,
  handlers: {
    onEvent: (event: SessionRuntimeEvent) => void;
    onError?: (error: Event) => void;
    onOpen?: () => void;
  },
): AuthenticatedEventStream {
  // 中文说明：原生 EventSource 不能附加 Authorization 请求头，登录后会被后端拒绝。
  // 这里改用 fetch 读取同样的 SSE 数据，并保留 close() 方法，调用页面不用改关闭逻辑。
  const controller = new AbortController();
  const stream = { close: () => controller.abort() };

  void readEventStream(streamUrl, controller.signal, handlers);
  return stream;
}

async function readEventStream(
  streamUrl: string,
  signal: AbortSignal,
  handlers: {
    onEvent: (event: SessionRuntimeEvent) => void;
    onError?: (error: Event) => void;
    onOpen?: () => void;
  },
): Promise<void> {
  try {
    const response = await fetch(streamUrl, {
      headers: authHeaders(),
      signal,
    });
    if (!response.ok || !response.body) {
      throw new Error(`stream request failed: ${response.status}`);
    }

    handlers.onOpen?.();
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
      const chunks = buffer.split(/\r?\n\r?\n/);
      buffer = chunks.pop() ?? "";
      for (const chunk of chunks) {
        dispatchSseChunk(chunk, handlers.onEvent);
      }
      if (done) {
        break;
      }
    }
  } catch (error) {
    if (signal.aborted) {
      return;
    }
    handlers.onError?.(new Event(error instanceof Error ? error.message : "stream error"));
  }
}

function dispatchSseChunk(chunk: string, onEvent: (event: SessionRuntimeEvent) => void): void {
  const eventName = chunk.match(/^event:\s*(.+)$/m)?.[1]?.trim();
  if (eventName && !STREAM_EVENTS.includes(eventName as (typeof STREAM_EVENTS)[number])) {
    return;
  }
  const data = chunk
    .split(/\r?\n/)
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart())
    .join("\n");
  if (!data) {
    return;
  }
  try {
    onEvent(JSON.parse(data) as SessionRuntimeEvent);
  } catch {
    // 中文说明：单条数据格式异常时跳过这一条，避免整个实时阅读过程被中断。
  }
}
