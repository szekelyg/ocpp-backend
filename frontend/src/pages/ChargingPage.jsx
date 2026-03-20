import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import AppHeader from "../components/ui/AppHeader";
import StatusBadge from "../components/ui/StatusBadge";

const POLL_MS = 3_000;
const WAITING_TIMEOUT_S = 15 * 60; // 15 perc
const REDIRECT_DELAY_S = 30;

function formatDuration(s) {
  if (s == null || s < 0) return "—";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}ó ${m}p ${sec}mp`;
  if (m > 0) return `${m}p ${sec}mp`;
  return `${sec}mp`;
}

function phaseof(session) {
  if (!session) return null;
  if (session.finished_at) {
    if (session.timed_out) return "timeout";
    return "finished";
  }
  if (session.ocpp_transaction_id) {
    // Csak akkor "töltés folyamatban" ha az OCPP státusz is charging
    if (session.charge_point?.status === "charging") return "charging";
    return "connecting"; // StartTransaction megjött de fizikailag még nem tölt
  }
  if ((session.duration_s ?? 0) >= WAITING_TIMEOUT_S) return "timeout";
  return "waiting";
}

export default function ChargingPage() {
  const { sessionId } = useParams();
  const navigate = useNavigate();

  const [session, setSession] = useState(null);
  const [loading, setLoading] = useState(true);
  const [fetchErr, setFetchErr] = useState("");
  const [redirectCountdown, setRedirectCountdown] = useState(null);

  const [stopConfirm, setStopConfirm] = useState(false);
  const [stopBusy, setStopBusy] = useState(false);
  const [stopErr, setStopErr] = useState("");

  const fetchSession = useCallback(async () => {
    try {
      const res = await fetch(`/api/sessions/${sessionId}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setSession(await res.json());
      setFetchErr("");
    } catch (e) {
      setFetchErr(e.message);
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    fetchSession();
    const t = setInterval(fetchSession, POLL_MS);
    return () => clearInterval(t);
  }, [fetchSession]);

  // Redirect countdown – timeout és finished esetén egyaránt
  // A finished_at-tól számítjuk a maradék időt, így oldalfrissítés után sem indul újra 30mp-ről.
  useEffect(() => {
    const phase = phaseof(session);
    if (phase !== "timeout" && phase !== "finished") return;
    if (redirectCountdown !== null) return;
    const finishedAt = session?.finished_at;
    if (finishedAt) {
      const elapsed = Math.floor((Date.now() - new Date(finishedAt).getTime()) / 1000);
      setRedirectCountdown(Math.max(0, REDIRECT_DELAY_S - elapsed));
    } else {
      setRedirectCountdown(REDIRECT_DELAY_S);
    }
  }, [session, redirectCountdown]);

  useEffect(() => {
    if (redirectCountdown === null) return;
    if (redirectCountdown <= 0) { navigate("/"); return; }
    const t = setTimeout(() => setRedirectCountdown((c) => c - 1), 1000);
    return () => clearTimeout(t);
  }, [redirectCountdown, navigate]);

  async function doStop() {
    setStopBusy(true);
    setStopErr("");
    try {
      const res = await fetch(`/api/sessions/${sessionId}/stop`, {
        method: "POST",
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const msg =
          data?.detail?.hint ||
          (typeof data?.detail === "string" ? data.detail : null) ||
          "Nem sikerült leállítani.";
        throw new Error(msg);
      }
      setStopConfirm(false);
      fetchSession();
    } catch (e) {
      setStopErr(e.message);
    } finally {
      setStopBusy(false);
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
        <AppHeader />
        <div className="flex-1 flex items-center justify-center">
          <div className="flex gap-1.5">
            {[0, 1, 2].map((i) => (
              <div key={i} className="w-2 h-2 rounded-full bg-blue-500 animate-bounce"
                style={{ animationDelay: `${i * 0.15}s` }} />
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (fetchErr && !session) {
    return (
      <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
        <AppHeader />
        <div className="flex-1 flex items-center justify-center p-6">
          <div className="max-w-md w-full card cardBody text-center space-y-4">
            <div className="text-3xl">⚠️</div>
            <div className="text-lg font-semibold text-red-300">A session nem található</div>
            <p className="text-slate-400 text-sm">
              A töltési munkamenet nem elérhető vagy lejárt.
            </p>
            <a href="/" className="btn btnPrimary inline-flex">← Vissza a töltőkhöz</a>
          </div>
        </div>
      </div>
    );
  }

  const phase = phaseof(session);
  const cp = session?.charge_point;
  const canStop = session?.is_active && session?.ocpp_transaction_id;

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
      <AppHeader />
      <div className="mx-auto max-w-lg w-full p-6 space-y-5">

        {/* Header */}
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Töltés</h1>
            <p className="text-sm text-slate-400 mt-0.5">
              {cp?.ocpp_id || "—"}
              {cp?.model ? ` · ${cp.model}` : ""}
            </p>
          </div>
          {cp?.status && <StatusBadge status={cp.status} />}
        </div>

        {/* Fázis banner */}
        {phase === "waiting" && (
          <div className="rounded-2xl border border-amber-700/60 bg-amber-900/20 px-4 py-3">
            <div className="font-semibold text-amber-200">⏳ Várakozás az autóra</div>
            <div className="text-sm text-amber-300/80 mt-0.5">
              Dugja be az autót a töltőbe a töltés megkezdéséhez.
            </div>
          </div>
        )}
        {phase === "timeout" && (
          <div className="rounded-2xl border border-red-700/60 bg-red-900/20 px-4 py-3 space-y-1">
            <div className="font-semibold text-red-300">✕ Töltés nem indult el</div>
            <div className="text-sm text-red-300/80">
              Az autó 15 percen belül nem csatlakozott. A munkamenet lezárult,
              a befizetett összeg visszatérítése folyamatban van.
            </div>
            {redirectCountdown !== null && (
              <div className="text-xs text-slate-400 pt-1">
                Átirányítás a főoldalra {redirectCountdown} másodperc múlva…
              </div>
            )}
          </div>
        )}
        {phase === "connecting" && (
          <div className="rounded-2xl border border-yellow-700/60 bg-yellow-900/20 px-4 py-3">
            <div className="font-semibold text-yellow-200">⏳ Csatlakozás folyamatban</div>
            <div className="text-sm text-yellow-300/80 mt-0.5">
              A töltő elfogadta a kérést. Dugja be az autót, ha még nem tette meg.
            </div>
          </div>
        )}
        {phase === "charging" && (
          <div className="rounded-2xl border border-emerald-700/60 bg-emerald-900/20 px-4 py-3">
            <div className="font-semibold text-emerald-200">⚡ Töltés folyamatban</div>
            <div className="text-sm text-emerald-300/80 mt-0.5">
              Az autó töltődik.
            </div>
          </div>
        )}
        {phase === "finished" && (
          <div className="rounded-2xl border border-slate-700 bg-slate-800/40 px-4 py-3 space-y-1">
            <div className="font-semibold text-slate-200">✓ Töltés befejezve</div>
            <div className="text-sm text-slate-400 mt-0.5">
              A session lezárult. Az elfogyasztott energia és díj végleges.
            </div>
            {redirectCountdown !== null && (
              <div className="text-xs text-slate-400 pt-1">
                Átirányítás a főoldalra {redirectCountdown} másodperc múlva…
              </div>
            )}
          </div>
        )}

        {/* Statisztikák */}
        <div className="card">
          <div className="cardBody grid grid-cols-2 gap-x-6 gap-y-5">
            <div>
              <div className="label mb-1">Eltelt idő</div>
              <div className="text-2xl font-mono font-semibold tabular-nums">
                {formatDuration(session?.duration_s)}
              </div>
            </div>
            <div>
              <div className="label mb-1">Energia</div>
              <div className="text-2xl font-mono font-semibold tabular-nums">
                {session?.energy_kwh != null
                  ? `${session.energy_kwh.toFixed(2)} kWh`
                  : "—"}
              </div>
            </div>
            <div>
              <div className="label mb-1">Becsült díj</div>
              <div className="text-2xl font-mono font-semibold tabular-nums">
                {session?.cost_huf != null
                  ? `${Math.round(session.cost_huf).toLocaleString("hu-HU")} Ft`
                  : "—"}
              </div>
            </div>
            <div>
              <div className="label mb-1">Indítás</div>
              <div className="text-sm text-slate-300 tabular-nums">
                {session?.started_at
                  ? new Date(session.started_at).toLocaleString("hu-HU")
                  : "—"}
              </div>
            </div>
          </div>
        </div>

        {/* Stop gomb – inline megerősítéssel */}
        {canStop && !stopConfirm && (
          <button
            className="btn w-full border-rose-700/60 bg-rose-700/20 text-rose-200 hover:bg-rose-700/40"
            onClick={() => { setStopErr(""); setStopConfirm(true); }}
          >
            Töltés leállítása
          </button>
        )}
        {canStop && stopConfirm && (
          <div className="rounded-2xl border border-rose-700/60 bg-rose-900/20 px-4 py-4 space-y-3">
            <div className="text-sm text-rose-200 font-medium">
              Biztosan leállítja a töltést?
            </div>
            {stopErr && <div className="text-sm text-red-400">{stopErr}</div>}
            <div className="flex gap-2">
              <button
                className="btn btnGhost flex-1"
                disabled={stopBusy}
                onClick={() => { setStopConfirm(false); setStopErr(""); }}
              >
                Mégse
              </button>
              <button
                className="btn flex-1 border-rose-700/60 bg-rose-700/30 text-rose-200 hover:bg-rose-700/50"
                disabled={stopBusy}
                onClick={doStop}
              >
                {stopBusy ? "Leállítás…" : "Igen, leállítás"}
              </button>
            </div>
          </div>
        )}

        {/* Fetch hiba (de már van session) */}
        {fetchErr && (
          <div className="hint text-xs text-amber-400">
            Frissítési hiba: {fetchErr}
          </div>
        )}

        <div className="text-center pb-6">
          <a href="/" className="text-sm text-slate-500 hover:text-slate-300 transition">
            ← Vissza a töltőkhöz
          </a>
        </div>
      </div>
    </div>
  );
}
