import { useMemo } from "react";

const STATUS_LABELS = {
  all: "Minden státusz",
  available: "Szabad",
  charging: "Tölt",
  preparing: "Csatlakoztatva",
  finishing: "Csatlakoztatva",
  unavailable: "Nem elérhető",
  faulted: "Hibás",
  offline: "Offline",
};

export default function ChargerToolbar({
  items,
  query,
  setQuery,
  statusFilter,
  setStatusFilter,
  onReset,
}) {
  const statuses = useMemo(() => {
    const set = new Set(
      (items || []).map((x) => (x.status || "").toLowerCase()).filter(Boolean)
    );
    return ["all", ...Array.from(set)];
  }, [items]);

  const hasFilter = query || statusFilter !== "all";

  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Keresés helyszín, cím alapján…"
          className="field flex-1"
        />
        {hasFilter && (
          <button type="button" onClick={onReset} className="btn btnGhost shrink-0">
            Törlés
          </button>
        )}
      </div>

      <select
        value={statusFilter}
        onChange={(e) => setStatusFilter(e.target.value)}
        className="field"
      >
        {statuses.map((s) => (
          <option key={s} value={s}>
            {STATUS_LABELS[s] || s}
          </option>
        ))}
      </select>
    </div>
  );
}
