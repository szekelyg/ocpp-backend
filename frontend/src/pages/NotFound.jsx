import AppHeader from "../components/ui/AppHeader";
import AppFooter from "../components/ui/AppFooter";

export default function NotFound() {
  return (
    <div className="min-h-screen flex flex-col">
      <AppHeader />
      <div className="flex-1 flex items-center justify-center p-6">
        <div className="max-w-md w-full card cardBody text-center space-y-4">
          <div className="text-3xl">🔌</div>
          <div className="text-lg font-semibold text-ink">404 – Nincs ilyen oldal</div>
          <p className="text-ink-soft text-sm">A kért oldal nem található.</p>
          <a href="/" className="btn btnPrimary inline-flex">← Vissza a főoldalra</a>
        </div>
      </div>
      <AppFooter />
    </div>
  );
}
