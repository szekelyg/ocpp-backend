import { useEffect } from "react";
import { useMap } from "react-leaflet";

export default function FitToMarkers({ points }) {
  const map = useMap();

  useEffect(() => {
    if (!points?.length) return;

    const valid = points
      .filter((p) => typeof p.latitude === "number" && typeof p.longitude === "number")
      .map((p) => [p.latitude, p.longitude]);

    if (!valid.length) return;

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