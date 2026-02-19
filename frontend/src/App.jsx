import { useEffect, useMemo, useRef, useState } from "react";
import {
  MapContainer,
  TileLayer,
  Marker,
  Popup,
  useMap,
} from "react-leaflet";
import "leaflet/dist/leaflet.css";
import L from "leaflet";


// Fix Leaflet marker icon paths (Vite alatt gyakran “eltűnik”)
import markerIcon2x from "leaflet/dist/images/marker-icon-2x.png";
import markerIcon from "leaflet/dist/images/marker-icon.png";
import markerShadow from "leaflet/dist/images/marker-shadow.png";

delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: markerIcon2x,
  iconUrl: markerIcon,
  shadowUrl: markerShadow,
});

// ---- helpers ----
const PRICE_HUF_PER_KWH = 1;      // MVP: 1 Ft/kWh
const PREAUTH_HUF = 5000;         // MVP: 5000 Ft zárolás

function fmtDateTime(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString("hu-HU");
  } catch {
    return iso;
  }
}

function statusBadgeClass(status) {
  const s = (status || "").toLowerCase();
  if (s.includes("charging")) return "badge badge--charging";
  if (s.includes("available")) return "badge badge--ok";
  if (s.includes("fault") || s.includes("error")) return "badge badge--bad";
  return "badge";
}

function calcMapCenter(points) {
  const withCoords = points.filter(
    (p) => typeof p.latitude === "number" && typeof p.longitude === "number"
  );
  if (!withCoords.length) return [47.4979, 19.0402]; // Budapest fallback
  const lat = withCoords.reduce((a, p) => a + p.latitude, 0) / withCoords.length;
  const lon = withCoords.reduce((a, p) => a + p.longitude, 0) / withCoords.length;
  return [lat, lon];
}

function FitToMarkers({ points }) {
  const map = useMap();
  const didFit = useRef(false);

  useEffect(() => {
    // csak első betöltésnél fitBounds (ne rángassa a usert)
    if (didFit.current) return;
    const coords = points
      .filter((p) => typeof p.latitude === "number" && typeof p.longitude === "number")
      .map((p) => [p.latitude, p.longitude]);
    if (!coords.length) return;

    const b = L.latLngBounds(coords);
    map.fitBounds(b.pad(0.25));
    didFit.current = true;
  }, [map, points]);

  return null;
}

export default function App() {
  const [items, setItems] = useState([]);
  const [selectedId, setSelectedId] = useState(null);

  const [q, setQ] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");

  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [lastUpdated, setLastUpdated] = useState(null);

  async function load() {
    setErr("");
    setLoading(true);
    try {
      const r = await fetch("/api/charge-points/");
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      setItems(Array.isArray(data) ? data : []);
      setLastUpdated(new Date());
      // ha eddig semmi nem volt kiválasztva, válasszuk az elsőt
      if (!selectedId && Array.isArray(data) && data.length) {
        setSelectedId(data[0].id);
      }
    } catch (e) {
      setErr(e?.message || "Ismeretlen hiba");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    const t = setInterval(load, 30_000); // 30s auto refresh
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return items.filter((cp) => {
      const matchesQ =
        !needle ||
        (cp.ocpp_id || "").toLowerCase().includes(needle) ||
        (cp.location_name || "").toLowerCase().includes(needle) ||
        (cp.address_text || "").toLowerCase().includes(needle);

      const s = (cp.status || "").toLowerCase();
      const matchesStatus =
        statusFilter === "all" ||
        (statusFilter === "available" && s.includes("available")) ||
        (statusFilter === "charging" && s.includes("charging")) ||
        (statusFilter === "offline" && (s.includes("offline") || s.includes("unavailable"))) ||
        (statusFilter === "error" && (s.includes("fault") || s.includes("error")));

      return matchesQ && matchesStatus;
    });
  }, [items, q, statusFilter]);

  const selected = useMemo(
    () => items.find((x) => x.id === selectedId) || null,
    [items, selectedId]
  );

  const center = useMemo(() => calcMapCenter(items), [items]);

  return (
    <div className="page">
      <header className="topbar">
        <div className="brand">
          <div className="brand__title">EV Charging</div>
          <div className="brand__sub">Térkép • Töltők • Indítás QR-rel (MVP)</div>
        </div>

        <div className="topbar__right">
          <div className="pill">
            <span className="muted">Ár:</span> {PRICE_HUF_PER_KWH} Ft/kWh
          </div>
          <div className="pill">
            <span className="muted">Zárolás:</span> {PREAUTH_HUF} Ft
          </div>
          <button className="btn btn--ghost" onClick={load} disabled={loading}>
            {loading ? "Frissítés…" : "Frissítés"}
          </button>
        </div>
      </header>

      <main className="layout">
        <section className="mapCard">
          <div className="mapCard__header">
            <div>
              <div className="h2">Térkép</div>
              <div className="muted small">
                Utolsó frissítés:{" "}
                {lastUpdated ? lastUpdated.toLocaleString("hu-HU") : "—"}
                {err ? <span className="error"> • Hiba: {err}</span> : null}
              </div>
            </div>

            <div className="mapCard__headerRight">
              <div className="stat">
                <div className="stat__k">Töltők</div>
                <div className="stat__v">{items.length}</div>
              </div>
              <div className="stat">
                <div className="stat__k">Szűrt</div>
                <div className="stat__v">{filtered.length}</div>
              </div>
            </div>
          </div>

          <div className="mapWrap">
            <MapContainer center={center} zoom={11} scrollWheelZoom className="map">
              <TileLayer
                attribution='&copy; OpenStreetMap'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              />
              <FitToMarkers points={items} />

              {filtered
                .filter((cp) => typeof cp.latitude === "number" && typeof cp.longitude === "number")
                .map((cp) => (
                  <Marker
                    key={cp.id}
                    position={[cp.latitude, cp.longitude]}
                    eventHandlers={{
                      click: () => setSelectedId(cp.id),
                    }}
                  >
                    <Popup>
                      <div style={{ minWidth: 220 }}>
                        <div style={{ fontWeight: 800 }}>{cp.ocpp_id}</div>
                        <div className="small muted">{cp.location_name || "—"}</div>
                        <div className="small muted">{cp.address_text || "—"}</div>
                        <div style={{ marginTop: 8 }}>
                          <span className={statusBadgeClass(cp.status)}>
                            {cp.status || "unknown"}
                          </span>
                        </div>
                      </div>
                    </Popup>
                  </Marker>
                ))}
            </MapContainer>
          </div>
        </section>

        <aside className="side">
          <div className="card">
            <div className="card__title">Töltők</div>

            <div className="controls">
              <input
                className="input"
                placeholder="Keresés: ID / hely / cím…"
                value={q}
                onChange={(e) => setQ(e.target.value)}
              />

              <div className="row">
                <select
                  className="select"
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                >
                  <option value="all">Minden státusz</option>
                  <option value="available">Available</option>
                  <option value="charging">Charging</option>
                  <option value="offline">Offline/Unavailable</option>
                  <option value="error">Fault/Error</option>
                </select>

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
            </div>

            <div className="list">
              {filtered.map((cp) => (
                <button
                  key={cp.id}
                  className={"listItem " + (cp.id === selectedId ? "listItem--active" : "")}
                  onClick={() => setSelectedId(cp.id)}
                >
                  <div className="listItem__top">
                    <div className="listItem__id">{cp.ocpp_id}</div>
                    <span className={statusBadgeClass(cp.status)}>{cp.status || "unknown"}</span>
                  </div>
                  <div className="listItem__sub">{cp.location_name || "—"}</div>
                  <div className="listItem__sub muted">{cp.address_text || "—"}</div>
                </button>
              ))}

              {!loading && !filtered.length ? (
                <div className="empty">Nincs találat.</div>
              ) : null}
            </div>
          </div>

          <div className="card">
            <div className="card__title">Kiválasztott töltő</div>

            {selected ? (
              <div className="detail">
                <div className="detail__row">
                  <div className="detail__k">OCPP ID</div>
                  <div className="detail__v">{selected.ocpp_id}</div>
                </div>

                <div className="detail__row">
                  <div className="detail__k">Hely</div>
                  <div className="detail__v">{selected.location_name || "—"}</div>
                </div>

                <div className="detail__row">
                  <div className="detail__k">Cím</div>
                  <div className="detail__v">{selected.address_text || "—"}</div>
                </div>

                <div className="detail__row">
                  <div className="detail__k">Státusz</div>
                  <div className="detail__v">
                    <span className={statusBadgeClass(selected.status)}>
                      {selected.status || "unknown"}
                    </span>
                  </div>
                </div>

                <div className="detail__row">
                  <div className="detail__k">Utoljára látva</div>
                  <div className="detail__v">{fmtDateTime(selected.last_seen_at)}</div>
                </div>

                <div className="divider" />

                <div className="actions">
                  <button
                    className="btn btn--primary"
                    onClick={() => alert("MVP: itt jön majd a QR / fizetés / Start flow")}
                  >
                    Töltés indítása (QR)
                  </button>

                  <button
                    className="btn btn--ghost"
                    onClick={() => {
                      const lat = selected.latitude;
                      const lon = selected.longitude;
                      if (typeof lat === "number" && typeof lon === "number") {
                        window.open(`https://www.google.com/maps?q=${lat},${lon}`, "_blank");
                      } else {
                        alert("Nincs koordináta ehhez a töltőhöz.");
                      }
                    }}
                  >
                    Megnyitás Google Maps-ben
                  </button>
                </div>

                <div className="hint">
                  Tipp: a “Start” gomb mögé később megy a zárolás (5000 Ft), majd a RemoteStartTransaction.
                </div>
              </div>
            ) : (
              <div className="empty">Válassz ki egy töltőt a listából.</div>
            )}
          </div>
        </aside>
      </main>

      <footer className="footer">
        <span className="muted small">
          MVP • térkép + lista • QR indítás + fizetés jön (SimplePay/Stripe).
        </span>
      </footer>
    </div>
  );
}