import { useEffect, useState, useCallback } from "react";
import { api } from "./api";

const STATUS_COLORS = {
  active: "bg-green-500/20 text-green-400 border-green-700",
  finished: "bg-slate-600/20 text-slate-400 border-slate-600",
  timed_out: "bg-red-500/20 text-red-400 border-red-700",
};

function duration(s) {
  if (!s) return "—";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}ó ${m}p`;
  if (m > 0) return `${m}p ${sec}mp`;
  return `${sec}mp`;
}

function formatDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("hu-HU", {
    month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

// Remote start modal
function RemoteStartModal({ chargePoints, onClose, onSuccess }) {
  const [cpId, setCpId] = useState("");
  const [connector, setConnector] = useState("1");
  const [tag, setTag] = useState("ADMIN");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleStart() {
    if (!cpId) return;
    setLoading(true);
    setError("");
    try {
      await api.remoteStart(Number(cpId), Number(connector), tag);
      onSuccess();
      onClose();
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 px-4">
      <div className="bg-slate-800 rounded-2xl p-6 w-full max-w-sm border border-slate-700 shadow-2xl">
        <h2 className="text-lg font-bold text-white mb-4">Töltés indítása (Admin)</h2>

        {error && (
          <div className="bg-red-900/40 border border-red-700 text-red-300 rounded-lg px-3 py-2 text-sm mb-3">
            {error}
          </div>
        )}

        <div className="space-y-3">
          <div>
            <label className="block text-xs text-slate-400 mb-1">Töltő</label>
            <select
              value={cpId}
              onChange={(e) => setCpId(e.target.value)}
              className="w-full bg-slate-700 text-white rounded-lg px-3 py-2 text-sm border border-slate-600 focus:outline-none focus:border-blue-500"
            >
              <option value="">Válassz töltőt...</option>
              {chargePoints.map((cp) => (
                <option key={cp.id} value={cp.id}>
                  {cp.ocpp_id} ({cp.status})
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs text-slate-400 mb-1">Csatlakozó (connector_id)</label>
            <input
              type="number"
              min="0"
              value={connector}
              onChange={(e) => setConnector(e.target.value)}
              className="w-full bg-slate-700 text-white rounded-lg px-3 py-2 text-sm border border-slate-600 focus:outline-none focus:border-blue-500"
            />
          </div>

          <div>
            <label className="block text-xs text-slate-400 mb-1">ID tag</label>
            <input
              type="text"
              value={tag}
              onChange={(e) => setTag(e.target.value)}
              className="w-full bg-slate-700 text-white rounded-lg px-3 py-2 text-sm border border-slate-600 focus:outline-none focus:border-blue-500"
            />
          </div>
        </div>

        <div className="flex gap-2 mt-5">
          <button
            onClick={onClose}
            className="flex-1 bg-slate-700 hover:bg-slate-600 text-white text-sm font-medium py-2 rounded-lg transition-colors"
          >
            Mégse
          </button>
          <button
            onClick={handleStart}
            disabled={!cpId || loading}
            className="flex-1 bg-green-600 hover:bg-green-500 disabled:opacity-50 text-white text-sm font-medium py-2 rounded-lg transition-colors"
          >
            {loading ? "Indítás..." : "Indítás"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function AdminSessions() {
  const [data, setData] = useState({ sessions: [], total: 0 });
  const [cps, setCps] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [activeOnly, setActiveOnly] = useState(false);
  const [emailFilter, setEmailFilter] = useState("");
  const [page, setPage] = useState(0);
  const [showStartModal, setShowStartModal] = useState(false);
  const [stoppingId, setStoppingId] = useState(null);

  const PAGE_SIZE = 50;

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [sessData, cpData] = await Promise.all([
        api.sessions({
          limit: PAGE_SIZE,
          offset: page * PAGE_SIZE,
          active_only: activeOnly,
          email: emailFilter || undefined,
        }),
        api.chargePoints(),
      ]);
      setData(sessData);
      setCps(cpData);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [page, activeOnly, emailFilter]);

  useEffect(() => { load(); }, [load]);

  async function handleStop(sessionId) {
    if (!confirm("Biztosan leállítod ezt a töltést?")) return;
    setStoppingId(sessionId);
    try {
      await api.stopSession(sessionId);
      load();
    } catch (e) {
      alert("Hiba: " + e.message);
    } finally {
      setStoppingId(null);
    }
  }

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">Tranzakciók</h1>
          <p className="text-slate-400 text-sm mt-1">{data.total} összesen</p>
        </div>
        <button
          onClick={() => setShowStartModal(true)}
          className="bg-green-600 hover:bg-green-500 text-white text-sm font-semibold px-4 py-2 rounded-lg transition-colors flex items-center gap-2"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          Töltés indítása
        </button>
      </div>

      {/* Filters */}
      <div className="flex gap-3 mb-4 flex-wrap">
        <label className="flex items-center gap-2 text-sm text-slate-300 cursor-pointer">
          <input
            type="checkbox"
            checked={activeOnly}
            onChange={(e) => { setActiveOnly(e.target.checked); setPage(0); }}
            className="accent-blue-500"
          />
          Csak aktív
        </label>
        <input
          type="text"
          placeholder="Email szűrő..."
          value={emailFilter}
          onChange={(e) => { setEmailFilter(e.target.value); setPage(0); }}
          className="bg-slate-700 text-white text-sm rounded-lg px-3 py-1.5 border border-slate-600 focus:outline-none focus:border-blue-500 w-52"
        />
        <button
          onClick={() => load()}
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
                    <th className="text-left px-4 py-3">Kezdés</th>
                    <th className="text-left px-4 py-3">Időtartam</th>
                    <th className="text-left px-4 py-3">Energia</th>
                    <th className="text-left px-4 py-3">Összeg</th>
                    <th className="text-left px-4 py-3">Státusz</th>
                    <th className="text-right px-4 py-3">Műveletek</th>
                  </tr>
                </thead>
                <tbody>
                  {data.sessions.length === 0 && (
                    <tr>
                      <td colSpan={9} className="text-center text-slate-500 py-8">
                        Nincs találat
                      </td>
                    </tr>
                  )}
                  {data.sessions.map((s) => {
                    const isActive = s.is_active;
                    const isTimedOut = s.timed_out;
                    const statusKey = isActive ? "active" : isTimedOut ? "timed_out" : "finished";

                    return (
                      <tr key={s.id} className="border-b border-slate-700/50 hover:bg-slate-700/30">
                        <td className="px-4 py-3 text-slate-400 font-mono">{s.id}</td>
                        <td className="px-4 py-3 text-white font-medium">
                          {s.charge_point_ocpp_id || `CP#${s.charge_point_id}`}
                          {s.connector_id && (
                            <span className="text-slate-500 text-xs ml-1">:{s.connector_id}</span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-slate-300 truncate max-w-[150px]">
                          {s.anonymous_email || s.user_tag || "—"}
                        </td>
                        <td className="px-4 py-3 text-slate-300 whitespace-nowrap">
                          {formatDate(s.started_at)}
                        </td>
                        <td className="px-4 py-3 text-slate-300">
                          {duration(s.duration_s)}
                        </td>
                        <td className="px-4 py-3 text-slate-300">
                          {s.energy_kwh != null ? `${Number(s.energy_kwh).toFixed(2)} kWh` : "—"}
                        </td>
                        <td className="px-4 py-3 text-slate-300">
                          {s.cost_huf != null
                            ? `${Number(s.cost_huf).toLocaleString("hu-HU")} Ft`
                            : "—"}
                        </td>
                        <td className="px-4 py-3">
                          <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs border ${STATUS_COLORS[statusKey]}`}>
                            {isActive ? "Aktív" : isTimedOut ? "Időtúllépés" : "Befejezett"}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-right">
                          {isActive && s.ocpp_transaction_id && (
                            <button
                              onClick={() => handleStop(s.id)}
                              disabled={stoppingId === s.id}
                              className="bg-red-700 hover:bg-red-600 disabled:opacity-50 text-white text-xs px-3 py-1 rounded-lg transition-colors"
                            >
                              {stoppingId === s.id ? "..." : "Leállít"}
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* Pagination */}
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

      {showStartModal && (
        <RemoteStartModal
          chargePoints={cps}
          onClose={() => setShowStartModal(false)}
          onSuccess={load}
        />
      )}
    </div>
  );
}
