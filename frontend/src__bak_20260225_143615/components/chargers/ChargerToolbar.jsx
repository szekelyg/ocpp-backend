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
    <div className="space-y-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Keresés: ID / hely / cím…"
            className="w-full rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm outline-none transition focus:border-slate-300 focus:ring-4 focus:ring-slate-100"
          />
        </div>

        <button
          type="button"
          onClick={onReset}
          className="inline-flex items-center justify-center rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 transition hover:bg-slate-50 active:scale-[0.99]"
        >
          Reset
        </button>
      </div>

      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <label className="text-xs font-medium text-slate-600 sm:w-28">
          Státusz
        </label>

        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="w-full rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-800 outline-none transition focus:border-slate-300 focus:ring-4 focus:ring-slate-100 sm:max-w-xs"
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