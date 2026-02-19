import { useEffect, useMemo, useState } from "react";
import "./App.css";

import { MapContainer, TileLayer, Marker, Popup, useMap } from "react-leaflet";

function FitToMarkers({ points }) {
  const map = useMap();

  useEffect(() => {
    if (!points?.length) return;

    const valid = points
      .filter((p) => typeof p.latitude === "number" && typeof p.longitude === "number")
      .map((p) => [p.latitude, p.longitude]);

    if (valid.length === 0) return;

    if (valid.length === 1) {
      map.setView(valid[0], 13, { animate: true });
      return;
    }

    const L = window.L;
    if (!L) return;

    const bounds = L.latLngBounds(valid);
    map.fitBounds(bounds, { padding: [30, 30] });
  }, [map, points]);

  return null;
}

function formatHu(dtIso) {
  if (!dtIso) return "—";
  const d = new Date(dtIso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("hu-HU");
}

function norm(s) {
  return (s || "").trim().replace(/\s+/g, " ").toLowerCase();
}

function placeLines(cp) {
  const a = (cp?.location_name || "").trim();
  const b = (cp?.address_text || "").trim();
  if (!a && !b) return ["—"];
  if (a && !b) return [a];
  if (!a && b) return [b];
  if (norm(a) === norm(b)) return [a]; // ugyanaz -> egyszer
  return [a, b];
}

export default function App() {
  const PRICE_FT_PER_KWH = 1;
  const HOLD_FT = 5000;

  const [items, setItems] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [q, setQ] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [lastUpdated, setLastUpdated] = useState(null);
  const [loading, setLoading] = useState(false);

  async function refresh() {
    try {
      setLoading(true);
      const res = await fetch("/api/charge-points/");
      const data = await res.json();
      setItems(Array.isArray(data) ? data : []);
      setLastUpdated(new Date());
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, []);

  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase();
    return items.filter((cp) => {
      const okStatus =
        statusFilter === "all"
          ? true
          : (cp.status || "").toLowerCase() === statusFilter;

      const hay = `${cp.ocpp_id || ""} ${cp.location_name || ""} ${cp.address_text || ""}`.toLowerCase();
      const okQ = s ? hay.includes(s) : true;
      return okStatus && okQ;
    });
  }, [items, q, statusFilter]);

  const selected = useMemo(() => {
    return items.find((x) => x.id === selectedId) || filtered[0] || null;
  }, [items, filtered, selectedId]);

  useEffect(() => {
    if (selected && selectedId == null) setSelectedId(selected.id);
  }, [selected, selectedId]);

  const statuses = useMemo(() => {
    const set = new Set(items.map((x) => (x.status || "").toLowerCase()).filter(Boolean));
    return ["all", ...Array.from(set)];
  }, [items]);

  const mapPoints = useMemo(() => filtered, [filtered]);

  const centerFallback = [47.49, 18.94];

  return (
    <div className="app">
      <div className="header">
        <div className="brand">
          <h1>EV Charging</h1>
          <p>Térkép • Töltők • Indítás QR-rel (MVP)</p>
        </div>

        <div className="pills">
          <div className="pill">Ár: {PRICE_FT_PER_KWH} Ft/kWh</div>
          <div className="pill">Zárolás: {HOLD_FT} Ft</div>
          <button className="btn" onClick={refresh} disabled={loading}>
            {loading ? "Frissítés..." : "Frissítés"}
          </button>
        </div>
      </div>

      <hr className="sep" />

      <div className="grid">
        <div className="card">
          <div className="cardHeader">
            <div>
              <div className="cardTitle">Térkép</div>
              <div className="cardSub">
                Utolsó frissítés: {lastUpdated ? lastUpdated.toLocaleString("hu-HU") : "—"}
              </div>
            </div>
            <div className="kpis">
              <div className="kpi">
                <div className="label">Töltők</div>
                <div className="val">{items.length}</div>
              </div>
              <div className="kpi">
                <div className="label">Szűrt</div>
                <div className="val">{filtered.length}</div>
              </div>
            </div>
          </div>

          <div className="cardBody">
            <div className="mapWrap">
              <MapContainer center={centerFallback} zoom={12} scrollWheelZoom>
                <TileLayer
                  attribution="&copy; OpenStreetMap"
                  url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                />

                <FitToMarkers points={mapPoints} />

                {mapPoints.map((cp) => {
                  if (typeof cp.latitude !== "number" || typeof cp.longitude !== "number") return null;

                  const lines = placeLines(cp);

                  return (
                    <Marker
                      key={cp.id}
                      position={[cp.latitude, cp.longitude]}
                      eventHandlers={{
                        click: () => setSelectedId(cp.id),
                      }}
                    >
                      <Popup>
                        <div style={{ minWidth: 180 }}>
                          <b>{cp.ocpp_id}</b>
                          <div>{lines[0]}</div>
                          {lines[1] ? (
                            <div style={{ opacity: 0.8, fontSize: 12 }}>{lines[1]}</div>
                          ) : null}
                          <div style={{ marginTop: 6 }}>
                            státusz: <b>{cp.status}</b>
                          </div>
                        </div>
                      </Popup>
                    </Marker>
                  );
                })}
              </MapContainer>
            </div>
          </div>
        </div>

        <div className="rightCol">
          <div className="card">
            <div className="cardHeader">
              <div>
                <div className="cardTitle">Töltők</div>
                <div className="cardSub">Keresés + szűrés</div>
              </div>
            </div>
            <div className="cardBody">
              <div className="toolbar">
                <input
                  className="input"
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  placeholder="Keresés: ID / hely / cím…"
                />
                <button
                  className="btn"
                  onClick={() => {
                    setQ("");
                    setStatusFilter("all");
                  }}
                >
                  Reset
                </button>
              </div>

              <select
                className="select"
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
              >
                {statuses.map((s) => (
                  <option key={s} value={s}>
                    {s === "all" ? "Minden státusz" : s}
                  </option>
                ))}
              </select>

              <div style={{ height: 10 }} />

              <div className="list">
                {filtered.map((cp) => {
                  const lines = placeLines(cp);
                  return (
                    <div
                      key={cp.id}
                      className="item"
                      onClick={() => setSelectedId(cp.id)}
                      style={{
                        outline: selected?.id === cp.id ? "2px solid rgba(59,130,246,0.35)" : "none",
                      }}
                    >
                      <div className="itemTop">
                        <div className="itemId">{cp.ocpp_id}</div>
                        <div className="badge">{cp.status || "unknown"}</div>
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
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          <div className="card">
            <div className="cardHeader">
              <div>
                <div className="cardTitle">Kiválasztott töltő</div>
                <div className="cardSub">Indítás QR-rel / később fizetés</div>
              </div>
            </div>

            <div className="cardBody">
              {!selected ? (
                <div style={{ color: "var(--muted)" }}>Nincs kiválasztott töltő.</div>
              ) : (
                <>
                  <div className="detailGrid">
                    <div className="key">OCPP ID</div>
                    <div className="val">
                      <b>{selected.ocpp_id}</b>
                    </div>

                    <div className="key">Hely</div>
                    <div className="val">{placeLines(selected)[0] || "—"}</div>

                    <div className="key">Cím</div>
                    <div className="val">{placeLines(selected)[1] || "—"}</div>

                    <div className="key">Státusz</div>
                    <div className="val">
                      <span className="badge">{selected.status || "unknown"}</span>
                    </div>

                    <div className="key">Utoljára látva</div>
                    <div className="val">{formatHu(selected.last_seen_at)}</div>
                  </div>

                  <div className="actions">
                    <button className="btn btnPrimary">Töltés indítása (QR)</button>

                    <button
                      className="btn btnGhost"
                      onClick={() => {
                        if (typeof selected.latitude !== "number" || typeof selected.longitude !== "number") return;
                        const url = `https://www.google.com/maps?q=${selected.latitude},${selected.longitude}`;
                        window.open(url, "_blank");
                      }}
                    >
                      Megnyitás Google Maps-ben
                    </button>
                  </div>

                  <div className="footerNote">
                    Tipp: a “Start” gomb mögé később megy a zárolás (5000 Ft), majd a RemoteStartTransaction.
                  </div>
                </>
              )}
            </div>
          </div>

          <div className="smallFooter">MVP • térkép + lista • QR indítás + fizetés jön (SimplePay/Stripe).</div>
        </div>
      </div>
    </div>
  );
}