export default function AppHeader() {
  return (
    <header className="sticky top-0 z-50 border-b border-slate-800 bg-slate-950/90 backdrop-blur">
      <div className="mx-auto max-w-7xl px-6 py-3 flex items-center justify-between">
        <a href="/" className="flex items-center gap-2.5 group">
          <span className="text-blue-400 text-xl leading-none">⚡</span>
          <span className="font-bold text-slate-100 tracking-tight text-base">
            Energiafelhő
          </span>
          <span className="text-slate-600 text-xs font-normal hidden sm:block">Kft.</span>
        </a>
        <span className="text-xs text-slate-500 hidden sm:block">EV töltőhálózat</span>
      </div>
    </header>
  );
}
