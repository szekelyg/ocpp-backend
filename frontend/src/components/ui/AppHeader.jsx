import CloudLogo from "./CloudLogo";

export default function AppHeader() {
  return (
    <header className="sticky top-0 z-50 bg-white/95 backdrop-blur shadow-[0_1px_0_#e2e8f6]">
      <div className="mx-auto max-w-7xl px-6 py-3 flex items-center justify-between">
        <a href="/" className="flex items-center gap-3 group">
          <CloudLogo size={30} />
          <span className="flex flex-col leading-tight">
            <span className="font-extrabold text-ink tracking-tight text-lg">
              Energiafelhő
            </span>
            <span className="text-[9px] font-bold uppercase tracking-[0.22em] text-ink-muted">
              Elektromos töltőhálózat
            </span>
          </span>
        </a>
        <span className="text-xs text-ink-muted hidden sm:block">EV töltőhálózat</span>
      </div>
      <div className="accentLine" />
    </header>
  );
}
