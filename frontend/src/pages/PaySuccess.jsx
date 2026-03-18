import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

const MAX_POLL_MS = 60_000;
const POLL_INTERVAL_MS = 3_000;

export default function PaySuccess() {
  const params = useMemo(() => new URLSearchParams(window.location.search), []);
  const intentId = params.get("intent_id");
  const navigate = useNavigate();

  const [phase, setPhase] = useState("polling"); // polling | timeout | no_intent
  const [elapsed, setElapsed] = useState(0);

  const startRef = useRef(Date.now());
  const timerRef = useRef(null);

  useEffect(() => {
    if (!intentId) {
      setPhase("no_intent");
      return;
    }

    async function poll() {
      try {
        const res = await fetch(`/api/sessions/by-intent/${intentId}`);
        if (res.ok) {
          const data = await res.json();
          navigate(`/charging/${data.id}`, { replace: true });
          return;
        }
      } catch (_) {}

      const now = Date.now();
      setElapsed(Math.round((now - startRef.current) / 1000));

      if (now - startRef.current >= MAX_POLL_MS) {
        setPhase("timeout");
        return;
      }

      timerRef.current = setTimeout(poll, POLL_INTERVAL_MS);
    }

    timerRef.current = setTimeout(poll, POLL_INTERVAL_MS);
    return () => clearTimeout(timerRef.current);
  }, [intentId, navigate]);

  if (phase === "no_intent") {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center p-6">
        <div className="max-w-md w-full card cardBody text-center space-y-4">
          <div className="text-4xl">⚠️</div>
          <div className="text-lg font-semibold text-red-300">Érvénytelen link</div>
          <p className="text-slate-400 text-sm">Hiányzó intent_id paraméter.</p>
          <a href="/" className="btn btnGhost inline-flex">← Vissza a főoldalra</a>
        </div>
      </div>
    );
  }

  if (phase === "timeout") {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center p-6">
        <div className="max-w-md w-full card cardBody text-center space-y-4">
          <div className="text-4xl">⏱️</div>
          <div className="text-lg font-semibold text-amber-300">A töltés indítása késik</div>
          <p className="text-slate-400 text-sm">
            A fizetés valószínűleg sikeres volt, de a töltés indítása még nem fejeződött be.
            Kérjük ellenőrizd az emailedet, vagy vedd fel a kapcsolatot az üzemeltetővel.
          </p>
          <a href="/" className="btn btnGhost inline-flex">← Vissza a főoldalra</a>
        </div>
      </div>
    );
  }

  // polling állapot
  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center p-6">
      <div className="max-w-md w-full card cardBody text-center space-y-6">
        <div className="text-4xl">✅</div>
        <div>
          <div className="text-xl font-semibold text-emerald-300">Sikeres fizetés!</div>
          <p className="text-slate-400 text-sm mt-1">Töltés indítása folyamatban…</p>
        </div>

        {/* Animált töltés indikátor */}
        <div className="flex justify-center gap-1.5">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="w-2 h-2 rounded-full bg-blue-500 animate-bounce"
              style={{ animationDelay: `${i * 0.15}s` }}
            />
          ))}
        </div>

        <p className="text-xs text-slate-500">{elapsed}s</p>
      </div>
    </div>
  );
}
