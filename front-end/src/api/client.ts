/** Shared API base for local FastAPI. */
export const API_BASE = "http://127.0.0.1:8000";

const ID_TOKEN_KEY = "google_id_token";
const ID_TOKEN_EXPIRES_KEY = "google_id_token_expires_at";

/** Keep the GIS session for one hour across page refreshes. */
export const SESSION_TTL_MS = 60 * 60 * 1000;

export function getIdToken(): string | null {
  const token = localStorage.getItem(ID_TOKEN_KEY);
  const expiresRaw = localStorage.getItem(ID_TOKEN_EXPIRES_KEY);
  if (!token || !expiresRaw) {
    clearIdToken();
    return null;
  }

  const expiresAt = Number(expiresRaw);
  if (!Number.isFinite(expiresAt) || Date.now() >= expiresAt) {
    clearIdToken();
    return null;
  }

  return token;
}

export function setIdToken(token: string | null, ttlMs: number = SESSION_TTL_MS) {
  if (!token) {
    clearIdToken();
    return;
  }
  localStorage.setItem(ID_TOKEN_KEY, token);
  localStorage.setItem(ID_TOKEN_EXPIRES_KEY, String(Date.now() + ttlMs));
}

function clearIdToken() {
  localStorage.removeItem(ID_TOKEN_KEY);
  localStorage.removeItem(ID_TOKEN_EXPIRES_KEY);
  // Clear legacy sessionStorage key from earlier builds.
  sessionStorage.removeItem(ID_TOKEN_KEY);
}

export function authHeaders(): HeadersInit {
  const token = getIdToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}
