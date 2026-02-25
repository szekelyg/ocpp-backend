import { useMemo } from "react";

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

  return (
    <div className="toolbar">
      <div className="toolbarRow">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Keresés: ID / hely / cím…"
          className="field"
        />

        <button type="button" onClick={onReset} className="btn btnGhost">
          Reset
        </button>
      </div>

      <div className="toolbarLabelRow">
        <label className="toolbarLabel">Státusz</label>

        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="field sm:max-w-xs"
        >
          {statuses.map((s) => (
            <option key={s} value={s}>
              {s === "all" ? "Minden státusz" : s}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}