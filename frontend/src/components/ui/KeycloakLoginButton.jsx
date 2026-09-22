// frontend/src/components/ui/KeycloakLoginButton.jsx
// "Belépés Energiafelhő-fiókkal" – csak akkor jelenik meg, ha a backend szerint van Keycloak.
import { useEffect, useState } from "react";
import CloudLogo from "./CloudLogo";
import { getKeycloakConfig, startKeycloakLogin } from "../../utils/auth";

export default function KeycloakLoginButton({ returnTo, className = "", disabled = false, onError }) {
  const [enabled, setEnabled] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    getKeycloakConfig().then((cfg) => { if (alive) setEnabled(!!cfg.enabled); });
    return () => { alive = false; };
  }, []);

  if (!enabled) return null;

  async function go() {
    setBusy(true);
    try {
      await startKeycloakLogin({ returnTo });
    } catch (e) {
      setBusy(false);
      onError?.(e?.message || "A belépés nem indítható.");
    }
  }

  return (
    <button
      type="button"
      disabled={disabled || busy}
      onClick={go}
      className={`btn btnPrimary w-full gap-2 ${className}`}
    >
      <CloudLogo size={18} />
      {busy ? "Átirányítás…" : "Belépés Energiafelhő-fiókkal"}
    </button>
  );
}
