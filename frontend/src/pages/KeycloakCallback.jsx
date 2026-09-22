// frontend/src/pages/KeycloakCallback.jsx
// A Keycloak ide irányít vissza (?code=&state=). Itt történik a PKCE code → token csere,
// aztán megyünk oda, ahonnan a belépés indult (pl. vissza a töltő fizetési űrlapjára).
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import AppHeader from "../components/ui/AppHeader";
import { completeKeycloakLogin } from "../utils/auth";

export default function KeycloakCallback() {
  const navigate = useNavigate();
  const [err, setErr] = useState("");
  const ranRef = useRef(false);

  useEffect(() => {
    // StrictMode dev-ben kétszer futtatná; a code egyszer használatos.
    if (ranRef.current) return;
    ranRef.current = true;
    (async () => {
      try {
        const returnTo = await completeKeycloakLogin(window.location.search);
        navigate(returnTo, { replace: true });
      } catch (e) {
        setErr(e?.message || "A belépés nem sikerült.");
      }
    })();
  }, [navigate]);

  return (
    <div className="min-h-screen flex flex-col">
      <AppHeader />
      <div className="flex-1 flex items-center justify-center p-6">
        <div className="max-w-md w-full card cardBody text-center space-y-4">
          {err ? (
            <>
              <div className="text-3xl">⚠️</div>
              <div className="text-lg font-semibold text-rose-600">A belépés nem sikerült</div>
              <p className="text-ink-soft text-sm">{err}</p>
              <div className="flex gap-2 justify-center">
                <a href="/" className="btn btnGhost inline-flex">← Vissza a töltőkhöz</a>
                <a href="/toltesek" className="btn btnPrimary inline-flex">Újra próbálom</a>
              </div>
            </>
          ) : (
            <>
              <div className="text-lg font-semibold text-ink">Belépés folyamatban…</div>
              <p className="text-ink-soft text-sm">Az Energiafelhő-fiók ellenőrzése.</p>
              <div className="flex justify-center gap-1.5">
                {["bg-brand-yellow", "bg-brand-blue", "bg-brand-green"].map((c, i) => (
                  <div key={i} className={`w-2 h-2 rounded-full animate-bounce ${c}`}
                    style={{ animationDelay: `${i * 0.15}s` }} />
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
