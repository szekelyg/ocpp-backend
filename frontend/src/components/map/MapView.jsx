import {
  MapContainer,
  TileLayer,
  Marker,
  CircleMarker,
  Popup,
  useMap,
  useMapEvents,
} from "react-leaflet";
import L from "leaflet";
import { useEffect, useMemo, useRef, useState } from "react";
import StatusBadge from "../ui/StatusBadge";
import { placeLines } from "../../utils/format";

// Státusz → szín
// A matrica-paletta színei
const STATUS_COLOR = {
  available:     "#04cd99", // brand zöld
  charging:      "#6699ff", // brand kék
  preparing:     "#ffcd60", // brand sárga
  finishing:     "#ffcd60", // brand sárga
  faulted:       "#ef4444", // piros
  unavailable:   "#ef4444", // piros
  reserved:      "#a855f7", // lila
  offline:       "#949eb0", // szürke
};

function statusColor(status) {
  return STATUS_COLOR[String(status || "").toLowerCase()] || "#949eb0";
}

function makeIcon(color) {
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="28" height="36" viewBox="0 0 28 36">
      <path d="M14 0C6.27 0 0 6.27 0 14c0 9.33 14 22 14 22S28 23.33 28 14C28 6.27 21.73 0 14 0z"
            fill="${color}" stroke="white" stroke-width="1.5"/>
      <circle cx="14" cy="14" r="6" fill="white" opacity="0.9"/>
    </svg>`.trim();
  return L.divIcon({
    html: svg,
    className: "",
    iconSize: [28, 36],
    iconAnchor: [14, 36],
    popupAnchor: [0, -36],
  });
}

// In-memory view cache (page refreshig él)
const viewCache = {
  hasUserView: false,
  center: null, // [lat,lng]
  zoom: null,
};

function InvalidateSize() {
  const map = useMap();

  useEffect(() => {
    // ha a konténer épp most kapott magasságot (grid/flex), ez kell
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

function ViewPersistence() {
  const map = useMap();
  const restoringRef = useRef(false);

  // mountkor: ha volt user view, állítsuk vissza
  useEffect(() => {
    if (!viewCache.hasUserView || !viewCache.center || viewCache.zoom == null) return;

    restoringRef.current = true;
    map.setView(viewCache.center, viewCache.zoom, { animate: false });

    // engedjük el a restore flag-et kicsit később
    const t = setTimeout(() => {
      restoringRef.current = false;
    }, 150);

    return () => clearTimeout(t);
  }, [map]);

  // user move/zoom után: mentsük a view-t
  useMapEvents({
    moveend: () => {
      if (restoringRef.current) return;
      const c = map.getCenter();
      viewCache.center = [c.lat, c.lng];
      viewCache.zoom = map.getZoom();
      viewCache.hasUserView = true;
    },
    zoomend: () => {
      if (restoringRef.current) return;
      const c = map.getCenter();
      viewCache.center = [c.lat, c.lng];
      viewCache.zoom = map.getZoom();
      viewCache.hasUserView = true;
    },
    dragstart: () => {
      // jelzi, hogy user interakció történt
      viewCache.hasUserView = true;
    },
  });

  return null;
}

// Csak akkor fitelünk automatikusan, ha NINCS user view még.
function FitInitialBounds({ points }) {
  const map = useMap();
  const didFitRef = useRef(false);

  useEffect(() => {
    if (didFitRef.current) return;
    if (viewCache.hasUserView) return;
    if (!points.length) return;

    const bounds = points.map((p) => [p.latitude, p.longitude]);
    map.fitBounds(bounds, { padding: [40, 40] });
    didFitRef.current = true;
  }, [map, points]);

  return null;
}

// "Hol vagyok?" gomb – NEM automatikus. Alapból marad az országos nézet;
// csak kattintásra kéri el a helyzetet és zoomol oda.
function LocateControl() {
  const map = useMap();
  const [userPos, setUserPos] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const btnRef = useRef(null);

  // a gombra kattintás ne mozgassa/zoomolja a térképet alatta
  useEffect(() => {
    if (!btnRef.current) return;
    L.DomEvent.disableClickPropagation(btnRef.current);
    L.DomEvent.disableScrollPropagation(btnRef.current);
  }, []);

  const locate = () => {
    if (!("geolocation" in navigator)) {
      setErr("A böngésződ nem támogatja a helymeghatározást.");
      return;
    }
    setBusy(true);
    setErr("");
    navigator.geolocation.getCurrentPosition(
      (p) => {
        const ll = [p.coords.latitude, p.coords.longitude];
        setUserPos(ll);
        viewCache.hasUserView = true; // ne fitelje vissza az egész országra
        map.flyTo(ll, 15, { duration: 0.8 });
        setBusy(false);
      },
      (e) => {
        setBusy(false);
        setErr(
          e.code === 1
            ? "Helymeghatározás letiltva a böngészőben."
            : "Nem sikerült a helymeghatározás."
        );
      },
      { enableHighAccuracy: true, timeout: 8000, maximumAge: 30000 }
    );
  };

  return (
    <>
      <div
        ref={btnRef}
        className="absolute top-3 right-3 z-[1000] flex flex-col items-end gap-2"
      >
        <button
          type="button"
          onClick={locate}
          disabled={busy}
          title="Hol vagyok?"
          aria-label="Hol vagyok?"
          className="flex items-center gap-1.5 rounded-full bg-white/95 hover:bg-white text-ink shadow-card border border-brand-line px-3 py-2 text-sm font-medium disabled:opacity-60 transition"
        >
          <span className="text-base leading-none">{busy ? "⏳" : "📍"}</span>
          <span className="hidden sm:inline">{busy ? "Keresés…" : "Hol vagyok?"}</span>
        </button>
        {err && (
          <div className="max-w-[220px] rounded-lg bg-red-600/95 text-white text-xs px-2.5 py-1.5 shadow-lg">
            {err}
          </div>
        )}
      </div>

      {userPos && (
        <CircleMarker
          center={userPos}
          radius={9}
          pathOptions={{ color: "#2f62da", weight: 3, fillColor: "#6699ff", fillOpacity: 0.5 }}
        >
          <Popup>Itt vagy</Popup>
        </CircleMarker>
      )}
    </>
  );
}

const STARTABLE = new Set(["available", "preparing", "finishing"]);

export default function MapView({ points = [], onSelect, onStartFlow }) {
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
      className="relative h-full w-full"
    >
      <InvalidateSize />
      <ViewPersistence />

      <TileLayer
        attribution="&copy; OpenStreetMap"
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />

      <FitInitialBounds points={mappable} />
      <LocateControl />

      {mappable.map((cp) => {
        const lines = placeLines(cp);
        return (
          <Marker
            key={cp.id}
            position={[cp.latitude, cp.longitude]}
            icon={makeIcon(statusColor(cp.status))}
            eventHandlers={{ click: () => onSelect(cp.id) }}
          >
            <Popup>
              <div className="space-y-2 text-sm">
                <div className="font-semibold">{cp.location_name || cp.ocpp_id}</div>
                <StatusBadge status={cp.status} />
                <div>{lines[0]}</div>
                {lines[1] ? <div className="text-ink-muted">{lines[1]}</div> : null}
                {(cp.connector_type || cp.max_power_kw) && (
                  <div className="flex flex-wrap gap-1">
                    {cp.connector_type && (
                      <span className="text-xs bg-brand-panel border border-brand-line rounded px-1.5 py-0.5 text-ink-soft">
                        {cp.connector_type}
                      </span>
                    )}
                    {cp.max_power_kw && (
                      <span className="text-xs bg-brand-panel border border-brand-line rounded px-1.5 py-0.5 text-ink-soft">
                        {cp.max_power_kw} kW
                      </span>
                    )}
                  </div>
                )}
                {cp.price_huf_per_kwh > 0 && (
                  <div className="font-semibold text-[#037a5c]">
                    {cp.price_huf_per_kwh.toLocaleString("hu-HU")} Ft/kWh
                  </div>
                )}
                {STARTABLE.has(String(cp.status || "").toLowerCase()) && (
                  <button
                    onClick={() => { onSelect(cp.id); onStartFlow?.(cp.id); }}
                    className="mt-1 w-full text-center bg-brand-action hover:bg-[#2451bd] text-white text-xs font-semibold py-1.5 px-3 rounded-lg"
                  >
                    ⚡ Töltés indítása
                  </button>
                )}
              </div>
            </Popup>
          </Marker>
        );
      })}
    </MapContainer>
  );
}