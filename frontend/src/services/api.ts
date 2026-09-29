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
  /** Locales the mic listens for (BCP-47, max 4). Empty = server default. */
  spoken_languages: string[];
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
  spoken_languages?: string[];
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

// ── Consent ────────────────────────────────────────────────────────────────────
// Storing medical conditions requires explicit, recorded consent (backend
// returns 403 otherwise). The profile form grants it before saving.

export type ConsentStatus = {
  consent_type: string;
  granted: boolean;
  last_updated?: string | null;
};

export async function getConsentStatus(): Promise<ConsentStatus> {
  return request<ConsentStatus>("/api/consent/status");
}

export async function grantConsent(): Promise<ConsentStatus> {
  return request<ConsentStatus>("/api/consent/grant", { method: "POST" });
}

// ── Chat ───────────────────────────────────────────────────────────────────────

export type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  timestamp: string;
};

export type RagSource = {
  source: string;
  condition: string;
};

export type ChatResponse = {
  response: string;
  intent: string;
  plan_proposed: boolean;
  proposed_plan: Record<string, unknown> | null;
  session_id: string;
  rag_sources: RagSource[];
  /** Language the reply is written in (Translator code: "en", "hi", "ml", "fr"). */
  language: string;
  /** The English the pipeline processed, when the message was translated. */
  message_english: string | null;
};

export async function sendMessage(
  userId: string,
  sessionId: string,
  message: string,
  /** BCP-47 locale from speech recognition ("hi-IN"); omit for typed text. */
  language?: string
): Promise<ChatResponse> {
  return request<ChatResponse>("/api/chat/message", {
    method: "POST",
    body: JSON.stringify({ user_id: userId, session_id: sessionId, message, language: language ?? null }),
  });
}

/** Streaming counterpart of sendMessage, backed by /api/chat/message/stream
 *  (Server-Sent Events). `onProgress` fires once per completed pipeline
 *  stage with a short human label ("Building your response", ...) -- real
 *  stage completions, not a fake timer, so it tracks whatever's actually
 *  slow. Resolves with the exact same ChatResponse shape as sendMessage()
 *  once the `done` event arrives.
 *
 *  Uses raw fetch + a ReadableStream reader (not EventSource) because
 *  EventSource can't send the Authorization header or a POST body. */
export async function sendMessageStream(
  userId: string,
  sessionId: string,
  message: string,
  onProgress: (label: string) => void,
  language?: string
): Promise<ChatResponse> {
  const token = typeof window !== "undefined" ? localStorage.getItem("nutribot_token") : null;
  const res = await fetch(`${API_BASE}/api/chat/message/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ user_id: userId, session_id: sessionId, message, language: language ?? null }),
  });
  if (!res.ok || !res.body) {
    const data = await res.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(data.detail ?? `HTTP ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line; each frame is one `event:`
    // line and one `data:` line. The JSON payload is always single-line
    // (JSON.stringify/model_dump_json escape embedded newlines), so a
    // line-anchored regex is enough -- no SSE parsing library needed.
    let sepIndex: number;
    while ((sepIndex = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, sepIndex);
      buffer = buffer.slice(sepIndex + 2);
      const eventMatch = /^event:\s*(.+)$/m.exec(frame);
      const dataMatch = /^data:\s*(.+)$/m.exec(frame);
      if (!eventMatch || !dataMatch) continue;

      const eventType = eventMatch[1].trim();
      const data = JSON.parse(dataMatch[1]);
      if (eventType === "progress") {
        onProgress(data.label);
      } else if (eventType === "done") {
        return data as ChatResponse;
      } else if (eventType === "error") {
        throw new Error(data.detail ?? "Something went wrong generating a response.");
      }
    }
  }

  throw new Error("Connection closed before a response was received.");
}

/** Render a plan (proposed or accepted) to PDF on the server and hand the
 *  bytes back. Uses raw fetch because `request` assumes JSON. */
// ── Medical documents ────────────────────────────────────────────────────────

export type DocumentStatus = "uploaded" | "processing" | "processed" | "failed";

export type MedicalDocument = {
  id: string;
  filename: string;
  content_type: string;
  status: DocumentStatus;
  facts_extracted: number;
  error_message: string | null;
  uploaded_at: string;
  processed_at: string | null;
};

export async function listDocuments(): Promise<MedicalDocument[]> {
  return request<MedicalDocument[]>("/api/documents");
}

/** Multipart upload -- deliberately bypasses `request()`, which always sets
 *  Content-Type: application/json; a FormData body needs the browser to set
 *  its own Content-Type with the multipart boundary instead. */
export async function uploadDocument(file: File): Promise<{ id: string; status: DocumentStatus; facts_extracted: number }> {
  const token = typeof window !== "undefined" ? localStorage.getItem("nutribot_token") : null;
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/api/documents/upload`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    body: form,
  });
  const data = await res.json().catch(() => ({ detail: "Upload failed" }));
  if (!res.ok) throw new Error(data.detail ?? `HTTP ${res.status}`);
  return data;
}

export async function deleteDocument(documentId: string): Promise<{ status: string }> {
  return request(`/api/documents/${encodeURIComponent(documentId)}`, { method: "DELETE" });
}

export async function deleteDocumentsBatch(documentIds: string[]): Promise<{ deleted_count: number; not_found_ids: string[] }> {
  return request("/api/documents/delete-batch", {
    method: "POST",
    body: JSON.stringify({ document_ids: documentIds }),
  });
}

export async function clearAllDocuments(): Promise<{ deleted_count: number; not_found_ids: string[] }> {
  return request("/api/documents", { method: "DELETE" });
}

export async function downloadPlanPdf(plan: Record<string, unknown>): Promise<{ blob: Blob; filename: string }> {
  const res = await fetch(`${API_BASE}/api/plans/pdf`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ plan_data: plan }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({ detail: "Could not generate the PDF" }));
    throw new Error(data.detail ?? `HTTP ${res.status}`);
  }
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const match = /filename="?([^"]+)"?/.exec(disposition);
  return { blob: await res.blob(), filename: match?.[1] ?? "nutribot-meal-plan.pdf" };
}

// ── Speech ─────────────────────────────────────────────────────────────────────

export type SpeechTokenResponse = {
  token: string;
  region: string;
  expires_in_seconds: number;
  languages: string[];
};

export async function getSpeechToken(): Promise<SpeechTokenResponse> {
  return request<SpeechTokenResponse>("/api/speech/token");
}

export type SpokenLocale = { code: string; label: string };

export type SpokenLanguagesResponse = {
  supported: SpokenLocale[];
  default: string[];
  max_selectable: number;
};

export async function getSpokenLanguages(): Promise<SpokenLanguagesResponse> {
  return request<SpokenLanguagesResponse>("/api/speech/languages");
}

export async function getChatHistory(sessionId: string): Promise<{ session_id: string; messages: ChatMessage[] }> {
  return request(`/api/chat/history?session_id=${encodeURIComponent(sessionId)}`);
}

export type ChatSession = {
  session_id: string;
  started_at: string;
  preview: string;
  message_count: number;
};

export async function getChatSessions(): Promise<{ sessions: ChatSession[] }> {
  return request("/api/chat/sessions");
}

export async function deleteSession(sessionId: string): Promise<{ status: string }> {
  return request(`/api/chat/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
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
