const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

function authHeaders(): HeadersInit {
  const token = typeof window !== "undefined" ? localStorage.getItem("nutribot_token") : null;
  return {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { ...authHeaders(), ...(options.headers ?? {}) },
  });
  const data = await res.json().catch(() => ({ detail: "Request failed" }));
  if (!res.ok) throw new Error(data.detail ?? `HTTP ${res.status}`);
  return data as T;
}

// ── Auth ─────────────────────��───────────────────────────���─────────────────────

export type AuthUser = {
  id: string;
  email: string;
  full_name: string;
  gender?: string;
  age?: number;
  height_cm?: number;
  weight_kg?: number;
  medical_conditions: string[];
  allergies: string[];
  medications?: string;
  activity_level?: string;
  diet_type?: string;
  goal?: string;
  bot_name: string;
  profile_complete: boolean;
};

export type TokenResponse = {
  access_token: string;
  token_type: string;
  user: AuthUser;
};

export async function register(
  email: string,
  password: string,
  full_name: string
): Promise<TokenResponse> {
  return request<TokenResponse>("/api/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password, full_name }),
  });
}

export async function login(email: string, password: string): Promise<TokenResponse> {
  return request<TokenResponse>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function getGoogleAuthUrl(): string {
  const redirectUri = `${window.location.origin}/auth/google/callback`;
  const clientId = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID ?? "";
  const params = new URLSearchParams({
    client_id: clientId,
    redirect_uri: redirectUri,
    response_type: "code",
    scope: "openid email profile",
    access_type: "offline",
  });
  return `https://accounts.google.com/o/oauth2/v2/auth?${params.toString()}`;
}

// ── Profile ─────────────────────────────────────────────────────────────────���──

export type ProfilePayload = {
  full_name: string;
  gender: string;
  age: number;
  height_cm: number;
  weight_kg: number;
  medical_conditions: string[];
  allergies: string[];
  medications?: string;
  activity_level: string;
  diet_type: string;
  goal: string;
  bot_name: string;
};

export async function createProfile(payload: ProfilePayload): Promise<AuthUser> {
  return request<AuthUser>("/api/profile/create", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getMyProfile(): Promise<AuthUser> {
  return request<AuthUser>("/api/profile/me");
}

export async function updateProfile(payload: Partial<ProfilePayload>): Promise<AuthUser> {
  return request<AuthUser>("/api/profile/update", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

// ── Chat ───────────────────────────────────────────────────────────────────────

export type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  timestamp: string;
};

export type ChatResponse = {
  response: string;
  intent: string;
  plan_proposed: boolean;
  proposed_plan: Record<string, unknown> | null;
  session_id: string;
};

export async function sendMessage(
  userId: string,
  sessionId: string,
  message: string
): Promise<ChatResponse> {
  return request<ChatResponse>("/api/chat/message", {
    method: "POST",
    body: JSON.stringify({ user_id: userId, session_id: sessionId, message }),
  });
}

export async function getChatHistory(sessionId: string): Promise<{ session_id: string; messages: ChatMessage[] }> {
  return request(`/api/chat/history?session_id=${encodeURIComponent(sessionId)}`);
}

// ── Plans ──────────────────────────────────────────────────────────────────────

export type PlanAcceptResponse = {
  status: string;
  plan_id: string;
  message: string;
};

export async function acceptPlan(
  userId: string,
  sessionId: string,
  planData: Record<string, unknown>,
  calorieTarget: number,
  planSummary: string
): Promise<PlanAcceptResponse> {
  return request<PlanAcceptResponse>("/api/plans/accept", {
    method: "POST",
    body: JSON.stringify({
      user_id: userId,
      session_id: sessionId,
      plan_data: planData,
      calorie_target: calorieTarget,
      plan_summary: planSummary,
    }),
  });
}

export async function getSavedPlans(): Promise<{ plans: unknown[] }> {
  return request("/api/plans/saved");
}
