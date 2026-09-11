import { useState, useEffect, useCallback } from "react";
import { GoogleLogin, googleLogout } from "@react-oauth/google";
import type { CredentialResponse } from "@react-oauth/google";
import { API_BASE, authHeaders, getIdToken, setIdToken } from "../api/client";

/** Profile fields from a Google ID token (display only — verify tokens on the backend). */
export interface GoogleIdTokenPayload {
  sub: string;
  name?: string;
  email?: string;
  picture?: string;
  exp?: number;
}

function parseIdTokenPayload(credential: string): GoogleIdTokenPayload | null {
  try {
    const payload = credential.split(".")[1];
    if (!payload) return null;
    const normalized = payload.replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(atob(normalized)) as GoogleIdTokenPayload;
  } catch {
    return null;
  }
}

/** Prefer JWT exp when present, but never exceed ~1 hour from now. */
function sessionTtlMsFromToken(credential: string): number {
  const oneHour = 60 * 60 * 1000;
  const profile = parseIdTokenPayload(credential);
  if (profile?.exp) {
    const untilExp = profile.exp * 1000 - Date.now();
    if (untilExp > 0) return Math.min(untilExp, oneHour);
  }
  return oneHour;
}

interface GoogleSigninProps {
  onAuthChange?: (user: GoogleIdTokenPayload | null, idToken: string | null) => void;
}

const GoogleSignin = ({ onAuthChange }: GoogleSigninProps) => {
  const [user, setUser] = useState<GoogleIdTokenPayload | null>(null);
  const [gmailConnected, setGmailConnected] = useState(false);

  const refreshGmailStatus = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/auth/gmail/status`, {
        headers: { ...authHeaders() },
      });
      if (!response.ok) {
        setGmailConnected(false);
        return;
      }
      const data = await response.json();
      setGmailConnected(Boolean(data.connected));
    } catch {
      setGmailConnected(false);
    }
  }, []);

  // Restore signed-in UI after refresh if the stored session is still valid.
  useEffect(() => {
    const token = getIdToken();
    if (!token) return;
    const profile = parseIdTokenPayload(token);
    if (!profile) {
      setIdToken(null);
      return;
    }
    setUser(profile);
    onAuthChange?.(profile, token);
    // Intentionally run once on mount to restore session.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const gmail = params.get("gmail");
    if (gmail === "connected") {
      // Allow session restore to land first, then refresh Gmail status.
      window.setTimeout(() => void refreshGmailStatus(), 0);
      window.history.replaceState({}, "", window.location.pathname);
    } else if (gmail === "error") {
      const reason = params.get("reason") || "unknown";
      console.error("Gmail connect failed:", reason);
      window.alert(`Gmail connect failed (${reason}). Try Connect Gmail again.`);
      window.history.replaceState({}, "", window.location.pathname);
    }
  }, [refreshGmailStatus]);

  useEffect(() => {
    if (user) void refreshGmailStatus();
  }, [user, refreshGmailStatus]);

  function handleSuccess(response: CredentialResponse) {
    if (!response.credential) return;

    const profile = parseIdTokenPayload(response.credential);
    if (!profile) return;

    setIdToken(response.credential, sessionTtlMsFromToken(response.credential));
    setUser(profile);
    onAuthChange?.(profile, response.credential);
  }

  function handleSignOut() {
    googleLogout();
    setIdToken(null);
    setUser(null);
    setGmailConnected(false);
    onAuthChange?.(null, null);
  }

  function connectGmail() {
    const token = getIdToken();
    if (!token) {
      console.error("Sign in with Google before connecting Gmail.");
      return;
    }
    const params = new URLSearchParams();
    if (user?.email) params.set("login_hint", user.email);
    // Browser navigation cannot send Authorization; bind OAuth to this GIS user.
    params.set("id_token", token);
    window.location.href = `${API_BASE}/auth/gmail/start?${params.toString()}`;
  }

  if (user) {
    return (
      <div className="google-signin google-signin--signed-in" title={user.email}>
        {user.picture ? (
          <img
            src={user.picture}
            alt=""
            className="google-signin__avatar"
            referrerPolicy="no-referrer"
          />
        ) : (
          <span className="google-signin__avatar google-signin__avatar--fallback">
            {(user.name ?? user.email ?? "?").charAt(0).toUpperCase()}
          </span>
        )}
        <div className="google-signin__meta">
          <span className="google-signin__status">Signed in</span>
          <span className="google-signin__name">
            {user.name ?? user.email ?? "Google user"}
          </span>
          <span className="google-signin__gmail">
            {gmailConnected ? "Gmail connected" : "Gmail not connected"}
          </span>
        </div>
        {!gmailConnected && (
          <button type="button" className="google-signin__sign-out" onClick={connectGmail}>
            Connect Gmail
          </button>
        )}
        <button type="button" className="google-signin__sign-out" onClick={handleSignOut}>
          Sign out
        </button>
      </div>
    );
  }

  return (
    <div className="google-signin">
      <GoogleLogin
        onSuccess={handleSuccess}
        onError={() => {
          console.error(
            "Google login failed. Check VITE_GOOGLE_CLIENT_ID and Authorized JavaScript origins."
          );
        }}
      />
    </div>
  );
};

export default GoogleSignin;
