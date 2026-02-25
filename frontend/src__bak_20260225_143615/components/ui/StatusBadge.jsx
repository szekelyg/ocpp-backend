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

const toneClass = {
  good: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  ok: "bg-sky-50 text-sky-700 ring-sky-200",
  warn: "bg-amber-50 text-amber-800 ring-amber-200",
  bad: "bg-rose-50 text-rose-700 ring-rose-200",
  muted: "bg-slate-50 text-slate-600 ring-slate-200",
};

export default function StatusBadge({ status }) {
  const ui = statusUi(status);

  return (
    <span
      className={[
        "inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset",
        toneClass[ui.tone] || toneClass.muted,
      ].join(" ")}
      title={String(status || "")}
    >
      {ui.label}
    </span>
  );
}