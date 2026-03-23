import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "./api";

function StatCard({ label, value, sub, color = "blue" }) {
  const colors = {
    blue: "bg-blue-600",
    green: "bg-green-600",
    amber: "bg-amber-500",
    purple: "bg-purple-600",
  };
  return (
    <div className="bg-slate-800 rounded-xl p-5 border border-slate-700">
      <div className={`inline-flex w-10 h-10 ${colors[color]} rounded-lg items-center justify-center mb-3`}>
        <div className="w-4 h-4 bg-white/30 rounded-sm" />
      </div>
      <div className="text-2xl font-bold text-white">{value ?? "—"}</div>
      <div className="text-sm text-slate-400 mt-0.5">{label}</div>
      {sub && <div className="text-xs text-slate-500 mt-1">{sub}</div>}
    </div>
  );
}

export default function AdminDashboard() {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const navigate = useNavigate();

  useEffect(() => {
    api.stats()
      .then(setStats)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  function fmt(n, decimals = 0) {
    if (n == null) return "—";
    return Number(n).toLocaleString("hu-HU", {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    });
  }

  return (
    <div className="p-6">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white">Dashboard</h1>
        <p className="text-slate-400 text-sm mt-1">Töltőhálózat áttekintő</p>
      </div>

      {loading && (
        <div className="text-slate-400 text-sm">Betöltés...</div>
      )}
      {error && (
        <div className="bg-red-900/40 border border-red-700 text-red-300 rounded-lg px-4 py-3 text-sm mb-4">
          {error}
        </div>
      )}

      {stats && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
            <StatCard
              label="Összes tranzakció"
              value={fmt(stats.total_sessions)}
              sub={`${fmt(stats.sessions_today)} ma`}
              color="blue"
            />
            <StatCard
              label="Aktív töltések"
              value={fmt(stats.active_sessions)}
              color="green"
            />
            <StatCard
              label="Összes energia"
              value={`${fmt(stats.total_energy_kwh, 1)} kWh`}
              color="amber"
            />
            <StatCard
              label="Összes bevétel"
              value={`${fmt(stats.total_revenue_huf)} Ft`}
              sub={`${fmt(stats.revenue_today_huf)} Ft ma`}
              color="purple"
            />
          </div>

          <div className="grid grid-cols-2 gap-4 mb-8 max-w-md">
            <div className="bg-slate-800 rounded-xl p-5 border border-slate-700 text-center">
              <div className="text-3xl font-bold text-white">{fmt(stats.total_charge_points)}</div>
              <div className="text-sm text-slate-400 mt-1">Töltő összesen</div>
            </div>
            <div className="bg-slate-800 rounded-xl p-5 border border-slate-700 text-center">
              <div className="text-3xl font-bold text-green-400">{fmt(stats.online_charge_points)}</div>
              <div className="text-sm text-slate-400 mt-1">Online (utolsó 5 perc)</div>
            </div>
          </div>

          <div className="flex gap-3">
            <button
              onClick={() => navigate("/admin/sessions")}
              className="bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium
                         px-4 py-2 rounded-lg transition-colors"
            >
              Tranzakciók megtekintése
            </button>
            <button
              onClick={() => navigate("/admin/charge-points")}
              className="bg-slate-700 hover:bg-slate-600 text-white text-sm font-medium
                         px-4 py-2 rounded-lg transition-colors"
            >
              Töltők kezelése
            </button>
          </div>
        </>
      )}
    </div>
  );
}
