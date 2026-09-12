import type { NextRequest } from "next/server";
import { setAccessToken, getAccessToken } from "@/lib/auth-client";

const API_BASE = process.env.API_INTERNAL_URL || "http://localhost:8000";

export type ApiProblem = {
  code?: string;
  detail?: string;
  title?: string;
  status?: number;
  message?: string;
};

export function rewriteUpstreamCookies(setCookieHeaders: string[]): string[] {
  return setCookieHeaders.map((cookie) =>
    cookie
      .replace(/Path=\/api\/v1\/auth/gi, "Path=/")
      .replace(/Domain=[^;]+;?\s*/gi, ""),
  );
}

export function collectSetCookies(headers: Headers): string[] {
  const anyHeaders = headers as Headers & { getSetCookie?: () => string[] };
  if (typeof anyHeaders.getSetCookie === "function") {
    return anyHeaders.getSetCookie();
  }
  const single = headers.get("set-cookie");
  return single ? [single] : [];
}

export async function proxyToApi(
  path: string,
  init: RequestInit & { cookie?: string } = {},
): Promise<Response> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (init.cookie) headers.set("Cookie", init.cookie);

  const upstream = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });

  const body = await upstream.text();
  const out = new Headers();
  const ct = upstream.headers.get("content-type");
  if (ct) out.set("content-type", ct);

  for (const c of rewriteUpstreamCookies(collectSetCookies(upstream.headers))) {
    out.append("Set-Cookie", c);
  }

  return new Response(body, { status: upstream.status, headers: out });
}

export function cookieHeaderFromRequest(req: NextRequest): string {
  return req.headers.get("cookie") || "";
}

export async function parseApiJson<T>(res: Response): Promise<{ data?: T; error?: ApiProblem }> {
  const text = await res.text();
  let json: unknown = null;
  try {
    json = text ? JSON.parse(text) : null;
  } catch {
    return { error: { detail: "Unexpected response from server.", status: res.status } };
  }
  if (!res.ok) {
    const problem = (json as ApiProblem) || {};
    return {
      error: {
        ...problem,
        detail: problem.detail || problem.message || "Request failed",
        status: res.status,
      },
    };
  }
  return { data: json as T };
}

export function accessCookie(value: string, maxAge = 900): string {
  const secure = process.env.NODE_ENV === "production" ? "; Secure" : "";
  return `aarogya_access=${value}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${maxAge}${secure}`;
}

export function clearAccessCookie(): string {
  const secure = process.env.NODE_ENV === "production" ? "; Secure" : "";
  return `aarogya_access=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0${secure}`;
}

export async function refreshAccessToken(): Promise<string | null> {
  try {
    const res = await fetch("/api/v1/auth/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({}),
      cache: "no-store",
    });
    const text = await res.text();
    let json: unknown = null;
    try {
      json = text ? JSON.parse(text) : null;
    } catch {
      return null;
    }
    if (!res.ok) return null;
    const data = json as { access_token?: string } | null;
    const token = data?.access_token;
    if (token) {
      setAccessToken(token);
      return token;
    }
    return null;
  } catch {
    return null;
  }
}

export async function apiClient<T>(
  path: string,
  init: RequestInit & { retryOnAuthError?: boolean } = {},
): Promise<{ data?: T; error?: ApiProblem }> {
  const retryOnAuthError = init.retryOnAuthError !== false;
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const token = getAccessToken();
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const res = await fetch(path, { ...init, headers, credentials: "include" });
  const text = await res.text();
  let json: unknown = null;
  try {
    json = text ? JSON.parse(text) : null;
  } catch {
    return { error: { detail: "Unexpected response.", status: res.status } };
  }
  if (!res.ok) {
    const err = (json as { detail?: string; code?: string }) || {};
    const problem = {
      detail: err.detail || "Request failed",
      status: res.status,
      code: err.code,
    };
    if (res.status === 401 && retryOnAuthError) {
      const newToken = await refreshAccessToken();
      if (newToken) {
        headers.set("Authorization", `Bearer ${newToken}`);
        const retry = await fetch(path, { ...init, headers, credentials: "include" });
        const retryText = await retry.text();
        let retryJson: unknown = null;
        try {
          retryJson = retryText ? JSON.parse(retryText) : null;
        } catch {
          return { error: { detail: "Unexpected response.", status: retry.status } };
        }
        if (retry.ok) {
          return { data: retryJson as T };
        }
        const retryErr = (retryJson as { detail?: string; code?: string }) || {};
        return {
          error: {
            detail: retryErr.detail || problem.detail,
            status: retry.status,
            code: retryErr.code || problem.code,
          },
        };
      }
    }
    return { error: problem };
  }
  return { data: json as T };
}
