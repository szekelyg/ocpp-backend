import { useMemo } from "react";
import AppHeader from "../components/ui/AppHeader";

export default function PayCancel() {
  const params = useMemo(() => new URLSearchParams(window.location.search), []);
  const intentId = params.get("intent_id");

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
      <AppHeader />

      <div className="flex-1 flex items-center justify-center p-6">
        <div className="max-w-md w-full space-y-6">
          <div className="card cardBody text-center space-y-4">
            <div className="w-14 h-14 rounded-full bg-slate-800 border border-slate-700 flex items-center justify-center mx-auto text-2xl">
              ✕
            </div>

            <div>
              <div className="text-xl font-semibold text-slate-100">Fizetés megszakítva</div>
              <p className="text-slate-400 text-sm mt-2">
                A fizetési folyamat megszakadt vagy lejárt az időkorlát.
                Nem történt terhelés a kártyáján.
              </p>
            </div>

            <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-3 text-xs text-slate-400 text-left">
              Ha a fizetés tévesen szakadt meg, kérjük próbálja újra, vagy vegye
              fel a kapcsolatot ügyfélszolgálatunkkal a
              <a href="mailto:szerviz@energiafelho.hu" className="text-blue-400 ml-1">
                szerviz@energiafelho.hu
              </a> címen.
            </div>

            <a href="/" className="btn btnPrimary w-full">
              Vissza a töltőkhöz
            </a>
          </div>

          <div className="text-xs text-slate-600 text-center">
            © {new Date().getFullYear()} Energiafelhő Kft.
          </div>
        </div>
      </div>
    </div>
  );
}
