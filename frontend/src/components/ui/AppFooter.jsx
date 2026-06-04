export default function AppFooter() {
  return (
    <footer className="border-t border-slate-800/60 mt-auto">
      <div className="mx-auto max-w-7xl px-6 py-5 flex flex-col sm:flex-row items-center justify-between gap-2 text-xs text-slate-500">
        <span>© {new Date().getFullYear()} Energiafelhő Kft.</span>
        <nav className="flex items-center gap-4">
          <a href="/aszf" className="hover:text-slate-300 transition">
            ÁSZF
          </a>
          <a href="/adatkezeles" className="hover:text-slate-300 transition">
            Adatkezelés
          </a>
          <a
            href="mailto:szerviz@energiafelho.hu"
            className="hover:text-slate-300 transition"
          >
            Kapcsolat
          </a>
        </nav>
      </div>
    </footer>
  );
}
