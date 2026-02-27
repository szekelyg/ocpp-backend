import {
  MapContainer,
  TileLayer,
  Marker,
  Popup,
  useMap,
  useMapEvents,
} from "react-leaflet";
import { useEffect, useMemo, useRef } from "react";
import StatusBadge from "../ui/StatusBadge";
import { placeLines } from "../../utils/format";

function InvalidateSize() {
  const map = useMap();

  useEffect(() => {
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

// Csak az első értelmes marker-készletnél fitelünk.
// Utána SOHA, kivéve ha explicit "Recenter" gombot csinálunk később.
function FitInitialBounds({ points }) {
  const map = useMap();
  const didFitRef = useRef(false);
  const userMovedRef = useRef(false);

  useMapEvents({
    dragstart: () => (userMovedRef.current = true),
    zoomstart: () => (userMovedRef.current = true),
  });

  useEffect(() => {
    if (didFitRef.current) return;
    if (userMovedRef.current) return;

    if (!points.length) return;

    const bounds = points.map((p) => [p.latitude, p.longitude]);
    map.fitBounds(bounds, { padding: [40, 40] });

    didFitRef.current = true;
  }, [map, points]);

  return null;
}

export default function MapView({ points = [], onSelect }) {
  const centerFallback = [47.49, 18.94];

  const mappable = useMemo(() => {
    return (points || []).filter(
      (p) => typeof p.latitude === "number" && typeof p.longitude === "number"
    );
  }, [points]);

  return (
    <MapContainer
      center={centerFallback}
      zoom={12}
      scrollWheelZoom
      className="h-full w-full"
    >
      <InvalidateSize />

      <TileLayer
        attribution="&copy; OpenStreetMap"
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />

      <FitInitialBounds points={mappable} />

      {mappable.map((cp) => {
        const lines = placeLines(cp);

        return (
          <Marker
            key={cp.id}
            position={[cp.latitude, cp.longitude]}
            eventHandlers={{ click: () => onSelect(cp.id) }}
          >
            <Popup>
              <div className="space-y-2 text-sm">
                <div className="font-semibold">{cp.ocpp_id}</div>
                <StatusBadge status={cp.status} />
                <div>{lines[0]}</div>
                {lines[1] ? (
                  <div className="text-slate-500">{lines[1]}</div>
                ) : null}
              </div>
            </Popup>
          </Marker>
        );
      })}
    </MapContainer>
  );
}