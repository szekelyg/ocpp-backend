import { useMemo } from "react";
import ChargerListItem from "./ChargerListItem";
import SelectedChargerCard from "./SelectedChargerCard";

const STATUS_PRIORITY = {
  available: 0,
  preparing: 1,
  finishing: 1,
  charging: 2,
};

function statusPriority(status) {
  const s = String(status || "").toLowerCase();
  return s in STATUS_PRIORITY ? STATUS_PRIORITY[s] : 3; // offline/hiba/ismeretlen → legvégére
}

export default function ChargerList({ items, selectedId, onSelect, onToggle, selectedCp, autoOpenModal, onAutoOpenDone, onModalChange }) {
  const list = useMemo(
    () => [...(items || [])].sort((a, b) => statusPriority(a.status) - statusPriority(b.status)),
    [items]
  );

  if (!list.length) {
    return (
      <div className="rounded-xl border border-slate-200 bg-slate-50 p-6 text-center text-sm text-slate-500">
        Nincs találat.
      </div>
    );
  }

  return (
    <div className="flex max-h-[70vh] flex-col gap-2 overflow-y-auto pr-1">
      {list.map((cp) => (
        <div key={cp.id} className="flex flex-col gap-2">
          <ChargerListItem
            cp={cp}
            selected={cp.id === selectedId}
            onClick={() => onToggle(cp.id)}
          />
          {cp.id === selectedId && selectedCp && (
            <div className="rounded-xl border border-blue-500/20 bg-slate-800/50 px-4 pt-4 pb-3">
              <SelectedChargerCard
                cp={selectedCp}
                autoOpenModal={autoOpenModal}
                onAutoOpenDone={onAutoOpenDone}
                onModalChange={onModalChange}
                compact
              />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
