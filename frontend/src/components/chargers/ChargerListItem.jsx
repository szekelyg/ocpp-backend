import StatusBadge from "../ui/StatusBadge";
import { placeLines, formatHu } from "../../utils/format";

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
        <div className="text-sm font-semibold text-slate-100">
          {cp.ocpp_id || "—"}
        </div>
        <StatusBadge status={cp.status} />
      </div>

      <div className="mt-2 text-sm text-slate-300 leading-snug">
        {lines[0] || "—"}
        {lines[1] ? (
          <>
            <br />
            <span className="text-slate-400">{lines[1]}</span>
          </>
        ) : null}
      </div>

      <div className="mt-3 text-xs text-slate-400">
        Utoljára: {formatHu(cp.last_seen_at)}
      </div>
    </button>
  );
}