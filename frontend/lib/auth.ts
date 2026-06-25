const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";
const TOKEN_KEY = "equilibrium_auth_token";

export interface AuthUser {
  email: string;
  role: "user" | "admin";
  name: string;
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export function authHeaders(): HeadersInit {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function login(email: string, password: string): Promise<AuthUser> {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });

  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.detail || "Sign in failed.");
  }

  setToken(data.access_token);
  return data.user;
}

export async function fetchCurrentUser(): Promise<AuthUser | null> {
  const token = getToken();
  if (!token) return null;

  const res = await fetch(`${API_BASE}/auth/me`, {
    headers: authHeaders(),
  });

  if (!res.ok) {
    clearToken();
    return null;
  }

  return res.json();
}

export function logout(): void {
  clearToken();
}
