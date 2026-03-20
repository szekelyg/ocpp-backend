import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import AppHeader from "../components/ui/AppHeader";

const MAX_POLL_MS = 60_000;
const POLL_INTERVAL_MS = 3_000;

export default function PaySuccess() {
  const params = useMemo(() => new URLSearchParams(window.location.search), []);
  const intentId = params.get("intent_id");
  const navigate = useNavigate();

  const [phase, setPhase] = useState("polling");
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
      <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
        <AppHeader />
        <div className="flex-1 flex items-center justify-center p-6">
          <div className="max-w-md w-full card cardBody text-center space-y-4">
            <div className="text-3xl">⚠️</div>
            <div className="text-lg font-semibold text-red-300">Érvénytelen hivatkozás</div>
            <p className="text-slate-400 text-sm">A link nem tartalmaz érvényes azonosítót.</p>
            <a href="/" className="btn btnPrimary inline-flex">← Vissza a töltőkhöz</a>
          </div>
        </div>
      </div>
    );
  }

  if (phase === "timeout") {
    return (
      <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
        <AppHeader />
        <div className="flex-1 flex items-center justify-center p-6">
          <div className="max-w-md w-full card cardBody text-center space-y-4">
            <div className="text-3xl">⏱️</div>
            <div className="text-lg font-semibold text-amber-300">A töltés indítása késik</div>
            <p className="text-slate-400 text-sm">
              A fizetés valószínűleg sikeres volt, de a töltő visszajelzése még várat magára.
              Kérjük ellenőrizze email-fiókját — hamarosan értesítőt küldünk.
            </p>
            <p className="text-slate-500 text-xs">
              Ha perceken belül sem érkezik értesítő, kérjük vegye fel a kapcsolatot
              ügyfélszolgálatunkkal.
            </p>
            <a href="/" className="btn btnGhost inline-flex">← Vissza a töltőkhöz</a>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
      <AppHeader />
      <div className="flex-1 flex items-center justify-center p-6">
        <div className="max-w-md w-full card cardBody text-center space-y-6">

          <div className="w-16 h-16 rounded-full bg-emerald-900/40 border border-emerald-700/60 flex items-center justify-center mx-auto text-3xl">
            ✓
          </div>

          <div>
            <div className="text-xl font-semibold text-emerald-300">Fizetés sikeres</div>
            <p className="text-slate-400 text-sm mt-2">
              A töltő fogadta a kérést. A session indítása folyamatban…
            </p>
          </div>

          <div className="flex justify-center gap-1.5">
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="w-2 h-2 rounded-full bg-blue-500 animate-bounce"
                style={{ animationDelay: `${i * 0.15}s` }}
              />
            ))}
          </div>

          <p className="text-xs text-slate-600">{elapsed}s</p>
        </div>
      </div>
    </div>
  );
}
