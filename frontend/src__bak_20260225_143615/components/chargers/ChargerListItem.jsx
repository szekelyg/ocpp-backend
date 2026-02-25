import StatusBadge from "../ui/StatusBadge";
import { placeLines, formatHu } from "../../utils/format";

export default function ChargerListItem({ cp, selected, onClick }) {
  const lines = placeLines(cp);

  return (
    <div
      onClick={onClick}
      className={`
        rounded-xl border bg-white p-4 transition cursor-pointer
        ${selected
          ? "border-blue-400 ring-4 ring-blue-100"
          : "border-slate-200 hover:border-slate-300 hover:shadow-sm"}
      `}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="text-sm font-semibold text-slate-800">
          {cp.ocpp_id}
        </div>

        <StatusBadge status={cp.status} />
      </div>

      <div className="mt-2 text-sm text-slate-600 leading-snug">
        {lines[0]}
        {lines[1] && (
          <>
            <br />
            {lines[1]}
          </>
        )}
      </div>

      <div className="mt-3 text-xs text-slate-500">
        Utoljára: {formatHu(cp.last_seen_at)}
      </div>
    </div>
  );
}