import { MapContainer, TileLayer, Marker, useMap, useMapEvents } from "react-leaflet";
import L from "leaflet";
import { useEffect } from "react";

// Kis ellenőrző térkép a töltő beállításához: a telefon GPS-e a ház tövében
// pár tíz métert is tévedhet, a marker viszont ugyanaz, amit a vásárló lát.
// Ezért nem csak megjelenít: kattintással és a marker húzásával igazítható is.

const PIN = L.divIcon({
  html: `
    <svg xmlns="http://www.w3.org/2000/svg" width="28" height="36" viewBox="0 0 28 36">
      <path d="M14 0C6.27 0 0 6.27 0 14c0 9.33 14 22 14 22S28 23.33 28 14C28 6.27 21.73 0 14 0z"
            fill="#2f62da" stroke="white" stroke-width="1.5"/>
      <circle cx="14" cy="14" r="6" fill="white" opacity="0.9"/>
    </svg>`.trim(),
  className: "",
  iconSize: [28, 36],
  iconAnchor: [14, 36],
});

// A modal nyitásakor a térkép konténere csak utólag kap méretet – nélküle
// szürke csempéket kapnánk.
function InvalidateOnOpen() {
  const map = useMap();
  useEffect(() => {
    const timers = [0, 150, 400].map((d) => setTimeout(() => map.invalidateSize(), d));
    return () => timers.forEach(clearTimeout);
  }, [map]);
  return null;
}

// Csak akkor ugrunk a ponthoz, ha kilátszott a képből – így a marker húzása
// nem rántja el a térképet a szem alól.
function KeepPointVisible({ lat, lng }) {
  const map = useMap();
  useEffect(() => {
    if (!map.getBounds().contains([lat, lng])) map.setView([lat, lng], map.getZoom());
  }, [map, lat, lng]);
  return null;
}

function ClickToPlace({ onPick }) {
  useMapEvents({ click: (e) => onPick(e.latlng.lat, e.latlng.lng) });
  return null;
}

export default function CoordPicker({ lat, lng, onPick }) {
  return (
    <div className="overflow-hidden rounded-xl border border-brand-line">
      <MapContainer center={[lat, lng]} zoom={17} scrollWheelZoom={false} className="h-48 w-full">
        <InvalidateOnOpen />
        <KeepPointVisible lat={lat} lng={lng} />
        <ClickToPlace onPick={onPick} />
        <TileLayer
          attribution="&copy; OpenStreetMap"
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <Marker
          position={[lat, lng]}
          icon={PIN}
          draggable
          eventHandlers={{
            dragend: (e) => {
              const p = e.target.getLatLng();
              onPick(p.lat, p.lng);
            },
          }}
        />
      </MapContainer>
    </div>
  );
}
