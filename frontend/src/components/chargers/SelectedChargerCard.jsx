import StatusBadge from "../ui/StatusBadge";
import { placeLines, formatHu } from "../../utils/format";

export default function SelectedChargerCard({ cp }) {
  if (!cp) return <div className="text-slate-400 text-sm">Nincs kiválasztott töltő.</div>;

  const lines = placeLines(cp);

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
        <button type="button" className="btn btnPrimary">
          Töltés indítása (QR)
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

      <div className="hint">
        Tipp: a “Start” gomb mögé jön a zárolás + RemoteStartTransaction.
      </div>
    </div>
  );
}