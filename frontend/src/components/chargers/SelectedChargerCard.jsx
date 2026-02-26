// SelectedChargerCard.jsx
import { useMemo, useState } from "react";
import StatusBadge from "../ui/StatusBadge";
import { placeLines, formatHu } from "../../utils/format";
import PayModal from "../ui/PayModal";

function isAvailable(status) {
  return String(status || "").toLowerCase() === "available";
}

export default function SelectedChargerCard({ cp }) {
  const [email, setEmail] = useState("");
  const [showPay, setShowPay] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const lines = useMemo(() => (cp ? placeLines(cp) : ["", ""]), [cp]);
  const canStart = cp && isAvailable(cp.status) && !busy;

  if (!cp) return <div className="text-slate-400 text-sm">Nincs kiválasztott töltő.</div>;

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

      window.location.href = url;
    } catch (e) {
      setErr(e?.message || "Hiba történt.");
      setBusy(false);
    }
  }

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
            (OCPP:{" "}
            <span className="font-semibold text-slate-200">{String(cp.status || "—")}</span>)
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
          onClick={() => {
            setErr("");
            setShowPay(true);
          }}
          title={!isAvailable(cp.status) ? "Csak 'available' státuszban indítható." : ""}
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
          Megnyitás Google Maps-ben
        </button>
      </div>

      {!isAvailable(cp.status) ? (
        <div className="hint">
          A töltés indítása csak akkor aktív, ha a státusz <b>available</b>.
        </div>
      ) : (
        <div className="hint">Indítás: email → Stripe fizetés → webhook → RemoteStartTransaction.</div>
      )}

      <PayModal
        open={showPay}
        busy={busy}
        onClose={() => {
          if (busy) return;
          setShowPay(false);
        }}
      >
        <div className="text-slate-100 font-semibold text-base">Fizetés indítása</div>
        <div className="mt-1 text-slate-400 text-sm">
          Add meg az emailed. Erre küldjük később a stop kódot / bizonylatot.
        </div>

        <div className="mt-4">
          <label className="block text-xs text-slate-400 mb-2">Email</label>
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
          <button
            type="button"
            className="btn btnGhost"
            onClick={() => {
              if (busy) return;
              setShowPay(false);
            }}
          >
            Mégse
          </button>

          <button
            type="button"
            className="btn btnPrimary"
            disabled={busy || !isAvailable(cp.status)}
            onClick={startFlow}
          >
            {busy ? "Átirányítás..." : "Fizetés (5000 Ft)"}
          </button>
        </div>
      </PayModal>
    </div>
  );
}