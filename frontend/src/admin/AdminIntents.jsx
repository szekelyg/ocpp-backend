import { useEffect, useState, useCallback } from "react";
import { api } from "./api";

const STATUS_COLORS = {
  pending_payment: "text-yellow-400 border-yellow-700 bg-yellow-500/10",
  paid: "text-green-400 border-green-700 bg-green-500/10",
  expired: "text-slate-400 border-slate-600 bg-slate-500/10",
  cancelled: "text-orange-400 border-orange-700 bg-orange-500/10",
  failed: "text-red-400 border-red-700 bg-red-500/10",
};

const STATUS_LABELS = {
  pending_payment: "Fizetésre vár",
  paid: "Fizetve",
  expired: "Lejárt",
  cancelled: "Visszavont",
  failed: "Sikertelen",
};

function formatDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("hu-HU", {
    month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

export default function AdminIntents() {
  const [data, setData] = useState({ intents: [], total: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [page, setPage] = useState(0);
  const PAGE_SIZE = 100;

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const d = await api.intents({
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
        status: statusFilter || undefined,
      });
      setData(d);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [page, statusFilter]);

  useEffect(() => { load(); }, [load]);

  const STATUSES = ["", "pending_payment", "paid", "expired", "cancelled", "failed"];

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">Fizetési szándékok</h1>
          <p className="text-slate-400 text-sm mt-1">{data.total} összesen</p>
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-3 mb-4">
        <select
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value); setPage(0); }}
          className="bg-slate-700 text-white text-sm rounded-lg px-3 py-1.5 border border-slate-600 focus:outline-none focus:border-blue-500"
        >
          {STATUSES.map((s) => (
            <option key={s} value={s}>{s ? STATUS_LABELS[s] || s : "Összes státusz"}</option>
          ))}
        </select>
        <button
          onClick={load}
          className="bg-slate-700 hover:bg-slate-600 text-white text-sm px-3 py-1.5 rounded-lg transition-colors"
        >
          Frissítés
        </button>
      </div>

      {error && (
        <div className="bg-red-900/40 border border-red-700 text-red-300 rounded-lg px-4 py-3 text-sm mb-4">
          {error}
        </div>
      )}

      {loading ? (
        <div className="text-slate-400 text-sm">Betöltés...</div>
      ) : (
        <>
          <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-700 text-slate-400 text-xs uppercase">
                    <th className="text-left px-4 py-3">#</th>
                    <th className="text-left px-4 py-3">Töltő</th>
                    <th className="text-left px-4 py-3">Email</th>
                    <th className="text-left px-4 py-3">Összeg</th>
                    <th className="text-left px-4 py-3">Státusz</th>
                    <th className="text-left px-4 py-3">Provider ref</th>
                    <th className="text-left px-4 py-3">Létrehozva</th>
                    <th className="text-left px-4 py-3">Lejárat</th>
                  </tr>
                </thead>
                <tbody>
                  {data.intents.length === 0 && (
                    <tr>
                      <td colSpan={8} className="text-center text-slate-500 py-8">
                        Nincs találat
                      </td>
                    </tr>
                  )}
                  {data.intents.map((intent) => {
                    const color = STATUS_COLORS[intent.status] || STATUS_COLORS.expired;
                    return (
                      <tr key={intent.id} className="border-b border-slate-700/50 hover:bg-slate-700/30">
                        <td className="px-4 py-3 text-slate-400 font-mono">{intent.id}</td>
                        <td className="px-4 py-3 text-white font-medium">
                          {intent.charge_point_ocpp_id || `CP#${intent.charge_point_id}`}
                        </td>
                        <td className="px-4 py-3 text-slate-300 truncate max-w-[160px]">
                          {intent.anonymous_email || "—"}
                        </td>
                        <td className="px-4 py-3 text-slate-300">
                          {Number(intent.hold_amount_huf).toLocaleString("hu-HU")} Ft
                        </td>
                        <td className="px-4 py-3">
                          <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs border ${color}`}>
                            {STATUS_LABELS[intent.status] || intent.status}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-slate-500 font-mono text-xs truncate max-w-[140px]">
                          {intent.payment_provider_ref || "—"}
                        </td>
                        <td className="px-4 py-3 text-slate-300 whitespace-nowrap">
                          {formatDate(intent.created_at)}
                        </td>
                        <td className="px-4 py-3 text-slate-300 whitespace-nowrap">
                          {formatDate(intent.expires_at)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {data.total > PAGE_SIZE && (
            <div className="flex items-center justify-between mt-4">
              <span className="text-slate-400 text-sm">
                {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, data.total)} / {data.total}
              </span>
              <div className="flex gap-2">
                <button
                  disabled={page === 0}
                  onClick={() => setPage((p) => p - 1)}
                  className="bg-slate-700 disabled:opacity-40 hover:bg-slate-600 text-white text-sm px-3 py-1.5 rounded-lg transition-colors"
                >
                  Előző
                </button>
                <button
                  disabled={(page + 1) * PAGE_SIZE >= data.total}
                  onClick={() => setPage((p) => p + 1)}
                  className="bg-slate-700 disabled:opacity-40 hover:bg-slate-600 text-white text-sm px-3 py-1.5 rounded-lg transition-colors"
                >
                  Következő
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
