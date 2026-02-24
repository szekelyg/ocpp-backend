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
    <div className="app">
      <div className="header">
        <div className="brand">
          <h1>EV Charging</h1>
          <p>Térkép • Töltők • Fizetés + indítás</p>
        </div>

        <div className="pills">
          <div className="pill">
            Utolsó frissítés:{" "}
            {lastUpdated ? lastUpdated.toLocaleString("hu-HU") : "—"}
          </div>
          <button className="btn" onClick={refresh}>
            Frissítés
          </button>
        </div>
      </div>

      <hr className="sep" />

      <div className="grid">
        <div className="card">
          <div className="cardHeader">
            <div>
              <div className="cardTitle">Térkép</div>
              <div className="cardSub">Töltők: {filtered.length}</div>
            </div>
          </div>
          <div className="cardBody">
            <div className="mapWrap">
              <MapView points={filtered} onSelect={setSelectedId} />
            </div>
          </div>
        </div>

        <div className="rightCol">
          <div className="card">
            <div className="cardHeader">
              <div>
                <div className="cardTitle">Töltők</div>
                <div className="cardSub">Keresés + szűrés</div>
              </div>
            </div>
            <div className="cardBody">
              <ChargerToolbar
                items={items}
                query={query}
                setQuery={setQuery}
                statusFilter={statusFilter}
                setStatusFilter={setStatusFilter}
                onReset={resetFilters}
              />

              <div style={{ height: 10 }} />

              <ChargerList
                items={filtered}
                selectedId={selectedId}
                onSelect={setSelectedId}
              />
            </div>
          </div>

          <div className="card">
            <div className="cardHeader">
              <div>
                <div className="cardTitle">Kiválasztott töltő</div>
                <div className="cardSub">Fizetés + indítás</div>
              </div>
            </div>
            <div className="cardBody">
              <SelectedChargerCard cp={selected} />
            </div>
          </div>

          <div className="smallFooter">
            MVP • moduláris frontend • production-ready alap
          </div>
        </div>
      </div>
    </div>
  );
}