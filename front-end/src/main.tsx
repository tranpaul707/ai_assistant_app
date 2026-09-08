import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { GoogleOAuthProvider } from "@react-oauth/google";
import "./index.css";
import App from "./App.tsx";
import "./App.css";

const clientId = import.meta.env.VITE_GOOGLE_CLIENT_ID as string | undefined;

if (!clientId) {
  console.warn(
    "VITE_GOOGLE_CLIENT_ID is missing. Add it to front-end/.env to enable Google sign-in."
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <GoogleOAuthProvider clientId={clientId ?? ""}>
      <App />
    </GoogleOAuthProvider>
  </StrictMode>
);
