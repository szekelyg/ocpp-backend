import { Link } from "react-router-dom";
import CloudLogo from "./CloudLogo";
import useAuth from "../../hooks/useAuth";

function AccountArea() {
  const { me, loggedIn, logout } = useAuth();
  if (!loggedIn) {
    return (
      <Link to="/toltesek" className="btn btnGhost !py-1.5 !px-3 !text-xs">
        Belépés / Töltéseim
      </Link>
    );
  }
  return (
    <div className="flex items-center gap-2">
      <Link to="/toltesek" className="btn btnGhost !py-1.5 !px-3 !text-xs max-w-[200px]">
        <span className="truncate">{me?.email}</span>
      </Link>
      <button
        type="button"
        onClick={() => logout({ redirectTo: "/" })}
        className="text-xs text-ink-muted hover:text-brand-action transition"
        title="Kijelentkezés"
      >
        Kilépés
      </button>
    </div>
  );
}

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
        <div className="flex items-center gap-4">
          <span className="text-xs text-ink-muted hidden md:block">EV töltőhálózat</span>
          <AccountArea />
        </div>
      </div>
      <div className="accentLine" />
    </header>
  );
}
