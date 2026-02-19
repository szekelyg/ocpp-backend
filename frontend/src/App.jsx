import { useEffect, useMemo, useState } from "react";
import { MapContainer, TileLayer, Marker, Popup } from "react-leaflet";
import L from "leaflet";

// Fix: Leaflet marker ikon Vite alatt
import markerIcon2x from "leaflet/dist/images/marker-icon-2x.png";
import markerIcon from "leaflet/dist/images/marker-icon.png";
import markerShadow from "leaflet/dist/images/marker-shadow.png";

delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: markerIcon2x,
  iconUrl: markerIcon,
  shadowUrl: markerShadow,
});

export default function App() {
  const [chargers, setChargers] = useState([]);
  const [err, setErr] = useState("");

  async function load() {
    try {
      setErr("");
      const r = await fetch("/api/charge-points/");
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setChargers(await r.json());
    } catch (e) {
      setErr(String(e));
    }
  }

  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  const points = useMemo(
    () =>
      chargers
        .filter((c) => c.latitude != null && c.longitude != null)
        .map((c) => ({
          ...c,
          lat: Number(c.latitude),
          lng: Number(c.longitude),
        })),
    [chargers]
  );

  // középpont: első pont, vagy Budapest
  const center = points.length
    ? [points[0].lat, points[0].lng]
    : [47.4979, 19.0402];

  return (
    <div style={{ fontFamily: "Arial", padding: 16 }}>
      <h1 style={{ margin: "8px 0 16px" }}>EV Charging – Térkép</h1>

      {err && (
        <div style={{ color: "red", marginBottom: 12 }}>
          Hiba: {err}
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 16 }}>
        <div style={{ border: "1px solid #ddd", borderRadius: 12, overflow: "hidden" }}>
          <MapContainer center={center} zoom={12} style={{ height: "70vh", width: "100%" }}>
            <TileLayer
              attribution='&copy; OpenStreetMap'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />

            {points.map((cp) => (
              <Marker key={cp.id} position={[cp.lat, cp.lng]}>
                <Popup>
                  <div style={{ minWidth: 220 }}>
                    <div style={{ fontWeight: 700 }}>{cp.ocpp_id}</div>
                    <div>{cp.location_name || "—"}</div>
                    <div style={{ marginTop: 6 }}>
                      <b>Státusz:</b> {cp.status}
                    </div>
                    <div style={{ fontSize: 12, opacity: 0.7, marginTop: 6 }}>
                      last_seen: {cp.last_seen_at || "—"}
                    </div>
                  </div>
                </Popup>
              </Marker>
            ))}
          </MapContainer>
        </div>

        <div style={{ border: "1px solid #ddd", borderRadius: 12, padding: 12 }}>
          <h3 style={{ marginTop: 0 }}>Töltők</h3>
          {chargers.map((cp) => (
            <div key={cp.id} style={{ padding: "10px 0", borderBottom: "1px solid #eee" }}>
              <div style={{ fontWeight: 700 }}>{cp.ocpp_id}</div>
              <div style={{ fontSize: 12, opacity: 0.8 }}>{cp.location_name || "—"}</div>
              <div style={{ fontSize: 12 }}>
                státusz: <b>{cp.status}</b>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}