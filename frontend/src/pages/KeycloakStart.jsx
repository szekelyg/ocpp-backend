// frontend/src/pages/KeycloakStart.jsx
// /auth/keycloak?return_to=/toltesek — a portál (my.) ide linkel. A helyi tokeneket eldobja, és a
// közös fiókkal léptet be: élő SSO-munkamenetnél ez egy láthatatlan oda-vissza a Keycloakhoz, és
// a portálon belépett felhasználó lesz belépve (2026-10-16: korábban a régi fiók maradt).
import { useEffect, useRef, useState } from "react";
import AppHeader from "../components/ui/AppHeader";
import { switchToKeycloakUser } from "../utils/auth";

export default function KeycloakStart() {
  const [err, setErr] = useState("");
  const ranRef = useRef(false);

  useEffect(() => {
    if (ranRef.current) return;
    ranRef.current = true;
    const returnTo = new URLSearchParams(window.location.search).get("return_to") || "/toltesek";
    switchToKeycloakUser({ returnTo }).catch((e) => setErr(e?.message || "A belépés nem indítható."));
  }, []);

  return (
    <div className="min-h-screen flex flex-col">
      <AppHeader />
      <div className="flex-1 flex items-center justify-center p-6">
        <div className="max-w-md w-full card cardBody text-center space-y-4">
          {err ? (
            <>
              <div className="text-lg font-semibold text-rose-600">A belépés nem indítható</div>
              <p className="text-ink-soft text-sm">{err}</p>
              <a href="/" className="btn btnGhost inline-flex">← Vissza a töltőkhöz</a>
            </>
          ) : (
            <div className="text-lg font-semibold text-ink">Belépés az Energiafelhő-fiókkal…</div>
          )}
        </div>
      </div>
    </div>
  );
}
