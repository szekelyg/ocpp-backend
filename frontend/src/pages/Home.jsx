import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import AppHeader from "../components/ui/AppHeader";
import MapView from "../components/map/MapView";
import ChargerList from "../components/chargers/ChargerList";
import SelectedChargerCard from "../components/chargers/SelectedChargerCard";
import ChargerToolbar from "../components/chargers/ChargerToolbar";

const REFRESH_MS = 5000;

export default function Home() {
  const [searchParams] = useSearchParams();
  const cpParam = searchParams.get("cp");

  const [items, setItems] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [autoOpenModal, setAutoOpenModal] = useState(false);
  const autoOpenDoneRef = useRef(false);

  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const abortRef = useRef(null);
  const modalOpenRef = useRef(false);

  const refresh = useCallback(async () => {
    if (abortRef.current) abortRef.current.abort();

    const ac = new AbortController();
    abortRef.current = ac;

    setLoading(true);
    setError("");

    try {
      const res = await fetch("/api/charge-points/", {
        signal: ac.signal,
        headers: { Accept: "application/json" },
      });

      if (!res.ok) throw new Error(`API hiba: ${res.status} ${res.statusText}`);

      const data = await res.json();

      if (!modalOpenRef.current) {
        setItems(Array.isArray(data) ? data : []);
        setLastUpdated(new Date());
      }
    } catch (e) {
      if (e?.name === "AbortError") return;
      setError(e?.message || "Ismeretlen hiba");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, REFRESH_MS);
    return () => {
      clearInterval(t);
      if (abortRef.current) abortRef.current.abort();
    };
  }, [refresh]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();

    return (items || []).filter((cp) => {
      const status = (cp.status || "").toString().trim().toLowerCase();
      const matchStatus = statusFilter === "all" ? true : status === statusFilter;

      const hay = `${cp.ocpp_id || ""} ${cp.location_name || ""} ${cp.address_text || ""}`.toLowerCase();
      const matchQuery = q ? hay.includes(q) : true;

      return matchStatus && matchQuery;
    });
  }, [items, query, statusFilter]);

  const selected = useMemo(() => {
    return filtered.find((x) => x.id === selectedId) || filtered[0] || null;
  }, [filtered, selectedId]);

  useEffect(() => {
    if (!filtered.length) {
      if (selectedId != null) setSelectedId(null);
      return;
    }
    if (selectedId == null) {
      setSelectedId(filtered[0].id);
      return;
    }
    if (!filtered.some((x) => x.id === selectedId)) {
      setSelectedId(filtered[0].id);
    }
  }, [filtered, selectedId]);

  // ?cp=<id> – töltő előválasztás és modal auto-nyitás (csak startolható státusznál)
  useEffect(() => {
    if (!cpParam || !items.length || autoOpenDoneRef.current) return;
    const cpId = parseInt(cpParam, 10);
    const match = items.find((x) => x.id === cpId);
    if (!match) return;
    autoOpenDoneRef.current = true;
    setSelectedId(match.id);
    const startable = new Set(["available", "preparing", "finishing"]);
    if (startable.has(String(match.status || "").toLowerCase())) {
      setAutoOpenModal(true);
    }
  }, [cpParam, items]);

  const resetFilters = useCallback(() => {
    setQuery("");
    setStatusFilter("all");
  }, []);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
      <AppHeader />

      <div className="mx-auto max-w-7xl w-full p-6 space-y-6 flex-1">

        {error && (
          <div className="rounded-2xl border border-red-900/50 bg-red-950/40 px-4 py-3 text-sm text-red-300">
            Nem sikerült betölteni a töltők adatait. Kérjük próbálja újra.
          </div>
        )}

        <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
          {/* TÉRKÉP */}
          <div className="xl:col-span-2 bg-slate-900 rounded-2xl shadow overflow-hidden flex flex-col border border-slate-800">
            <div className="px-5 py-4 border-b border-slate-800 flex items-center justify-between">
              <div>
                <div className="font-semibold text-slate-100">Töltőállomások térképe</div>
                <div className="text-xs text-slate-400 mt-0.5">
                  {filtered.length === 0
                    ? "Nincs találat"
                    : `${filtered.length} állomás`}
                </div>
              </div>
              {loading && (
                <div className="flex gap-1">
                  {[0, 1, 2].map((i) => (
                    <div key={i} className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-bounce"
                      style={{ animationDelay: `${i * 0.15}s` }} />
                  ))}
                </div>
              )}
            </div>

            <div className="w-full h-[60vh] md:h-[70vh] lg:h-[75vh] xl:h-[80vh] 2xl:h-[85vh]">
              <MapView
                points={filtered}
                onSelect={setSelectedId}
                onStartFlow={(id) => { setSelectedId(id); setAutoOpenModal(true); }}
              />
            </div>
          </div>

          {/* JOBB OSZLOP */}
          <div className="space-y-5">
            {/* TÖLTŐK LISTÁJA */}
            <div className="bg-slate-900 rounded-2xl shadow border border-slate-800">
              <div className="px-5 py-4 border-b border-slate-800">
                <div className="font-semibold text-slate-100">Töltőállomások</div>
                <div className="text-xs text-slate-400 mt-0.5">Keresés és szűrés</div>
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

            {/* KIVÁLASZTOTT */}
            <div className="bg-slate-900 rounded-2xl shadow border border-slate-800">
              <div className="px-5 py-4 border-b border-slate-800">
                <div className="font-semibold text-slate-100">Töltés indítása</div>
                <div className="text-xs text-slate-400 mt-0.5">
                  Válasszon töltőt, majd fizessen kártyával
                </div>
              </div>

              <div className="p-5">
                <SelectedChargerCard
                  cp={selected}
                  autoOpenModal={autoOpenModal}
                  onAutoOpenDone={() => setAutoOpenModal(false)}
                  onModalChange={(open) => { modalOpenRef.current = open; }}
                />
              </div>
            </div>

            <div className="text-xs text-slate-600 text-center pb-2">
              © {new Date().getFullYear()} Energiafelhő Kft.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
