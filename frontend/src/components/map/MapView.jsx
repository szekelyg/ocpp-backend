import { MapContainer, TileLayer, Marker, Popup } from "react-leaflet";
import FitToMarkers from "./FitToMarkers";
import StatusBadge from "../ui/StatusBadge";
import { placeLines } from "../../utils/format";

export default function MapView({ points, onSelect }) {
  const centerFallback = [47.49, 18.94];

  return (
    <MapContainer center={centerFallback} zoom={12} scrollWheelZoom>
      <TileLayer
        attribution="&copy; OpenStreetMap"
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />

      <FitToMarkers points={points} />

      {points.map((cp) => {
        if (typeof cp.latitude !== "number" || typeof cp.longitude !== "number") return null;

        const lines = placeLines(cp);

        return (
          <Marker
            key={cp.id}
            position={[cp.latitude, cp.longitude]}
            eventHandlers={{ click: () => onSelect(cp.id) }}
          >
            <Popup>
              <b>{cp.ocpp_id}</b>
              <div style={{ marginTop: 6 }}>
                <StatusBadge status={cp.status} />
              </div>
              <div style={{ marginTop: 6 }}>{lines[0]}</div>
              {lines[1] && <div style={{ opacity: 0.8 }}>{lines[1]}</div>}
            </Popup>
          </Marker>
        );
      })}
    </MapContainer>
  );
}