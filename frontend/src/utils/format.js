export function formatHu(dtIso) {
    if (!dtIso) return "—";
    const d = new Date(dtIso);
    if (Number.isNaN(d.getTime())) return "—";
    return d.toLocaleString("hu-HU");
  }
  
  export function norm(s) {
    return (s || "").trim().replace(/\s+/g, " ").toLowerCase();
  }
  
  export function placeLines(cp) {
    const a = (cp?.location_name || "").trim();
    const b = (cp?.address_text || "").trim();
    if (!a && !b) return ["—"];
    if (a && !b) return [a];
    if (!a && b) return [b];
    if (norm(a) === norm(b)) return [a];
    return [a, b];
  }