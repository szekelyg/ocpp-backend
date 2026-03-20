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

      <div className="mt-2 flex items-center justify-between gap-2">
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
