import StatusBadge from "../ui/StatusBadge";
import { placeLines, formatHu } from "../../utils/format";

export default function SelectedChargerCard({ cp }) {
  if (!cp) {
    return <div className="text-slate-500">Nincs kiválasztott töltő.</div>;
  }

  const lines = placeLines(cp);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-x-4 gap-y-3 text-sm">
        <div className="text-slate-500">OCPP ID</div>
        <div className="col-span-2 font-semibold text-slate-900">{cp.ocpp_id}</div>

        <div className="text-slate-500">Hely</div>
        <div className="col-span-2 text-slate-700">{lines[0] || "—"}</div>

        <div className="text-slate-500">Cím</div>
        <div className="col-span-2 text-slate-700">{lines[1] || "—"}</div>

        <div className="text-slate-500">Státusz</div>
        <div className="col-span-2 flex items-center gap-3">
          <StatusBadge status={cp.status} />
          <span className="text-xs text-slate-500">
            (OCPP: <span className="font-semibold text-slate-700">{String(cp.status || "—")}</span>)
          </span>
        </div>

        <div className="text-slate-500">Utoljára látva</div>
        <div className="col-span-2 text-slate-700">{formatHu(cp.last_seen_at)}</div>
      </div>

      <div className="flex flex-col gap-2 sm:flex-row">
        <button
          className="inline-flex items-center justify-center rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 active:bg-blue-800"
          type="button"
        >
          Töltés indítása (QR)
        </button>

        <button
          className="inline-flex items-center justify-center rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
          type="button"
          onClick={() => {
            if (typeof cp.latitude !== "number" || typeof cp.longitude !== "number") return;
            window.open(`https://www.google.com/maps?q=${cp.latitude},${cp.longitude}`, "_blank");
          }}
        >
          Megnyitás Google Maps-ben
        </button>
      </div>

      <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
        Tipp: a “Start” gomb mögé jön a zárolás + RemoteStartTransaction.
      </div>
    </div>
  );
}