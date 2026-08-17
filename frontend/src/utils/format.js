export function formatHu(dtIso) {
    if (!dtIso) return "—";
    const d = new Date(dtIso);
    if (Number.isNaN(d.getTime())) return "—";
    return d.toLocaleString("hu-HU");
  }

export function timeAgo(dtIso) {
  if (!dtIso) return "—";
  const d = new Date(dtIso);
  if (Number.isNaN(d.getTime())) return "—";
  const diff = Math.floor((Date.now() - d.getTime()) / 1000);
  if (diff < 60) return "most";
  if (diff < 3600) return `${Math.floor(diff / 60)} perce`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} órája`;
  return `${Math.floor(diff / 86400)} napja`;
}
  
  export function norm(s) {
    return (s || "").trim().replace(/\s+/g, " ").toLowerCase();
  }
  
  export function placeLines(cp) {
    const name = (cp?.location_name || "").trim();
    const addr = (cp?.address_text || "").trim();
    const lines = [name, addr].filter(Boolean);
    return lines.length ? lines : ["—"];
  }