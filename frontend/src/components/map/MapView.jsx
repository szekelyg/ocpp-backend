import { MapContainer, TileLayer, Marker, Popup, useMap } from "react-leaflet";
import { useEffect } from "react";
import FitToMarkers from "./FitToMarkers";
import StatusBadge from "../ui/StatusBadge";
import { placeLines } from "../../utils/format";

function InvalidateSize() {
  const map = useMap();

  useEffect(() => {
    // 1) azonnali + 2) következő tick + 3) kis késleltetés: biztosan jó lesz
    map.invalidateSize();
    const t1 = setTimeout(() => map.invalidateSize(), 0);
    const t2 = setTimeout(() => map.invalidateSize(), 200);

    const onResize = () => map.invalidateSize();
    window.addEventListener("resize", onResize);

    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
      window.removeEventListener("resize", onResize);
    };
  }, [map]);

  return null;
}

export default function MapView({ points = [], onSelect }) {
  const centerFallback = [47.49, 18.94];

  return (
    <MapContainer center={centerFallback} zoom={12} scrollWheelZoom className="h-full w-full">
      <InvalidateSize />

      <TileLayer
        attribution="&copy; OpenStreetMap"
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />

      <FitToMarkers points={points} />

      {points.map((cp) => {
        if (typeof cp.latitude !== "number" || typeof cp.longitude !== "number") return null;
        const lines = placeLines(cp);

        return (
          <Marker key={cp.id} position={[cp.latitude, cp.longitude]} eventHandlers={{ click: () => onSelect(cp.id) }}>
            <Popup>
              <div className="space-y-2 text-sm">
                <div className="font-semibold">{cp.ocpp_id}</div>
                <StatusBadge status={cp.status} />
                <div>{lines[0]}</div>
                {lines[1] && <div className="text-slate-500">{lines[1]}</div>}
              </div>
            </Popup>
          </Marker>
        );
      })}
    </MapContainer>
  );
}