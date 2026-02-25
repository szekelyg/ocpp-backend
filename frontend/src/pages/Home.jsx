import { useEffect, useMemo, useState } from "react";

import MapView from "../components/map/MapView";
import ChargerList from "../components/chargers/ChargerList";
import SelectedChargerCard from "../components/chargers/SelectedChargerCard";
import ChargerToolbar from "../components/chargers/ChargerToolbar";

export default function Home() {
  const [items, setItems] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);

  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");

  async function refresh() {
    const res = await fetch("/api/charge-points/");
    const data = await res.json();
    setItems(Array.isArray(data) ? data : []);
    setLastUpdated(new Date());
  }

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();

    return items.filter((cp) => {
      const status = (cp.status || "").toLowerCase();

      const matchStatus =
        statusFilter === "all" ? true : status === statusFilter;

      const hay =
        `${cp.ocpp_id || ""} ${cp.location_name || ""} ${cp.address_text || ""}`.toLowerCase();

      const matchQuery = q ? hay.includes(q) : true;

      return matchStatus && matchQuery;
    });
  }, [items, query, statusFilter]);

  const selected = useMemo(() => {
    return filtered.find((x) => x.id === selectedId) || filtered[0] || null;
  }, [filtered, selectedId]);

  useEffect(() => {
    if (filtered.length && selectedId == null) {
      setSelectedId(filtered[0].id);
    }
  }, [filtered, selectedId]);

  function resetFilters() {
    setQuery("");
    setStatusFilter("all");
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <div className="mx-auto max-w-7xl p-6 space-y-6">
  
        {/* HEADER */}
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
          <div>
            <h1 className="text-3xl font-semibold tracking-tight">
              EV Charging
            </h1>
            <p className="text-slate-400 text-sm">
              Térkép • Töltők • Fizetés + indítás
            </p>
          </div>
  
          <div className="flex items-center gap-3">
            <div className="text-sm bg-slate-800 px-3 py-1.5 rounded-xl">
              Utolsó frissítés:{" "}
              {lastUpdated ? lastUpdated.toLocaleString("hu-HU") : "—"}
            </div>
  
            <button
              onClick={refresh}
              className="px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 transition"
            >
              Frissítés
            </button>
          </div>
        </div>
  
        {/* GRID */}
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
  
          {/* MAP */}
          <div className="xl:col-span-2 bg-slate-900 rounded-2xl shadow overflow-hidden flex flex-col">
            <div className="px-5 py-4 border-b border-slate-800 flex justify-between items-center">
              <div>
                <div className="font-medium">Térkép</div>
                <div className="text-xs text-slate-400">
                  Töltők: {filtered.length}
                </div>
              </div>
            </div>
  
            <div className="flex-1 min-h-[400px]">
              <MapView points={filtered} onSelect={setSelectedId} />
            </div>
          </div>
  
          {/* RIGHT COLUMN */}
          <div className="space-y-6">
  
            {/* LIST */}
            <div className="bg-slate-900 rounded-2xl shadow">
              <div className="px-5 py-4 border-b border-slate-800">
                <div className="font-medium">Töltők</div>
                <div className="text-xs text-slate-400">
                  Keresés + szűrés
                </div>
              </div>
  
              <div className="p-5 space-y-4">
                <ChargerToolbar
                  items={items}
                  query={query}
                  setQuery={setQuery}
                  statusFilter={statusFilter}
                  setStatusFilter={setStatusFilter}
                  onReset={resetFilters}
                />
  
                <ChargerList
                  items={filtered}
                  selectedId={selectedId}
                  onSelect={setSelectedId}
                />
              </div>
            </div>
  
            {/* SELECTED */}
            <div className="bg-slate-900 rounded-2xl shadow">
              <div className="px-5 py-4 border-b border-slate-800">
                <div className="font-medium">Kiválasztott töltő</div>
                <div className="text-xs text-slate-400">
                  Fizetés + indítás
                </div>
              </div>
  
              <div className="p-5">
                <SelectedChargerCard cp={selected} />
              </div>
            </div>
  
            <div className="text-xs text-slate-500 text-center">
              MVP • moduláris frontend • production-ready alap
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}