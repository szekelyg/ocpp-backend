import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import StatusBadge from "../components/ui/StatusBadge";
import PayModal from "../components/ui/PayModal";

const POLL_MS = 3_000;
const WAITING_TIMEOUT_S = 15 * 60; // 15 perc – ha az autó nem csatlakozik, timeout
const REDIRECT_DELAY_S = 10;

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
  if (session.ocpp_transaction_id) return "charging";
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

  const [showStop, setShowStop] = useState(false);
  const [stopCode, setStopCode] = useState("");
  const [stopBusy, setStopBusy] = useState(false);
  const [stopErr, setStopErr] = useState("");

  const modalOpenRef = useRef(false);

  const fetchSession = useCallback(async () => {
    if (modalOpenRef.current) return;
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

  // Ha timeout fázisba kerül, indítunk egy visszaszámlálót és átirányítunk
  useEffect(() => {
    if (phaseof(session) !== "timeout") return;
    if (redirectCountdown !== null) return; // már fut
    setRedirectCountdown(REDIRECT_DELAY_S);
  }, [session, redirectCountdown]);

  useEffect(() => {
    if (redirectCountdown === null) return;
    if (redirectCountdown <= 0) { navigate("/"); return; }
    const t = setTimeout(() => setRedirectCountdown((c) => c - 1), 1000);
    return () => clearTimeout(t);
  }, [redirectCountdown, navigate]);

  async function doStop() {
    const code = stopCode.trim().toUpperCase();
    if (!code) { setStopErr("Add meg a stop kódot."); return; }

    setStopBusy(true);
    setStopErr("");
    try {
      const res = await fetch(`/api/sessions/${sessionId}/stop`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stop_code: code }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const msg =
          data?.detail?.hint ||
          (typeof data?.detail === "string" ? data.detail : null) ||
          "Nem sikerült leállítani.";
        throw new Error(msg);
      }
      // siker
      setShowStop(false);
      modalOpenRef.current = false;
      setStopCode("");
      fetchSession();
    } catch (e) {
      setStopErr(e.message);
    } finally {
      setStopBusy(false);
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center">
        <div className="flex gap-1.5">
          {[0, 1, 2].map((i) => (
            <div key={i} className="w-2 h-2 rounded-full bg-blue-500 animate-bounce"
              style={{ animationDelay: `${i * 0.15}s` }} />
          ))}
        </div>
      </div>
    );
  }

  if (fetchErr && !session) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center p-6">
        <div className="max-w-md w-full card cardBody text-center space-y-4">
          <div className="text-4xl">⚠️</div>
          <div className="text-lg font-semibold text-red-300">Nem található</div>
          <p className="text-slate-400 text-sm">{fetchErr}</p>
          <a href="/" className="btn btnGhost inline-flex">← Főoldal</a>
        </div>
      </div>
    );
  }

  const phase = phaseof(session);
  const cp = session?.charge_point;
  const canStop = session?.is_active && session?.ocpp_transaction_id;

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <div className="mx-auto max-w-lg p-6 space-y-5">

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
        {phase === "charging" && (
          <div className="rounded-2xl border border-emerald-700/60 bg-emerald-900/20 px-4 py-3">
            <div className="font-semibold text-emerald-200">⚡ Töltés folyamatban</div>
            <div className="text-sm text-emerald-300/80 mt-0.5">
              Az autó töltődik. A stop kódot emailben kapta meg.
            </div>
          </div>
        )}
        {phase === "finished" && (
          <div className="rounded-2xl border border-slate-700 bg-slate-800/40 px-4 py-3">
            <div className="font-semibold text-slate-200">✓ Töltés befejezve</div>
            <div className="text-sm text-slate-400 mt-0.5">
              A session lezárult. Az elfogyasztott energia és díj végleges.
            </div>
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

        {/* Stop gomb */}
        {canStop && (
          <button
            className="btn w-full border-rose-700/60 bg-rose-700/20 text-rose-200 hover:bg-rose-700/40"
            onClick={() => {
              setStopErr("");
              setStopCode("");
              setShowStop(true);
              modalOpenRef.current = true;
            }}
          >
            Töltés leállítása
          </button>
        )}

        {/* Fetch hiba (de már van session) */}
        {fetchErr && (
          <div className="hint text-xs text-amber-400">
            Frissítési hiba: {fetchErr}
          </div>
        )}

        <div className="text-center">
          <a href="/" className="text-sm text-slate-500 hover:text-slate-300 transition">
            ← Vissza a főoldalra
          </a>
        </div>
      </div>

      {/* Stop modal */}
      <PayModal
        open={showStop}
        busy={stopBusy}
        onClose={() => {
          if (stopBusy) return;
          setShowStop(false);
          modalOpenRef.current = false;
        }}
      >
        <div className="text-slate-100 font-semibold text-base">Töltés leállítása</div>
        <div className="mt-1 text-slate-400 text-sm">
          Add meg a stop kódot, amelyet emailben kaptál a töltés indításakor.
        </div>

        <div className="mt-4">
          <label className="label block mb-2">Stop kód</label>
          <input
            className="field w-full text-center text-xl tracking-[0.3em] uppercase font-mono"
            value={stopCode}
            onChange={(e) => setStopCode(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ""))}
            placeholder="ABCD1234"
            maxLength={8}
            autoFocus
            disabled={stopBusy}
          />
          {stopErr && <div className="mt-2 text-sm text-red-400">{stopErr}</div>}
        </div>

        <div className="mt-5 flex gap-2 justify-end">
          <button
            type="button"
            className="btn btnGhost"
            disabled={stopBusy}
            onClick={() => {
              setShowStop(false);
              modalOpenRef.current = false;
            }}
          >
            Mégse
          </button>
          <button
            type="button"
            className="btn border-rose-700/60 bg-rose-700/20 text-rose-200 hover:bg-rose-700/40"
            disabled={stopBusy}
            onClick={doStop}
          >
            {stopBusy ? "Leállítás…" : "Leállítás megerősítése"}
          </button>
        </div>
      </PayModal>
    </div>
  );
}
