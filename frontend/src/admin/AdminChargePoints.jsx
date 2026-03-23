import { useEffect, useState, useCallback } from "react";
import { api } from "./api";

const STATUS_COLORS = {
  available: "text-green-400 border-green-700 bg-green-500/10",
  charging: "text-blue-400 border-blue-700 bg-blue-500/10",
  preparing: "text-yellow-400 border-yellow-700 bg-yellow-500/10",
  finishing: "text-orange-400 border-orange-700 bg-orange-500/10",
  offline: "text-slate-400 border-slate-600 bg-slate-500/10",
  faulted: "text-red-400 border-red-700 bg-red-500/10",
  unavailable: "text-slate-500 border-slate-700 bg-slate-700/10",
};

function statusColor(s) {
  return STATUS_COLORS[s?.toLowerCase()] || STATUS_COLORS.offline;
}

function formatDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("hu-HU", {
    month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

// Add/Edit modal
function CPModal({ cp, onClose, onSave }) {
  const isEdit = !!cp;
  const [form, setForm] = useState({
    ocpp_id: cp?.ocpp_id || "",
    model: cp?.model || "",
    vendor: cp?.vendor || "",
    serial_number: cp?.serial_number || "",
    firmware_version: cp?.firmware_version || "",
    status: cp?.status || "available",
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  function set(key, val) {
    setForm((f) => ({ ...f, [key]: val }));
  }

  async function handleSave() {
    setLoading(true);
    setError("");
    try {
      if (isEdit) {
        await api.updateChargePoint(cp.id, {
          model: form.model || null,
          vendor: form.vendor || null,
          serial_number: form.serial_number || null,
          firmware_version: form.firmware_version || null,
          status: form.status || null,
        });
      } else {
        await api.createChargePoint({
          ocpp_id: form.ocpp_id,
          model: form.model || null,
          vendor: form.vendor || null,
          serial_number: form.serial_number || null,
        });
      }
      onSave();
      onClose();
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  const STATUSES = ["available", "charging", "preparing", "finishing", "offline", "faulted", "unavailable"];

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 px-4">
      <div className="bg-slate-800 rounded-2xl p-6 w-full max-w-md border border-slate-700 shadow-2xl">
        <h2 className="text-lg font-bold text-white mb-4">
          {isEdit ? `Töltő szerkesztése – ${cp.ocpp_id}` : "Új töltő hozzáadása"}
        </h2>

        {error && (
          <div className="bg-red-900/40 border border-red-700 text-red-300 rounded-lg px-3 py-2 text-sm mb-3">
            {error}
          </div>
        )}

        <div className="space-y-3">
          {!isEdit && (
            <div>
              <label className="block text-xs text-slate-400 mb-1">OCPP ID *</label>
              <input
                type="text"
                value={form.ocpp_id}
                onChange={(e) => set("ocpp_id", e.target.value)}
                placeholder="pl. CP001"
                className="w-full bg-slate-700 text-white rounded-lg px-3 py-2 text-sm border border-slate-600 focus:outline-none focus:border-blue-500"
              />
            </div>
          )}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-slate-400 mb-1">Gyártó</label>
              <input
                type="text"
                value={form.vendor}
                onChange={(e) => set("vendor", e.target.value)}
                className="w-full bg-slate-700 text-white rounded-lg px-3 py-2 text-sm border border-slate-600 focus:outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1">Modell</label>
              <input
                type="text"
                value={form.model}
                onChange={(e) => set("model", e.target.value)}
                className="w-full bg-slate-700 text-white rounded-lg px-3 py-2 text-sm border border-slate-600 focus:outline-none focus:border-blue-500"
              />
            </div>
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1">Sorozatszám</label>
            <input
              type="text"
              value={form.serial_number}
              onChange={(e) => set("serial_number", e.target.value)}
              className="w-full bg-slate-700 text-white rounded-lg px-3 py-2 text-sm border border-slate-600 focus:outline-none focus:border-blue-500"
            />
          </div>
          {isEdit && (
            <>
              <div>
                <label className="block text-xs text-slate-400 mb-1">Firmware verzió</label>
                <input
                  type="text"
                  value={form.firmware_version}
                  onChange={(e) => set("firmware_version", e.target.value)}
                  className="w-full bg-slate-700 text-white rounded-lg px-3 py-2 text-sm border border-slate-600 focus:outline-none focus:border-blue-500"
                />
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1">Státusz</label>
                <select
                  value={form.status}
                  onChange={(e) => set("status", e.target.value)}
                  className="w-full bg-slate-700 text-white rounded-lg px-3 py-2 text-sm border border-slate-600 focus:outline-none focus:border-blue-500"
                >
                  {STATUSES.map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </div>
            </>
          )}
        </div>

        <div className="flex gap-2 mt-5">
          <button
            onClick={onClose}
            className="flex-1 bg-slate-700 hover:bg-slate-600 text-white text-sm font-medium py-2 rounded-lg transition-colors"
          >
            Mégse
          </button>
          <button
            onClick={handleSave}
            disabled={loading || (!isEdit && !form.ocpp_id)}
            className="flex-1 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-sm font-medium py-2 rounded-lg transition-colors"
          >
            {loading ? "Mentés..." : "Mentés"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function AdminChargePoints() {
  const [cps, setCps] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editCp, setEditCp] = useState(null);   // CP object to edit
  const [showAdd, setShowAdd] = useState(false);
  const [deletingId, setDeletingId] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await api.chargePoints();
      setCps(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function handleDelete(cp) {
    if (!confirm(`Biztosan törlöd a(z) "${cp.ocpp_id}" töltőt? Ez az összes hozzá tartozó session-t is törli!`)) return;
    setDeletingId(cp.id);
    try {
      await api.deleteChargePoint(cp.id);
      load();
    } catch (e) {
      alert("Hiba: " + e.message);
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">Töltők</h1>
          <p className="text-slate-400 text-sm mt-1">{cps.length} töltő</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={load}
            className="bg-slate-700 hover:bg-slate-600 text-white text-sm px-3 py-2 rounded-lg transition-colors"
          >
            Frissítés
          </button>
          <button
            onClick={() => setShowAdd(true)}
            className="bg-blue-600 hover:bg-blue-500 text-white text-sm font-semibold px-4 py-2 rounded-lg transition-colors flex items-center gap-2"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            Töltő hozzáadása
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-900/40 border border-red-700 text-red-300 rounded-lg px-4 py-3 text-sm mb-4">
          {error}
        </div>
      )}

      {loading ? (
        <div className="text-slate-400 text-sm">Betöltés...</div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {cps.length === 0 && (
            <div className="col-span-full text-center text-slate-500 py-12">
              Még nincs töltő felvéve.
            </div>
          )}
          {cps.map((cp) => (
            <div key={cp.id} className="bg-slate-800 rounded-xl border border-slate-700 p-5">
              <div className="flex items-start justify-between mb-3">
                <div>
                  <div className="text-white font-bold text-base">{cp.ocpp_id}</div>
                  <div className="text-slate-400 text-xs mt-0.5">
                    {cp.vendor} {cp.model}
                  </div>
                </div>
                <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs border ${statusColor(cp.status)}`}>
                  {cp.status}
                </span>
              </div>

              <div className="space-y-1 text-xs text-slate-400 mb-4">
                {cp.serial_number && (
                  <div>S/N: <span className="text-slate-300">{cp.serial_number}</span></div>
                )}
                {cp.firmware_version && (
                  <div>FW: <span className="text-slate-300">{cp.firmware_version}</span></div>
                )}
                {cp.location_name && (
                  <div>Helyszín: <span className="text-slate-300">{cp.location_name}</span></div>
                )}
                <div>Utolsó ping: <span className="text-slate-300">{formatDate(cp.last_seen_at)}</span></div>
              </div>

              <div className="flex gap-2">
                <button
                  onClick={() => setEditCp(cp)}
                  className="flex-1 bg-slate-700 hover:bg-slate-600 text-white text-xs font-medium py-1.5 rounded-lg transition-colors"
                >
                  Szerkesztés
                </button>
                <button
                  onClick={() => handleDelete(cp)}
                  disabled={deletingId === cp.id}
                  className="bg-red-900/40 hover:bg-red-800/60 disabled:opacity-50 text-red-400 text-xs font-medium px-3 py-1.5 rounded-lg transition-colors border border-red-800"
                >
                  {deletingId === cp.id ? "..." : "Törlés"}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {showAdd && (
        <CPModal
          cp={null}
          onClose={() => setShowAdd(false)}
          onSave={load}
        />
      )}
      {editCp && (
        <CPModal
          cp={editCp}
          onClose={() => setEditCp(null)}
          onSave={load}
        />
      )}
    </div>
  );
}
