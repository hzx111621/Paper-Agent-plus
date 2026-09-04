import type { AuthPayload, AuthUser } from "../types/auth";

const AUTH_TOKEN_KEY = "pa.auth.token";

type ErrorPayload = {
  error?: { message?: string };
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(init?.headers ?? {}),
    },
    ...init,
  });
  const data = (await response.json().catch(() => ({}))) as ErrorPayload & T;
  if (!response.ok) {
    throw new Error(data.error?.message || "请求失败");
  }
  return data as T;
}

export function getAuthToken(): string {
  return localStorage.getItem(AUTH_TOKEN_KEY) || "";
}

export function setAuthToken(token: string): void {
  localStorage.setItem(AUTH_TOKEN_KEY, token);
}

export function clearAuthToken(): void {
  localStorage.removeItem(AUTH_TOKEN_KEY);
}

export function authHeaders(): Record<string, string> {
  const token = getAuthToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function registerAccount(username: string, password: string): Promise<AuthPayload> {
  const payload = await request<AuthPayload>("/api/auth/register", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  setAuthToken(payload.token);
  return payload;
}

export async function loginAccount(username: string, password: string): Promise<AuthPayload> {
  const payload = await request<AuthPayload>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  setAuthToken(payload.token);
  return payload;
}

export function getCurrentUser(): Promise<{ user: AuthUser }> {
  return request<{ user: AuthUser }>("/api/auth/me");
}

export async function logoutAccount(): Promise<void> {
  try {
    if (getAuthToken()) {
      await request<{ logged_out: boolean }>("/api/auth/logout", { method: "POST" });
    }
  } finally {
    clearAuthToken();
  }
}

export function changePassword(oldPassword: string, newPassword: string) {
  return request<{ changed: boolean }>("/api/auth/password", {
    method: "POST",
    body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
  });
}

export function listAuthTokens() {
  return request<{ tokens: Array<{ token_hash: string; created_at: string; expires_at: string }> }>("/api/auth/tokens");
}

export function revokeOtherTokens() {
  return request<{ revoked: boolean }>("/api/auth/tokens/others", { method: "DELETE" });
}

export function deleteAccount(password: string) {
  return request<{ deleted: boolean }>("/api/auth/account", { method: "DELETE", body: JSON.stringify({ password }) });
}

export function requestPasswordReset(username: string) {
  return request<{ reset_code: string; expires_in: number }>("/api/auth/forgot-password", { method: "POST", body: JSON.stringify({ username }) });
}

export function resetPassword(username: string, resetCode: string, newPassword: string) {
  return request<{ reset: boolean }>("/api/auth/reset-password", { method: "POST", body: JSON.stringify({ username, reset_code: resetCode, new_password: newPassword }) });
}
