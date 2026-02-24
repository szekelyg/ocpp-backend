function statusUi(statusRaw) {
    const s = (statusRaw || "").toString().trim().toLowerCase();
  
    const map = {
      charging: { label: "Tölt", tone: "good" },
      available: { label: "Szabad", tone: "ok" },
      preparing: { label: "Csatlakoztatva", tone: "warn" },
      finishing: { label: "Csatlakoztatva", tone: "warn" },
      suspendedev: { label: "Szünetel (EV)", tone: "warn" },
      suspendedevse: { label: "Szünetel (állomás)", tone: "warn" },
      unavailable: { label: "Nem elérhető", tone: "bad" },
      faulted: { label: "Hibás", tone: "bad" },
      reserved: { label: "Foglalt", tone: "warn" },
    };
  
    if (!s) return { label: "Ismeretlen", tone: "muted" };
    return map[s] || { label: "Ismeretlen", tone: "muted" };
  }
  
  function badgeClass(tone) {
    switch (tone) {
      case "good":
        return "badge badgeGood";
      case "warn":
        return "badge badgeWarn";
      case "bad":
        return "badge badgeBad";
      case "ok":
        return "badge badgeOk";
      default:
        return "badge badgeMuted";
    }
  }
  
  export default function StatusBadge({ status }) {
    const ui = statusUi(status);
    return <span className={badgeClass(ui.tone)}>{ui.label}</span>;
  }