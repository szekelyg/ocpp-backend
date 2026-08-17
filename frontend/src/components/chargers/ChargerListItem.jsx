import StatusBadge from "../ui/StatusBadge";
import { placeLines, timeAgo } from "../../utils/format";
import { isPowerLimited } from "../../utils/power";

export default function ChargerListItem({ cp, selected, onClick }) {
  const lines = placeLines(cp);

  return (
    <button
      type="button"
      onClick={onClick}
      className={["listItem", selected ? "listItemSelected" : ""].join(" ")}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="text-sm font-semibold text-ink leading-tight">
          {lines[0] || cp.ocpp_id || "—"}
        </div>
        <StatusBadge status={cp.status} />
      </div>

      {lines[1] && (
        <div className="mt-1 text-xs text-ink-muted leading-snug">{lines[1]}</div>
      )}

      {(cp.connector_type || cp.max_power_kw) && (
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {cp.connector_type && <span className="chip">{cp.connector_type}</span>}
          {cp.max_power_kw && (
            <span className={isPowerLimited(cp) ? "chipWarn" : "chip"}>
              max. {cp.max_power_kw} kW
            </span>
          )}
        </div>
      )}

      {cp.price_huf_per_kwh > 0 && (
        <div className="mt-2 text-xs text-[#037a5c] font-semibold">
          {cp.price_huf_per_kwh.toLocaleString("hu-HU")} Ft/kWh
        </div>
      )}

      <div className="mt-1.5 flex items-center justify-between gap-2">
        <span className="text-xs text-ink-muted">Aktív: {timeAgo(cp.last_seen_at)}</span>
        {cp.latitude && cp.longitude && (
          <a
            href={`https://maps.google.com/?q=${cp.latitude},${cp.longitude}`}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="text-xs text-brand-action hover:underline shrink-0 font-medium"
          >
            📍 Navigáció
          </a>
        )}
      </div>
    </button>
  );
}
