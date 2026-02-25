import { useMemo } from "react";
import ChargerListItem from "./ChargerListItem";

export default function ChargerList({ items, selectedId, onSelect }) {
  const list = useMemo(() => items || [], [items]);

  if (!list.length) {
    return (
      <div className="rounded-xl border border-slate-200 bg-slate-50 p-6 text-center text-sm text-slate-500">
        Nincs találat.
      </div>
    );
  }

  return (
    <div className="flex max-h-[420px] flex-col gap-2 overflow-y-auto pr-1">
      {list.map((cp) => (
        <ChargerListItem
          key={cp.id}
          cp={cp}
          selected={cp.id === selectedId}
          onClick={() => onSelect(cp.id)}
        />
      ))}
    </div>
  );
}