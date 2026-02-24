import StatusBadge from "../ui/StatusBadge";
import { placeLines, formatHu } from "../../utils/format";

export default function SelectedChargerCard({ cp }) {
  if (!cp) return <div style={{ color: "var(--muted)" }}>Nincs kiválasztott töltő.</div>;

  const lines = placeLines(cp);

  return (
    <>
      <div className="detailGrid">
        <div className="key">OCPP ID</div>
        <div className="val">
          <b>{cp.ocpp_id}</b>
        </div>

        <div className="key">Hely</div>
        <div className="val">{lines[0] || "—"}</div>

        <div className="key">Cím</div>
        <div className="val">{lines[1] || "—"}</div>

        <div className="key">Státusz</div>
        <div className="val" style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <StatusBadge status={cp.status} />
          <span style={{ fontSize: 12, opacity: 0.8 }}>
            (OCPP: <b>{(cp.status || "—").toString()}</b>)
          </span>
        </div>

        <div className="key">Utoljára látva</div>
        <div className="val">{formatHu(cp.last_seen_at)}</div>
      </div>

      <div className="actions">
        <button className="btn btnPrimary">Töltés indítása (QR)</button>

        <button
          className="btn btnGhost"
          onClick={() => {
            if (typeof cp.latitude !== "number" || typeof cp.longitude !== "number") return;
            const url = `https://www.google.com/maps?q=${cp.latitude},${cp.longitude}`;
            window.open(url, "_blank");
          }}
        >
          Megnyitás Google Maps-ben
        </button>
      </div>

      <div className="footerNote">
        Tipp: a “Start” gomb mögé jön a zárolás + RemoteStartTransaction.
      </div>
    </>
  );
}