import StatusBadge from "../ui/StatusBadge";
import { placeLines, timeAgo } from "../../utils/format";

export default function ChargerListItem({ cp, selected, onClick }) {
  const lines = placeLines(cp);

  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "w-full text-left rounded-xl border p-4 transition",
        "bg-slate-950/30 border-slate-800 hover:bg-slate-900/60 hover:border-slate-700",
        "focus:outline-none focus:ring-2 focus:ring-blue-500/40",
        selected ? "ring-2 ring-blue-500/30 border-blue-500/40" : "",
      ].join(" ")}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="text-sm font-semibold text-slate-100 leading-tight">
          {lines[0] || cp.ocpp_id || "—"}
        </div>
        <StatusBadge status={cp.status} />
      </div>

      {lines[1] && (
        <div className="mt-1 text-xs text-slate-400 leading-snug">{lines[1]}</div>
      )}

      {(cp.connector_type || cp.max_power_kw) && (
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {cp.connector_type && (
            <span className="text-xs bg-slate-800 border border-slate-700 rounded px-1.5 py-0.5 text-slate-300">
              {cp.connector_type}
            </span>
          )}
          {cp.max_power_kw && (
            <span className="text-xs bg-slate-800 border border-slate-700 rounded px-1.5 py-0.5 text-slate-300">
              {cp.max_power_kw} kW
            </span>
          )}
        </div>
      )}

      {cp.price_huf_per_kwh > 0 && (
        <div className="mt-2 text-xs text-emerald-400 font-semibold">
          {cp.price_huf_per_kwh.toLocaleString("hu-HU")} Ft/kWh
        </div>
      )}

      <div className="mt-1.5 flex items-center justify-between gap-2">
        <span className="text-xs text-slate-500">Aktív: {timeAgo(cp.last_seen_at)}</span>
        {cp.latitude && cp.longitude && (
          <a
            href={`https://maps.google.com/?q=${cp.latitude},${cp.longitude}`}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="text-xs text-blue-400 hover:text-blue-300 shrink-0"
          >
            📍 Navigáció
          </a>
        )}
      </div>
    </button>
  );
}
