// frontend/src/components/ui/AccountLogin.jsx
// A fiókos belépés egyetlen útja: az egységes Energiafelhő-fiók (Keycloak). A gomb alatt
// egy mondat elmondja, hogy fiók nélkül is ugyanez az út (nincs külön regisztráció).
// A régi e-mail-kódos belépés 2026-09-22-én megszűnt. Vendégként (fiók nélkül) továbbra is
// lehet tölteni – az itt nem szerepel, azt a szülő űrlap adja.
import { useEffect, useState } from "react";
import KeycloakLoginButton from "./KeycloakLoginButton";
import { getKeycloakConfig } from "../../utils/auth";

export default function AccountLogin({ returnTo, disabled = false }) {
  const [enabled, setEnabled] = useState(null);   // null = még nem tudjuk
  const [err, setErr] = useState("");

  useEffect(() => {
    let alive = true;
    getKeycloakConfig().then((cfg) => { if (alive) setEnabled(!!cfg.enabled); });
    return () => { alive = false; };
  }, []);

  if (enabled === false) {
    return (
      <div className="text-xs text-ink-muted">
        A fiókos belépés jelenleg nem elérhető. Vendégként továbbra is tölthetsz.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <KeycloakLoginButton returnTo={returnTo} disabled={disabled} onError={setErr} />
      {enabled && (
        <p className="text-xs text-ink-muted">
          Nincs még Energiafelhő-fiókod? Ugyanez az út: e-mail-cím, név, 6 jegyű kód — jelszó nem kell.
        </p>
      )}
      {err && <div className="text-sm text-rose-600">{err}</div>}
    </div>
  );
}
