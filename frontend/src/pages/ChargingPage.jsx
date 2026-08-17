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
      <div className="min-h-screen flex flex-col">
        <AppHeader />
        <div className="flex-1 flex items-center justify-center">
          <div className="flex gap-1.5">
            {[0, 1, 2].map((i) => (
              <div key={i} className="w-2 h-2 rounded-full bg-brand-action animate-bounce"
                style={{ animationDelay: `${i * 0.15}s` }} />
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (fetchErr && !session) {
    return (
      <div className="min-h-screen flex flex-col">
        <AppHeader />
        <div className="flex-1 flex items-center justify-center p-6">
          <div className="max-w-md w-full card cardBody text-center space-y-4">
            <div className="text-3xl">⚠️</div>
            <div className="text-lg font-semibold text-rose-700">A session nem található</div>
            <p className="text-ink-soft text-sm">
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
    <div className="min-h-screen flex flex-col">
      <AppHeader />
      <div className="mx-auto max-w-lg w-full p-6 space-y-5">

        {/* Header */}
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Töltés</h1>
            <p className="text-sm text-ink-soft mt-0.5">
              {cp?.ocpp_id || "—"}
              {cp?.model ? ` · ${cp.model}` : ""}
            </p>
          </div>
          {cp?.status && <StatusBadge status={cp.status} />}
        </div>

        {/* Fázis banner */}
        {phase === "waiting" && (
          <div className="rounded-2xl border border-brand-yellow/60 bg-brand-cream px-4 py-3">
            <div className="font-semibold text-brand-amber">⏳ Várakozás az autóra</div>
            <div className="text-sm text-brand-amber/90 mt-0.5">
              Dugja be az autót a töltőbe a töltés megkezdéséhez.
            </div>
          </div>
        )}
        {phase === "timeout" && (
          <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 space-y-1">
            <div className="font-semibold text-rose-700">✕ Töltés nem indult el</div>
            <div className="text-sm text-rose-600">
              Az autó 15 percen belül nem csatlakozott. A munkamenet lezárult,
              a befizetett összeg visszatérítése folyamatban van.
            </div>
            {redirectCountdown !== null && (
              <div className="text-xs text-ink-muted pt-1">
                Átirányítás a főoldalra {redirectCountdown} másodperc múlva…
              </div>
            )}
          </div>
        )}
        {phase === "connecting" && (
          <div className="rounded-2xl border border-brand-yellow/60 bg-brand-cream px-4 py-3">
            <div className="font-semibold text-brand-amber">⏳ Csatlakozás folyamatban</div>
            <div className="text-sm text-brand-amber/90 mt-0.5">
              A töltő elfogadta a kérést. Dugja be az autót, ha még nem tette meg.
            </div>
          </div>
        )}
        {phase === "charging" && (
          <div className="rounded-2xl border border-[#04cd99]/40 bg-[#e6faf4] px-4 py-3">
            <div className="font-semibold text-[#037a5c]">⚡ Töltés folyamatban</div>
            <div className="text-sm text-[#037a5c]/80 mt-0.5">
              Az autó töltődik.
            </div>
          </div>
        )}
        {phase === "finished" && (
          <div className="rounded-2xl border border-brand-line bg-brand-panel px-4 py-3 space-y-1">
            <div className="font-semibold text-ink">✓ Töltés befejezve</div>
            <div className="text-sm text-ink-soft mt-0.5">
              A session lezárult. Az elfogyasztott energia és díj végleges.
            </div>
            {redirectCountdown !== null && (
              <div className="text-xs text-ink-muted pt-1">
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
              <div className="label mb-1">{phase === "finished" ? "Végösszeg" : "Becsült díj"}</div>
              <div className="text-2xl font-mono font-semibold tabular-nums">
                {session?.cost_huf != null
                  ? `${Math.round(session.cost_huf).toLocaleString("hu-HU")} Ft`
                  : "—"}
              </div>
              {session?.price_huf_per_kwh > 0 && (
                <div className="text-xs text-ink-muted mt-1 leading-snug">
                  {session.price_huf_per_kwh.toLocaleString("hu-HU")} Ft/kWh
                  {session?.min_charge_huf > 0 &&
                    ` · min. ${session.min_charge_huf.toLocaleString("hu-HU")} Ft`}
                </div>
              )}
            </div>
            <div>
              <div className="label mb-1">Töltési teljesítmény</div>
              <div className="text-2xl font-mono font-semibold tabular-nums">
                {session?.power_w != null
                  ? `${(session.power_w / 1000).toFixed(1)} kW`
                  : "—"}
              </div>
              {session?.phases?.list?.length > 0 && (
                <div className="mt-2">
                  <div className="text-xs text-ink-muted mb-1.5">
                    {session.phases.active_count > 0
                      ? `${session.phases.active_count} fázison tölt`
                      : "Fázisonként"}
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {session.phases.list.map((ph) => (
                      <span
                        key={ph.name}
                        className={[
                          "inline-flex items-center gap-1.5 rounded-lg border px-2 py-1 text-xs tabular-nums",
                          ph.active
                            ? "border-[#04cd99]/40 bg-[#e6faf4] text-[#037a5c]"
                            : "border-brand-line bg-brand-panel text-ink-muted",
                        ].join(" ")}
                      >
                        <span className="font-semibold">{ph.name}</span>
                        <span>
                          {ph.power_w != null ? `${(ph.power_w / 1000).toFixed(1)} kW` : "—"}
                        </span>
                        {ph.current_a != null && (
                          <span className="text-[10px] opacity-70">
                            {ph.current_a.toFixed(0)} A
                          </span>
                        )}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
            <div>
              <div className="label mb-1">Indítás</div>
              <div className="text-sm text-ink-soft tabular-nums">
                {session?.started_at
                  ? new Date(session.started_at).toLocaleString("hu-HU")
                  : "—"}
              </div>
            </div>
          </div>
        </div>

        {/* Zárolt összeg – maximális terhelés */}
        {session?.hold_amount_huf > 0 && (
          <div className="rounded-2xl border border-brand-line bg-white px-4 py-3 text-xs text-ink-soft leading-relaxed">
            Zárolt összeg:{" "}
            <span className="text-ink font-semibold">
              {session.hold_amount_huf.toLocaleString("hu-HU")} Ft
            </span>{" "}
            — legfeljebb ennyi kerülhet levonásra. A töltés végén csak a ténylegesen
            elfogyasztott energia díját számítjuk fel; a fennmaradó zárolás feloldódik.
          </div>
        )}

        {/* Stop gomb – inline megerősítéssel */}
        {canStop && !stopConfirm && (
          <button
            className="btn w-full border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100"
            onClick={() => { setStopErr(""); setStopConfirm(true); }}
          >
            Töltés leállítása
          </button>
        )}
        {canStop && stopConfirm && (
          <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-4 space-y-3">
            <div className="text-sm text-rose-700 font-medium">
              Biztosan leállítja a töltést?
            </div>
            {stopErr && <div className="text-sm text-rose-600">{stopErr}</div>}
            <div className="flex gap-2">
              <button
                className="btn btnGhost flex-1"
                disabled={stopBusy}
                onClick={() => { setStopConfirm(false); setStopErr(""); }}
              >
                Mégse
              </button>
              <button
                className="btn flex-1 border-rose-300 bg-rose-100 text-rose-700 hover:bg-rose-200"
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
          <div className="hint">
            Frissítési hiba: {fetchErr}
          </div>
        )}

        <div className="text-center pb-6">
          <a href="/" className="text-sm text-ink-muted hover:text-ink transition">
            ← Vissza a töltőkhöz
          </a>
        </div>
      </div>
    </div>
  );
}
