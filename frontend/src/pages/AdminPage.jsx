import { useState, useEffect, useCallback } from "react";

const REFRESH_MS = 15_000;

// ── Formatters ──────────────────────────────────────────────────────────────

function fmtHuf(v) {
  if (v == null) return "—";
  return `${Math.round(v).toLocaleString("hu-HU")} Ft`;
}
function fmtKwh(v) {
  if (v == null) return "—";
  return `${Number(v).toFixed(3)} kWh`;
}
function fmtDuration(s) {
  if (s == null) return "—";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}ó ${m}p`;
  if (m > 0) return `${m}p ${sec}mp`;
  return `${sec}mp`;
}
function fmtDt(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("hu-HU", { timeZone: "Europe/Budapest" });
}
function fmtDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("hu-HU", { timeZone: "Europe/Budapest" });
}
function timeAgo(iso) {
  if (!iso) return "—";
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${s}mp`;
  if (s < 3600) return `${Math.floor(s / 60)}p`;
  if (s < 86400) return `${Math.floor(s / 3600)}ó`;
  return `${Math.floor(s / 86400)}n`;
}

// ── Status colours ───────────────────────────────────────────────────────────

const STATUS_COLORS = {
  available:   "bg-emerald-500/20 text-emerald-300 border-emerald-700/40",
  charging:    "bg-blue-500/20 text-blue-300 border-blue-700/40",
  preparing:   "bg-amber-500/20 text-amber-300 border-amber-700/40",
  finishing:   "bg-amber-500/20 text-amber-300 border-amber-700/40",
  offline:     "bg-slate-700/40 text-slate-400 border-slate-600/30",
  faulted:     "bg-red-500/20 text-red-300 border-red-700/40",
  // intent statuses
  paid:              "bg-emerald-500/20 text-emerald-300 border-emerald-700/40",
  pending_payment:   "bg-amber-500/20 text-amber-300 border-amber-700/40",
  expired:           "bg-slate-700/40 text-slate-400 border-slate-600/30",
  cancelled:         "bg-slate-700/40 text-slate-400 border-slate-600/30",
  failed:            "bg-red-500/20 text-red-300 border-red-700/40",
};

function Badge({ status, label }) {
  const cls = STATUS_COLORS[String(status || "").toLowerCase()] || "bg-slate-700/40 text-slate-400 border-slate-600/30";
  return (
    <span className={`inline-block rounded-md border px-1.5 py-0.5 text-xs font-medium ${cls}`}>
      {label || status || "—"}
    </span>
  );
}

// ── Sub-components ───────────────────────────────────────────────────────────

function StatCard({ label, value, sub, accent }) {
  const accents = {
    blue:    "border-blue-700/30 bg-blue-950/20",
    emerald: "border-emerald-700/30 bg-emerald-950/20",
    amber:   "border-amber-700/30 bg-amber-950/20",
    slate:   "border-slate-700/30 bg-slate-800/20",
  };
  return (
    <div className={`rounded-2xl border p-4 ${accents[accent] || accents.slate}`}>
      <div className="text-xs text-slate-400 mb-1">{label}</div>
      <div className="text-2xl font-semibold tabular-nums text-slate-100">{value ?? "—"}</div>
      {sub && <div className="text-xs text-slate-500 mt-0.5">{sub}</div>}
    </div>
  );
}

function SectionHead({ children }) {
  return <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400 mb-3">{children}</h2>;
}

function Th({ children, className = "" }) {
  return <th className={`px-3 py-2 text-left text-xs font-semibold text-slate-400 whitespace-nowrap ${className}`}>{children}</th>;
}
function Td({ children, className = "" }) {
  return <td className={`px-3 py-2 text-sm text-slate-300 ${className}`}>{children}</td>;
}

// ── Login ────────────────────────────────────────────────────────────────────

function LoginForm({ onLogin }) {
  const [user, setUser] = useState("");
  const [pass, setPass] = useState("");
  const [err, setErr] = useState("");

  function submit(e) {
    e.preventDefault();
    if (!user || !pass) { setErr("Töltsd ki mindkét mezőt."); return; }
    onLogin(user, pass, setErr);
  }

  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center p-6">
      <div className="w-full max-w-sm bg-slate-900 border border-slate-800 rounded-2xl p-8 shadow-xl">
        <div className="text-center mb-6">
          <div className="text-2xl font-bold text-slate-100">Admin</div>
          <div className="text-sm text-slate-400 mt-1">Energiafelhő Kft.</div>
        </div>
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="block text-xs text-slate-400 mb-1.5">Felhasználónév</label>
            <input
              className="w-full rounded-xl border border-slate-700 bg-slate-800 px-3 py-2.5 text-slate-100 outline-none focus:ring-2 focus:ring-blue-500/40 text-sm"
              value={user} onChange={e => setUser(e.target.value)} autoFocus autoComplete="username"
            />
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1.5">Jelszó</label>
            <input
              type="password"
              className="w-full rounded-xl border border-slate-700 bg-slate-800 px-3 py-2.5 text-slate-100 outline-none focus:ring-2 focus:ring-blue-500/40 text-sm"
              value={pass} onChange={e => setPass(e.target.value)} autoComplete="current-password"
            />
          </div>
          {err && <div className="text-sm text-red-400">{err}</div>}
          <button type="submit" className="w-full rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-semibold py-2.5 text-sm transition">
            Bejelentkezés
          </button>
        </form>
      </div>
    </div>
  );
}

// ── Tabs ─────────────────────────────────────────────────────────────────────

const TABS = [
  { id: "overview",  label: "Áttekintés" },
  { id: "chargers",  label: "Töltők" },
  { id: "sessions",  label: "Sessionök" },
  { id: "intents",   label: "Intentek" },
];

// ── Overview tab ─────────────────────────────────────────────────────────────

function OverviewTab({ stats, chargers, sessions }) {
  if (!stats) return <div className="text-slate-500 text-sm py-8 text-center">Betöltés…</div>;

  const activeSessions = sessions.filter(s => s.is_active);

  return (
    <div className="space-y-8">
      {/* Stat grid */}
      <div>
        <SectionHead>Mai nap</SectionHead>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatCard label="Aktív session" value={stats.sessions.active} accent="blue" />
          <StatCard label="Mai sessionök" value={stats.sessions.today} accent="slate" />
          <StatCard label="Mai energia" value={`${stats.energy.today_kwh.toFixed(2)} kWh`} accent="emerald" />
          <StatCard label="Mai bevétel" value={fmtHuf(stats.revenue.today_huf)} accent="emerald" />
        </div>
      </div>
      <div>
        <SectionHead>Összesített</SectionHead>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatCard label="Összes session" value={stats.sessions.total} accent="slate" />
          <StatCard label="Összes energia" value={`${stats.energy.total_kwh.toFixed(2)} kWh`} accent="slate" />
          <StatCard label="Összes bevétel" value={fmtHuf(stats.revenue.total_huf)} accent="slate" />
          <StatCard label="Töltők" value={stats.charge_points.total} accent="slate" />
        </div>
      </div>

      {/* Töltők státusz */}
      <div>
        <SectionHead>Töltők állapota</SectionHead>
        <div className="flex flex-wrap gap-2">
          {Object.entries(stats.charge_points.by_status).map(([st, cnt]) => (
            <div key={st} className="flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-800/50 px-3 py-2">
              <Badge status={st} label={st} />
              <span className="text-slate-200 font-semibold text-sm">{cnt}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Aktív sessionök */}
      {activeSessions.length > 0 && (
        <div>
          <SectionHead>Aktív sessionök ({activeSessions.length})</SectionHead>
          <div className="overflow-x-auto rounded-xl border border-slate-800">
            <table className="w-full">
              <thead className="bg-slate-800/60">
                <tr>
                  <Th>#</Th><Th>Töltő</Th><Th>Email</Th><Th>Kezdés</Th><Th>Időtartam</Th><Th>Energia</Th><Th>Díj</Th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {activeSessions.map(s => (
                  <tr key={s.id} className="hover:bg-slate-800/30">
                    <Td>{s.id}</Td>
                    <Td><span className="font-mono text-xs">{s.charge_point_ocpp_id}</span></Td>
                    <Td>{s.anonymous_email || "—"}</Td>
                    <Td className="whitespace-nowrap">{fmtDt(s.started_at)}</Td>
                    <Td>{fmtDuration(s.duration_s)}</Td>
                    <Td>{fmtKwh(s.energy_kwh)}</Td>
                    <Td>{fmtHuf(s.cost_huf)}</Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Chargers tab ─────────────────────────────────────────────────────────────

function ChargersTab({ chargers }) {
  return (
    <div>
      <SectionHead>Töltők ({chargers.length})</SectionHead>
      <div className="overflow-x-auto rounded-xl border border-slate-800">
        <table className="w-full">
          <thead className="bg-slate-800/60">
            <tr>
              <Th>ID</Th><Th>OCPP ID</Th><Th>Státusz</Th><Th>Helyszín</Th><Th>Csatlakozó</Th>
              <Th>Max kW</Th><Th>Model</Th><Th>Firmware</Th><Th>Sorozatszám</Th><Th>Utoljára látva</Th><Th>Felvéve</Th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {chargers.map(cp => (
              <tr key={cp.id} className="hover:bg-slate-800/30">
                <Td>{cp.id}</Td>
                <Td><span className="font-mono text-xs text-slate-200">{cp.ocpp_id}</span></Td>
                <Td><Badge status={cp.status} label={cp.status} /></Td>
                <Td>
                  <div>{cp.location_name || "—"}</div>
                  {cp.address_text && <div className="text-xs text-slate-500">{cp.address_text}</div>}
                </Td>
                <Td>{cp.connector_type || "—"}</Td>
                <Td>{cp.max_power_kw ? `${cp.max_power_kw} kW` : "—"}</Td>
                <Td>{[cp.vendor, cp.model].filter(Boolean).join(" ") || "—"}</Td>
                <Td className="font-mono text-xs">{cp.firmware_version || "—"}</Td>
                <Td className="font-mono text-xs">{cp.serial_number || "—"}</Td>
                <Td className="whitespace-nowrap text-xs">{cp.last_seen_at ? `${timeAgo(cp.last_seen_at)} előtt` : "—"}</Td>
                <Td className="whitespace-nowrap text-xs">{fmtDate(cp.created_at)}</Td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Sessions tab ──────────────────────────────────────────────────────────────

function SessionsTab({ sessions, onStop, stopBusy }) {
  const [showAll, setShowAll] = useState(false);
  const [expandedId, setExpandedId] = useState(null);

  const active = sessions.filter(s => s.is_active);
  const finished = sessions.filter(s => !s.is_active);
  const displayed = showAll ? finished : finished.slice(0, 20);

  function SessionRow({ s }) {
    const expanded = expandedId === s.id;
    return (
      <>
        <tr
          className={`hover:bg-slate-800/30 cursor-pointer ${expanded ? "bg-slate-800/40" : ""}`}
          onClick={() => setExpandedId(expanded ? null : s.id)}
        >
          <Td>
            <span className="font-mono text-xs">{s.id}</span>
            {s.is_active && <span className="ml-1.5 inline-block w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />}
          </Td>
          <Td><span className="font-mono text-xs">{s.charge_point_ocpp_id}</span></Td>
          <Td>
            <div>{s.anonymous_email || "—"}</div>
            {s.intent?.billing_name && <div className="text-xs text-slate-500">{s.intent.billing_name}</div>}
          </Td>
          <Td className="whitespace-nowrap text-xs">{fmtDt(s.started_at)}</Td>
          <Td>{fmtDuration(s.duration_s)}</Td>
          <Td>{fmtKwh(s.energy_kwh)}</Td>
          <Td>{fmtHuf(s.cost_huf)}</Td>
          <Td>
            {s.timed_out ? <Badge status="expired" label="timeout" /> :
             s.is_active ? <Badge status="charging" label="aktív" /> :
             <Badge status="available" label="kész" />}
          </Td>
          <Td>{s.invoice_number || "—"}</Td>
          <Td>
            {s.is_active && s.ocpp_transaction_id && (
              <button
                className="rounded-lg border border-rose-700/50 bg-rose-900/20 px-2.5 py-1 text-xs text-rose-300 hover:bg-rose-900/40 transition disabled:opacity-40"
                disabled={stopBusy === s.id}
                onClick={e => { e.stopPropagation(); onStop(s.id); }}
              >
                {stopBusy === s.id ? "…" : "Stop"}
              </button>
            )}
          </Td>
        </tr>
        {expanded && (
          <tr className="bg-slate-800/20">
            <td colSpan={10} className="px-4 py-3">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs">
                <div>
                  <div className="text-slate-500 mb-0.5">OCPP Transaction ID</div>
                  <div className="font-mono text-slate-300">{s.ocpp_transaction_id || "—"}</div>
                </div>
                <div>
                  <div className="text-slate-500 mb-0.5">Töltő helyszín</div>
                  <div className="text-slate-300">{s.charge_point_location || "—"}</div>
                </div>
                {s.intent && (
                  <>
                    <div>
                      <div className="text-slate-500 mb-0.5">Fizetési státusz</div>
                      <Badge status={s.intent.status} label={s.intent.status} />
                    </div>
                    <div>
                      <div className="text-slate-500 mb-0.5">Zárolás</div>
                      <div className="text-slate-300">{fmtHuf(s.intent.hold_amount_huf)}</div>
                    </div>
                    <div>
                      <div className="text-slate-500 mb-0.5">Számlázás</div>
                      <div className="text-slate-300">
                        {s.intent.billing_name}
                        {s.intent.billing_company && <> · {s.intent.billing_company}</>}
                        {" · "}{s.intent.billing_city}, {s.intent.billing_country}
                        {" · "}{s.intent.billing_type === "business" ? "Céges" : "Magán"}
                      </div>
                    </div>
                    {s.intent.stripe_payment_intent_id && (
                      <div>
                        <div className="text-slate-500 mb-0.5">Stripe PI</div>
                        <div className="font-mono text-slate-400 text-xs break-all">{s.intent.stripe_payment_intent_id}</div>
                      </div>
                    )}
                    {s.intent.last_error && (
                      <div className="col-span-2">
                        <div className="text-slate-500 mb-0.5">Utolsó hiba</div>
                        <div className="text-red-400">{s.intent.last_error}</div>
                      </div>
                    )}
                  </>
                )}
                {s.finished_at && (
                  <div>
                    <div className="text-slate-500 mb-0.5">Befejezve</div>
                    <div className="text-slate-300">{fmtDt(s.finished_at)}</div>
                  </div>
                )}
              </div>
            </td>
          </tr>
        )}
      </>
    );
  }

  const cols = (
    <thead className="bg-slate-800/60">
      <tr>
        <Th>#</Th><Th>Töltő</Th><Th>Email / Névf</Th><Th>Kezdés</Th>
        <Th>Időtartam</Th><Th>Energia</Th><Th>Díj</Th><Th>Státusz</Th><Th>Számla</Th><Th></Th>
      </tr>
    </thead>
  );

  return (
    <div className="space-y-8">
      {/* Aktív */}
      <div>
        <SectionHead>Aktív sessionök ({active.length})</SectionHead>
        {active.length === 0 ? (
          <div className="text-slate-500 text-sm py-4">Nincs aktív session.</div>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-slate-800">
            <table className="w-full">
              {cols}
              <tbody className="divide-y divide-slate-800">
                {active.map(s => <SessionRow key={s.id} s={s} />)}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Befejezett */}
      <div>
        <SectionHead>Befejezett sessionök ({finished.length})</SectionHead>
        <div className="overflow-x-auto rounded-xl border border-slate-800">
          <table className="w-full">
            {cols}
            <tbody className="divide-y divide-slate-800">
              {displayed.map(s => <SessionRow key={s.id} s={s} />)}
            </tbody>
          </table>
        </div>
        {finished.length > 20 && (
          <button
            className="mt-2 text-xs text-blue-400 hover:text-blue-300"
            onClick={() => setShowAll(v => !v)}
          >
            {showAll ? "Kevesebb mutatása" : `Mind mutatása (${finished.length})`}
          </button>
        )}
      </div>
    </div>
  );
}

// ── Intents tab ───────────────────────────────────────────────────────────────

function IntentsTab({ intents }) {
  const [expandedId, setExpandedId] = useState(null);

  return (
    <div>
      <SectionHead>Charging intentek ({intents.length})</SectionHead>
      <div className="overflow-x-auto rounded-xl border border-slate-800">
        <table className="w-full">
          <thead className="bg-slate-800/60">
            <tr>
              <Th>#</Th><Th>Töltő</Th><Th>Email</Th><Th>Számlázási név</Th>
              <Th>Státusz</Th><Th>Zárolás</Th><Th>Típus</Th><Th>Lejár</Th><Th>Létrehozva</Th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {intents.map(i => {
              const expanded = expandedId === i.id;
              return (
                <>
                  <tr
                    key={i.id}
                    className={`hover:bg-slate-800/30 cursor-pointer ${expanded ? "bg-slate-800/40" : ""}`}
                    onClick={() => setExpandedId(expanded ? null : i.id)}
                  >
                    <Td><span className="font-mono text-xs">{i.id}</span></Td>
                    <Td><span className="font-mono text-xs">{i.charge_point_ocpp_id}</span></Td>
                    <Td>{i.anonymous_email}</Td>
                    <Td>{i.billing_name || "—"}</Td>
                    <Td><Badge status={i.status} label={i.status} /></Td>
                    <Td>{fmtHuf(i.hold_amount_huf)}</Td>
                    <Td>{i.billing_type === "business" ? "Céges" : "Magán"}</Td>
                    <Td className="text-xs whitespace-nowrap">{fmtDt(i.expires_at)}</Td>
                    <Td className="text-xs whitespace-nowrap">{fmtDt(i.created_at)}</Td>
                  </tr>
                  {expanded && (
                    <tr key={`${i.id}-exp`} className="bg-slate-800/20">
                      <td colSpan={9} className="px-4 py-3">
                        <div className="grid grid-cols-2 md:grid-cols-3 gap-4 text-xs">
                          <div>
                            <div className="text-slate-500 mb-0.5">Cím</div>
                            <div className="text-slate-300">
                              {[i.billing_zip, i.billing_city, i.billing_street, i.billing_country].filter(Boolean).join(", ")}
                            </div>
                          </div>
                          {i.billing_company && (
                            <div>
                              <div className="text-slate-500 mb-0.5">Cégnév</div>
                              <div className="text-slate-300">{i.billing_company}</div>
                            </div>
                          )}
                          {i.billing_tax_number && (
                            <div>
                              <div className="text-slate-500 mb-0.5">Adószám</div>
                              <div className="font-mono text-slate-300">{i.billing_tax_number}</div>
                            </div>
                          )}
                          {i.stripe_payment_intent_id && (
                            <div>
                              <div className="text-slate-500 mb-0.5">Stripe PI</div>
                              <div className="font-mono text-slate-400 break-all">{i.stripe_payment_intent_id}</div>
                            </div>
                          )}
                          {i.payment_provider_ref && (
                            <div>
                              <div className="text-slate-500 mb-0.5">Stripe Session</div>
                              <div className="font-mono text-slate-400 break-all">{i.payment_provider_ref}</div>
                            </div>
                          )}
                          {i.cancel_reason && (
                            <div>
                              <div className="text-slate-500 mb-0.5">Törlés oka</div>
                              <div className="text-slate-300">{i.cancel_reason}</div>
                            </div>
                          )}
                          {i.last_error && (
                            <div className="col-span-2">
                              <div className="text-slate-500 mb-0.5">Utolsó hiba</div>
                              <div className="text-red-400">{i.last_error}</div>
                            </div>
                          )}
                          <div>
                            <div className="text-slate-500 mb-0.5">Frissítve</div>
                            <div className="text-slate-300">{fmtDt(i.updated_at)}</div>
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────

export default function AdminPage() {
  const [token, setToken] = useState(() => sessionStorage.getItem("admin_token") || "");
  const [tab, setTab] = useState("overview");
  const [stats, setStats] = useState(null);
  const [chargers, setChargers] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [intents, setIntents] = useState([]);
  const [loading, setLoading] = useState(false);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [stopBusy, setStopBusy] = useState(null);
  const [err, setErr] = useState("");

  const apiFetch = useCallback(async (path) => {
    const res = await fetch(path, {
      headers: { Authorization: `Basic ${token}` },
    });
    if (res.status === 401) {
      sessionStorage.removeItem("admin_token");
      setToken("");
      throw new Error("401");
    }
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }, [token]);

  const refresh = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setErr("");
    try {
      const [st, cps, sess, ints] = await Promise.all([
        apiFetch("/api/admin/stats"),
        apiFetch("/api/admin/charge-points"),
        apiFetch("/api/admin/sessions?limit=200"),
        apiFetch("/api/admin/intents?limit=200"),
      ]);
      setStats(st);
      setChargers(cps);
      setSessions(sess);
      setIntents(ints);
      setLastUpdated(new Date());
    } catch (e) {
      if (e.message !== "401") setErr("Frissítési hiba: " + e.message);
    } finally {
      setLoading(false);
    }
  }, [token, apiFetch]);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, REFRESH_MS);
    return () => clearInterval(t);
  }, [refresh]);

  async function handleLogin(user, pass, setLoginErr) {
    const t = btoa(`${user}:${pass}`);
    const res = await fetch("/api/admin/stats", {
      headers: { Authorization: `Basic ${t}` },
    });
    if (res.status === 401) {
      setLoginErr("Hibás felhasználónév vagy jelszó.");
      return;
    }
    sessionStorage.setItem("admin_token", t);
    setToken(t);
  }

  async function handleStop(sessionId) {
    setStopBusy(sessionId);
    try {
      await apiFetch(`/api/admin/sessions/${sessionId}/stop`);
      // Wait a beat then refresh
      setTimeout(refresh, 1000);
    } catch (e) {
      setErr("Stop hiba: " + e.message);
    } finally {
      setStopBusy(null);
    }
  }

  function handleLogout() {
    sessionStorage.removeItem("admin_token");
    setToken("");
  }

  if (!token) {
    return <LoginForm onLogin={handleLogin} />;
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      {/* Header */}
      <div className="border-b border-slate-800 bg-slate-900/80 sticky top-0 z-10">
        <div className="mx-auto max-w-screen-2xl px-6 py-3 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <span className="font-bold text-slate-100">Admin Dashboard</span>
            {loading && (
              <div className="flex gap-1">
                {[0,1,2].map(i => (
                  <div key={i} className="w-1 h-1 rounded-full bg-blue-400 animate-bounce" style={{ animationDelay: `${i * 0.15}s` }} />
                ))}
              </div>
            )}
            {lastUpdated && !loading && (
              <span className="text-xs text-slate-500">Frissítve: {lastUpdated.toLocaleTimeString("hu-HU")}</span>
            )}
          </div>
          <div className="flex items-center gap-3">
            <button onClick={refresh} className="text-xs text-blue-400 hover:text-blue-300">Frissít</button>
            <button onClick={handleLogout} className="text-xs text-slate-500 hover:text-slate-300">Kijelentkezés</button>
          </div>
        </div>
        {/* Tabs */}
        <div className="mx-auto max-w-screen-2xl px-6">
          <div className="flex gap-0 border-t border-slate-800/50">
            {TABS.map(t => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={[
                  "px-4 py-2.5 text-sm font-medium border-b-2 transition -mb-px",
                  tab === t.id
                    ? "border-blue-500 text-blue-300"
                    : "border-transparent text-slate-400 hover:text-slate-200",
                ].join(" ")}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="mx-auto max-w-screen-2xl px-6 py-6">
        {err && (
          <div className="mb-4 rounded-xl border border-red-800/50 bg-red-950/30 px-4 py-2 text-sm text-red-300">
            {err}
          </div>
        )}
        {tab === "overview" && <OverviewTab stats={stats} chargers={chargers} sessions={sessions} />}
        {tab === "chargers" && <ChargersTab chargers={chargers} />}
        {tab === "sessions" && <SessionsTab sessions={sessions} onStop={handleStop} stopBusy={stopBusy} />}
        {tab === "intents"  && <IntentsTab intents={intents} />}
      </div>
    </div>
  );
}
