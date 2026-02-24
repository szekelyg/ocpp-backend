import StatusBadge from "../ui/StatusBadge";
import { placeLines, formatHu } from "../../utils/format";

export default function ChargerListItem({ cp, selected, onClick }) {
  const lines = placeLines(cp);

  return (
    <div
      className="item"
      onClick={onClick}
      style={{
        outline: selected ? "2px solid rgba(59,130,246,0.35)" : "none",
        cursor: "pointer",
      }}
    >
      <div className="itemTop">
        <div className="itemId">{cp.ocpp_id}</div>
        <StatusBadge status={cp.status} />
      </div>

      <div className="itemMeta">
        {lines[0]}
        {lines[1] ? (
          <>
            <br />
            {lines[1]}
          </>
        ) : null}
      </div>

      <div style={{ marginTop: 8, fontSize: 12, opacity: 0.8 }}>
        Utoljára: {formatHu(cp.last_seen_at)}
      </div>
    </div>
  );
}