import CloudLogo from "./CloudLogo";

export default function AppHeader() {
  // z-[1100]: a Leaflet paneljei 400-on, a térkép-vezérlői 1000-en ülnek, ezért egy
  // z-50-es sticky fejléc alá csúszna a térkép – görgetéskor a csempék kitakarnák a
  // fejlécet. A PayModal (z-[10000]) így is a fejléc fölött marad.
  return (
    <header className="sticky top-0 z-[1100] bg-white/95 backdrop-blur shadow-[0_1px_0_#e2e8f6]">
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
