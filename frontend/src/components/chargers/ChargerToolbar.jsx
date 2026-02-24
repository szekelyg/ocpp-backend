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
      items.map((x) => (x.status || "").toLowerCase()).filter(Boolean)
    );
    return ["all", ...Array.from(set)];
  }, [items]);

  return (
    <>
      <div className="toolbar">
        <input
          className="input"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Keresés: ID / hely / cím…"
        />
        <button className="btn" onClick={onReset}>
          Reset
        </button>
      </div>

      <select
        className="select"
        value={statusFilter}
        onChange={(e) => setStatusFilter(e.target.value)}
      >
        {statuses.map((s) => (
          <option key={s} value={s}>
            {s === "all" ? "Minden státusz" : s}
          </option>
        ))}
      </select>
    </>
  );
}