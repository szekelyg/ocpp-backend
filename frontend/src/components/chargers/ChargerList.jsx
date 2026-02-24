import { useMemo } from "react";
import ChargerListItem from "./ChargerListItem";

export default function ChargerList({ items, selectedId, onSelect }) {
  // később ide jöhet search + filter, most csak a lista
  const list = useMemo(() => items || [], [items]);

  return (
    <div className="list">
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