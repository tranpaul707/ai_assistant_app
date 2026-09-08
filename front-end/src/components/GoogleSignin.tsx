import { useState } from "react";
import { GoogleLogin } from "@react-oauth/google";
import type { CredentialResponse } from "@react-oauth/google";

/** Profile fields inside a Google ID token (display only — verify tokens on the backend). */
interface GoogleIdTokenPayload {
  sub: string;
  name?: string;
  email?: string;
  picture?: string;
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

const GoogleSignin = () => {
  const [user, setUser] = useState<GoogleIdTokenPayload | null>(null);

  function handleSuccess(response: CredentialResponse) {
    // Modern GIS gives an ID token string, not a gapi GoogleUser.
    if (!response.credential) return;

    const profile = parseIdTokenPayload(response.credential);
    if (!profile) return;

    setUser(profile);
    // Keep the credential for a future /auth/google backend verify call.
    // Do not put tokens in LangGraph / Redis / Chroma / prompts.
    console.log("Google ID token received for", profile.email ?? profile.sub);
  }

  if (user) {
    return (
      <div className="google-signin google-signin--signed-in">
        {user.picture && (
          <img
            src={user.picture}
            alt=""
            className="google-signin__avatar"
            referrerPolicy="no-referrer"
          />
        )}
        <span className="google-signin__name">{user.name ?? user.email}</span>
      </div>
    );
  }

  return (
    <div className="google-signin">
      <GoogleLogin
        onSuccess={handleSuccess}
        onError={() => console.error("Google sign-in failed")}
        useOneTap={false}
      />
    </div>
  );
};

export default GoogleSignin;
