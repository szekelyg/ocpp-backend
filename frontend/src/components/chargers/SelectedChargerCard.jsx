// SelectedChargerCard.jsx
import { useMemo, useState } from "react";
import StatusBadge from "../ui/StatusBadge";
import { placeLines, formatHu } from "../../utils/format";
import PayModal from "../ui/PayModal";

const STARTABLE = new Set(["available", "preparing", "finishing"]);

function isStartable(status) {
  return STARTABLE.has(String(status || "").toLowerCase());
}

function isCarConnected(status) {
  return ["preparing", "finishing"].includes(String(status || "").toLowerCase());
}

export default function SelectedChargerCard({ cp, onModalChange }) {
  const [email, setEmail] = useState("");
  const [showPay, setShowPay] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const lines = useMemo(() => (cp ? placeLines(cp) : ["", ""]), [cp]);
  const canStart = cp && isStartable(cp.status) && !busy;

  if (!cp) return <div className="text-slate-400 text-sm">Nincs kiválasztott töltő.</div>;

  function openModal() {
    setErr("");
    setShowPay(true);
    onModalChange?.(true);
  }

  function closeModal() {
    if (busy) return;
    setShowPay(false);
    onModalChange?.(false);
  }

  async function startFlow() {
    setErr("");

    const e = (email || "").trim();
    if (!e) {
      setErr("Adj meg egy email címet.");
      return;
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e)) {
      setErr("Hibás email formátum.");
      return;
    }

    setBusy(true);
    try {
      const res = await fetch("/api/intents/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          charge_point_id: cp.id,
          connector_id: 1,
          email: e,
          hold_amount_huf: 5000,
        }),
      });

      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(
          typeof data?.detail === "string"
            ? data.detail
            : data?.detail?.error || data?.error || "Nem sikerült intentet létrehozni."
        );
      }

      const url = data?.checkout_url;
      if (!url) throw new Error("Nem jött checkout_url a backendtől.");
      if (!/^https:\/\//i.test(url)) throw new Error("Érvénytelen fizetési URL.");

      onModalChange?.(false);
      window.location.href = url;
    } catch (e) {
      setErr(e?.message || "Hiba történt.");
      setBusy(false);
    }
  }

  const statusStr = String(cp.status || "").toLowerCase();

  return (
    <div className="space-y-4">
      <div className="detailGrid">
        <div className="detailKey">OCPP ID</div>
        <div className="detailValStrong">{cp.ocpp_id || "—"}</div>

        <div className="detailKey">Hely</div>
        <div className="detailVal">{lines[0] || "—"}</div>

        <div className="detailKey">Cím</div>
        <div className="detailVal">{lines[1] || "—"}</div>

        <div className="detailKey">Státusz</div>
        <div className="detailVal flex items-center gap-3">
          <StatusBadge status={cp.status} />
          <span className="text-xs text-slate-400">
            (OCPP: <span className="font-semibold text-slate-200">{String(cp.status || "—")}</span>)
          </span>
        </div>

        <div className="detailKey">Utoljára látva</div>
        <div className="detailVal">{formatHu(cp.last_seen_at)}</div>
      </div>

      <div className="actions">
        <button
          type="button"
          className="btn btnPrimary"
          disabled={!canStart}
          onClick={openModal}
        >
          {busy ? "Indítás..." : "Töltés indítása"}
        </button>

        <button
          type="button"
          className="btn btnGhost"
          onClick={() => {
            if (typeof cp.latitude !== "number" || typeof cp.longitude !== "number") return;
            window.open(`https://www.google.com/maps?q=${cp.latitude},${cp.longitude}`, "_blank");
          }}
        >
          Google Maps
        </button>
      </div>

      {/* Státusz-specifikus tájékoztató */}
      {statusStr === "available" && (
        <div className="hint">
          A töltő szabad. Indítás után csatlakoztassa az autót a töltőhöz.
        </div>
      )}
      {(statusStr === "preparing" || statusStr === "finishing") && (
        <div className="hint rounded-xl border-amber-800/50 bg-amber-950/30 text-amber-300">
          Az autó már csatlakoztatva van – a töltés fizetés után azonnal indul.
        </div>
      )}
      {statusStr === "charging" && (
        <div className="hint">
          Ez a töltő már használatban van. Kérjük válasszon másikat.
        </div>
      )}
      {!["available", "preparing", "finishing", "charging"].includes(statusStr) && (
        <div className="hint">
          A töltés indítása nem lehetséges ebben az állapotban ({statusStr}).
        </div>
      )}

      <PayModal open={showPay} busy={busy} onClose={closeModal}>
        <div className="text-slate-100 font-semibold text-base">Fizetés indítása</div>
        <div className="mt-1 text-slate-400 text-sm">
          {isCarConnected(cp.status)
            ? "Az autó már csatlakoztatva van – fizetés után azonnal indul a töltés."
            : "Fizetés után csatlakoztassa az autót a töltőhöz."}
        </div>
        <div className="mt-1 text-slate-500 text-xs">
          A stop kódot és a bizonylatot erre az emailre küldjük.
        </div>

        <div className="mt-4">
          <label className="block text-xs text-slate-400 mb-2">Email cím</label>
          <input
            className="w-full rounded-xl border border-slate-800 bg-slate-900/40 px-3 py-2 text-slate-100 outline-none focus:ring-2 focus:ring-blue-500/40"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="email@domain.hu"
            autoFocus
            disabled={busy}
          />
          {err ? <div className="mt-2 text-sm text-red-400">{err}</div> : null}
        </div>

        <div className="mt-5 flex gap-2 justify-end">
          <button type="button" className="btn btnGhost" onClick={closeModal}>
            Mégse
          </button>
          <button
            type="button"
            className="btn btnPrimary"
            disabled={busy || !isStartable(cp.status)}
            onClick={startFlow}
          >
            {busy ? "Átirányítás..." : "Fizetés (5 000 Ft)"}
          </button>
        </div>
      </PayModal>
    </div>
  );
}
