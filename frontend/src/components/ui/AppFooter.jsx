import CloudLogo from "./CloudLogo";

export default function AppFooter() {
  return (
    <footer className="mt-auto bg-brand-panel border-t border-brand-line">
      <div className="mx-auto max-w-7xl px-6 py-8 grid gap-8 sm:grid-cols-3">
        <div>
          <div className="flex items-center gap-2.5">
            <CloudLogo size={24} />
            <span className="font-extrabold text-ink tracking-tight">Energiafelhő</span>
          </div>
          <p className="mt-2 text-xs text-ink-muted leading-relaxed">
            Elektromos töltőhálózat — regisztráció nélküli, bankkártyás töltés.
          </p>
        </div>

        <div>
          <div className="kicker mb-2">Üzemeltető</div>
          <p className="text-xs text-ink-soft leading-relaxed">
            Energiafelhő Kft.
            <br />
            Nyilvántartási szám: 223/2026
          </p>
          <nav className="mt-2 flex flex-col gap-1 text-xs font-medium">
            <a href="/aszf" className="text-ink-soft hover:text-brand-action transition">
              Általános Szerződési Feltételek
            </a>
            <a href="/adatkezeles" className="text-ink-soft hover:text-brand-action transition">
              Adatkezelési tájékoztató
            </a>
          </nav>
        </div>

        <div>
          <div className="kicker mb-2">Segítség</div>
          <div className="flex flex-col gap-1 text-xs font-medium">
            <a href="tel:+3613009045" className="text-ink-soft hover:text-brand-action transition">
              📞 +36 1 300 9045
            </a>
            <a
              href="mailto:szerviz@energiafelho.hu"
              className="text-ink-soft hover:text-brand-action transition"
            >
              ✉️ szerviz@energiafelho.hu
            </a>
          </div>
          <p className="mt-2 text-xs text-ink-muted leading-relaxed">
            Hibabejelentés és ügyfélszolgálat a töltéssel kapcsolatos kérdésekben.
          </p>
        </div>
      </div>

      <div className="border-t border-brand-line">
        <div className="mx-auto max-w-7xl px-6 py-4 text-xs text-ink-muted">
          © {new Date().getFullYear()} Energiafelhő Kft. Minden jog fenntartva.
        </div>
      </div>
    </footer>
  );
}
