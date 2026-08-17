import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import AppHeader from "../components/ui/AppHeader";
import AppFooter from "../components/ui/AppFooter";
import MapView from "../components/map/MapView";
import ChargerList from "../components/chargers/ChargerList";
import ChargerToolbar from "../components/chargers/ChargerToolbar";
import FaqSection from "../components/ui/FaqSection";

const STEPS = [
  ["stepDot1", "Válasszon töltőt", "vagy olvassa be a QR-kódot az állomáson"],
  ["stepDot2", "Indítsa el a töltést online", "bankkártyás fizetéssel, regisztráció nélkül"],
  ["stepDot3", "Csatlakoztassa az autót", "a töltés automatikusan elindul"],
];

const REFRESH_MS = 5000;

export default function Home() {
  const [searchParams] = useSearchParams();
  const cpParam = searchParams.get("cp");

  const [items, setItems] = useState([]);
  const [selectedId, setSelectedId] = useState(null); // térkép highlight
  const [expandedId, setExpandedId] = useState(null); // lista expand (toggle)
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
    return filtered.find((x) => x.id === expandedId) || null;
  }, [filtered, expandedId]);

  // Egységes ár-információ a kiemelt ár-kártyához
  const priceInfo = useMemo(() => {
    const prices = [...new Set((items || []).filter((x) => x.price_huf_per_kwh > 0).map((x) => x.price_huf_per_kwh))];
    const mins = [...new Set((items || []).filter((x) => x.min_charge_huf > 0).map((x) => x.min_charge_huf))];
    if (!prices.length) return null;
    return {
      uniform: prices.length === 1,
      price: Math.min(...prices),
      minCharge: mins.length === 1 ? mins[0] : null,
    };
  }, [items]);

  // Ha a kiválasztott töltő kiszűrődik, töröljük az expandot
  useEffect(() => {
    if (expandedId != null && !filtered.some((x) => x.id === expandedId)) {
      setExpandedId(null);
    }
    if (selectedId != null && !filtered.some((x) => x.id === selectedId)) {
      setSelectedId(null);
    }
  }, [filtered, expandedId, selectedId]);

  // ?cp=<id> – töltő előválasztás és modal auto-nyitás (csak startolható státusznál)
  useEffect(() => {
    if (!cpParam || !items.length || autoOpenDoneRef.current) return;
    const cpId = parseInt(cpParam, 10);
    const match = items.find((x) => x.id === cpId);
    if (!match) return;
    autoOpenDoneRef.current = true;
    setSelectedId(match.id);
    setExpandedId(match.id);
    const startable = new Set(["available", "preparing", "finishing"]);
    if (startable.has(String(match.status || "").toLowerCase())) {
      setAutoOpenModal(true);
    }
  }, [cpParam, items]);

  const handleToggle = useCallback((id) => {
    setSelectedId(id);
    setExpandedId((prev) => (prev === id ? null : id));
  }, []);

  const handleMapSelect = useCallback((id) => {
    setSelectedId(id);
    setExpandedId(id);
  }, []);

  const resetFilters = useCallback(() => {
    setQuery("");
    setStatusFilter("all");
  }, []);

  return (
    <div className="min-h-screen flex flex-col">
      <AppHeader />

      <div className="mx-auto max-w-7xl w-full p-6 space-y-6 flex-1">

        {/* HERO */}
        <div className="card">
          <div className="cardBody md:flex md:items-center md:justify-between gap-8">
            <div className="max-w-xl">
              <h1 className="text-2xl md:text-3xl font-extrabold tracking-tight text-ink leading-tight">
                Töltse autóját{" "}
                <span className="text-brand-action">regisztráció nélkül</span>
              </h1>
              <p className="mt-2 text-sm md:text-base text-ink-soft">
                Olvassa be a QR-kódot az állomáson vagy válasszon töltőt a térképről —
                bankkártyás fizetés után azonnal indul a töltés. Nincs applikáció,
                nincs előzetes regisztráció.
              </p>
            </div>
            <div className="mt-5 md:mt-0 flex flex-col gap-3 shrink-0">
              {STEPS.map(([dot, title, sub], i) => (
                <div key={i} className="flex items-center gap-3">
                  <span className={`stepDot ${dot}`}>{i + 1}</span>
                  <span className="leading-tight">
                    <span className="block text-sm font-semibold text-ink">{title}</span>
                    <span className="block text-xs text-ink-muted">{sub}</span>
                  </span>
                </div>
              ))}
            </div>
          </div>
          <div className="accentLine" />
        </div>

        {error && (
          <div className="errorBanner">
            Nem sikerült betölteni a töltők adatait. Kérjük próbálja újra.
          </div>
        )}

        <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
          {/* TÉRKÉP */}
          <div className="xl:col-span-2 card flex flex-col">
            <div className="cardHeader flex items-center justify-between">
              <div>
                <div className="cardTitle">Töltőállomások térképe</div>
                <div className="cardSub mt-0.5">
                  {filtered.length === 0
                    ? "Nincs találat"
                    : `${filtered.length} állomás`}
                </div>
              </div>
              {loading && (
                <div className="flex gap-1">
                  {["bg-brand-yellow", "bg-brand-blue", "bg-brand-green"].map((c, i) => (
                    <div key={i} className={`w-1.5 h-1.5 rounded-full animate-bounce ${c}`}
                      style={{ animationDelay: `${i * 0.15}s` }} />
                  ))}
                </div>
              )}
            </div>

            <div className="w-full flex-1 min-h-[50vh]">
              <MapView
                points={filtered}
                selectedId={selectedId}
                onSelect={handleMapSelect}
                onStartFlow={(id) => { handleMapSelect(id); setAutoOpenModal(true); }}
              />
            </div>
          </div>

          {/* JOBB OSZLOP */}
          <div className="space-y-5">
            {/* ÁR-KÁRTYA */}
            {priceInfo && (
              <div className="card">
                <div className="cardBody flex items-start justify-between gap-3">
                  <div>
                    <div className="kicker">Töltési díj</div>
                    <div className="mt-1 text-3xl font-extrabold text-ink">
                      {priceInfo.price.toLocaleString("hu-HU")} Ft
                      <span className="text-base font-semibold text-ink-muted">/kWh</span>
                      {!priceInfo.uniform && (
                        <span className="text-base font-semibold text-ink-muted">-tól</span>
                      )}
                    </div>
                    <div className="mt-0.5 text-xs text-ink-muted">
                      bruttó, 27% ÁFÁ-val{priceInfo.uniform ? " · minden állomáson" : " · állomásonként eltérhet"}
                    </div>
                  </div>
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[#e6faf4] text-lg">
                    ⚡
                  </span>
                </div>
                <div className="px-5 pb-4 text-xs text-ink-soft">
                  Fizetéskor csak zárolás történik a kártyán — a töltés végén kizárólag a
                  felhasznált energia díját vonjuk le, a számlát emailben küldjük.
                  {priceInfo.minCharge && (
                    <> A bankkártyás feldolgozás minimuma {priceInfo.minCharge.toLocaleString("hu-HU")} Ft.</>
                  )}
                </div>
              </div>
            )}

            {/* TÖLTŐK LISTÁJA */}
            <div className="card">
              <div className="cardHeader">
                <div className="cardTitle">Töltőállomások</div>
                <div className="cardSub mt-0.5">Keresés és szűrés</div>
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
                  selectedId={expandedId}
                  onToggle={handleToggle}
                  selectedCp={selected}
                  autoOpenModal={autoOpenModal}
                  onAutoOpenDone={() => setAutoOpenModal(false)}
                  onModalChange={(open) => { modalOpenRef.current = open; }}
                />
              </div>
            </div>

          </div>
        </div>

        {/* GYIK */}
        <FaqSection />
      </div>

      <AppFooter />
    </div>
  );
}
