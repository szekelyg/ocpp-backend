// frontend/src/hooks/useAuth.js
// A bejelentkezett fiók (/api/me) React-oldali állapota – Energiafelhő-fiók (Keycloak).
import { useCallback, useEffect, useState } from "react";
import { apiFetch, authSource, isLoggedIn, logout as doLogout, onAuthChange } from "../utils/auth";

export default function useAuth() {
  const [me, setMe] = useState(null);          // { email, name, profile, keycloak_linked, auth_source }
  const [loading, setLoading] = useState(isLoggedIn());
  const [source, setSource] = useState(authSource());   // "keycloak" | null

  const reload = useCallback(async () => {
    setSource(authSource());
    if (!isLoggedIn()) { setMe(null); setLoading(false); return; }
    setLoading(true);
    try {
      const res = await apiFetch("/api/me", { headers: { Accept: "application/json" } });
      if (!res.ok) { setMe(null); return; }
      setMe(await res.json());
    } catch {
      setMe(null);
    } finally {
      setLoading(false);
      setSource(authSource());
    }
  }, []);

  useEffect(() => {
    reload();
    return onAuthChange(reload);
  }, [reload]);

  return {
    me,
    loading,
    loggedIn: !!me,
    source,
    reload,
    logout: (opts) => doLogout(opts),
  };
}
