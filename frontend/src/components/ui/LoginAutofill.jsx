// frontend/src/components/ui/LoginAutofill.jsx
// Jelszó nélküli belépés email-kóddal (OTP). Sikeres belépéskor visszaadja a
// mentett SZÁMLÁZÁSI profilt, amivel a szülő automatikusan kitölti az űrlapot.
// Kártyaadatot sehol nem kezel.
import { useState } from "react";

export const AUTH_TOKEN_KEY = "ef_auth_token";

const inputCls = "field";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function LoginAutofill({ defaultEmail = "", onLoggedIn, disabled = false }) {
  // "collapsed" | "email" | "code" | "done"
  const [step, setStep] = useState("collapsed");
  const [email, setEmail] = useState(defaultEmail);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [info, setInfo] = useState("");

  async function requestCode() {
    setErr("");
    const e = (email || "").trim().toLowerCase();
    if (!EMAIL_RE.test(e)) { setErr("Adj meg egy érvényes email-címet."); return; }
    setBusy(true);
    try {
      const res = await fetch("/api/auth/request-code", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: e }),
      });
      if (!res.ok) throw new Error("Nem sikerült a kódot elküldeni. Próbáld újra.");
      setStep("code");
      setInfo(`Kódot küldtünk ide: ${e}. Nézd meg a postaládád (spam is).`);
    } catch (x) {
      setErr(x?.message || "Hiba történt.");
    } finally {
      setBusy(false);
    }
  }

  async function verify() {
    setErr("");
    const e = (email || "").trim().toLowerCase();
    const c = (code || "").trim();
    if (c.length < 4) { setErr("Add meg a kapott kódot."); return; }
    setBusy(true);
    try {
      const res = await fetch("/api/auth/verify-code", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: e, code: c }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const left = data?.detail?.attempts_left;
        throw new Error(
          data?.detail === "code_invalid_or_expired"
            ? "A kód lejárt vagy érvénytelen. Kérj újat."
            : typeof left === "number"
            ? `Hibás kód. Még ${left} próbálkozás.`
            : "A kód nem megfelelő."
        );
      }
      try { localStorage.setItem(AUTH_TOKEN_KEY, data.token); } catch { /* ignore */ }
      setStep("done");
      setInfo(
        data.profile
          ? `Belépve: ${e} — a számlázási adataidat betöltöttük.`
          : `Belépve: ${e} — ehhez az email-címhez még nincs mentett adat, kérjük töltsd ki az űrlapot.`
      );
      onLoggedIn?.(data.profile || null, e);
    } catch (x) {
      setErr(x?.message || "Hiba történt.");
    } finally {
      setBusy(false);
    }
  }

  if (step === "done") {
    return (
      <div className="rounded-xl border border-brand-green/40 bg-[#e6faf4] px-3 py-2.5 text-xs text-[#037a5c]">
        ✓ {info || "Belépve"}
      </div>
    );
  }

  if (step === "collapsed") {
    return (
      <button
        type="button"
        disabled={disabled}
        onClick={() => { setErr(""); setStep("email"); }}
        className="w-full rounded-xl border border-brand-line bg-brand-panel px-3 py-2.5 text-sm text-ink-soft hover:border-brand-blue/60 disabled:opacity-50"
      >
        Már mentetted az adataidat? <span className="font-semibold text-brand-action">Belépés →</span>
      </button>
    );
  }

  return (
    <div className="rounded-xl border border-brand-line bg-brand-panel p-3 space-y-2.5">
      {step === "email" && (
        <>
          <div className="text-xs text-ink-soft">
            Add meg az email-címed, és küldünk egy belépési kódot.
          </div>
          <input
            className={inputCls}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="pelda@domain.hu"
            type="email"
            disabled={busy}
            autoFocus
          />
          <div className="flex gap-2">
            <button type="button" className="btn btnGhost flex-1" disabled={busy}
              onClick={() => { setStep("collapsed"); setErr(""); }}>
              Mégse
            </button>
            <button type="button" className="btn btnPrimary flex-1" disabled={busy} onClick={requestCode}>
              {busy ? "Küldés…" : "Kód kérése"}
            </button>
          </div>
        </>
      )}

      {step === "code" && (
        <>
          {info && <div className="text-xs text-ink-soft">{info}</div>}
          <input
            className={inputCls + " tracking-[0.4em] text-center font-semibold"}
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
            placeholder="123456"
            inputMode="numeric"
            disabled={busy}
            autoFocus
          />
          <div className="flex gap-2">
            <button type="button" className="btn btnGhost flex-1" disabled={busy} onClick={requestCode}>
              Új kód
            </button>
            <button type="button" className="btn btnPrimary flex-1" disabled={busy} onClick={verify}>
              {busy ? "Ellenőrzés…" : "Belépés"}
            </button>
          </div>
        </>
      )}

      {err && <div className="text-sm text-rose-600">{err}</div>}
    </div>
  );
}
