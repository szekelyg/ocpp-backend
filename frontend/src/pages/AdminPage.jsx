import { useState, useEffect, useCallback, useRef } from "react";

const REFRESH_MS = 15_000;

// ── Formatters ────────────────────────────────────────────────────────────────

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

// ── Status colours ────────────────────────────────────────────────────────────

const STATUS_COLORS = {
  available:       "bg-emerald-500/20 text-emerald-300 border-emerald-700/40",
  charging:        "bg-blue-500/20 text-blue-300 border-blue-700/40",
  preparing:       "bg-amber-500/20 text-amber-300 border-amber-700/40",
  finishing:       "bg-amber-500/20 text-amber-300 border-amber-700/40",
  offline:         "bg-slate-700/40 text-slate-400 border-slate-600/30",
  faulted:         "bg-red-500/20 text-red-300 border-red-700/40",
  paid:            "bg-emerald-500/20 text-emerald-300 border-emerald-700/40",
  pending_payment: "bg-amber-500/20 text-amber-300 border-amber-700/40",
  expired:         "bg-slate-700/40 text-slate-400 border-slate-600/30",
  cancelled:       "bg-slate-700/40 text-slate-400 border-slate-600/30",
  failed:          "bg-red-500/20 text-red-300 border-red-700/40",
};

function Badge({ status, label }) {
  const cls = STATUS_COLORS[String(status || "").toLowerCase()]
    || "bg-slate-700/40 text-slate-400 border-slate-600/30";
  return (
    <span className={`inline-block rounded-md border px-1.5 py-0.5 text-xs font-medium ${cls}`}>
      {label || status || "—"}
    </span>
  );
}

// ── Shared primitives ─────────────────────────────────────────────────────────

function Th({ children, className = "" }) {
  return (
    <th className={`px-3 py-2 text-left text-xs font-semibold text-slate-400 whitespace-nowrap ${className}`}>
      {children}
    </th>
  );
}
function Td({ children, className = "" }) {
  return <td className={`px-3 py-2 text-sm text-slate-300 align-top ${className}`}>{children}</td>;
}
function SectionHead({ children }) {
  return <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400 mb-3">{children}</h2>;
}

// ── Action button ─────────────────────────────────────────────────────────────

function ActionBtn({ onClick, busy, label, busyLabel, color = "slate", title }) {
  const colors = {
    slate:   "border-slate-600 bg-slate-700/30 text-slate-300 hover:bg-slate-700/60",
    blue:    "border-blue-700/50 bg-blue-900/20 text-blue-300 hover:bg-blue-900/40",
    rose:    "border-rose-700/50 bg-rose-900/20 text-rose-300 hover:bg-rose-900/40",
    amber:   "border-amber-700/50 bg-amber-900/20 text-amber-300 hover:bg-amber-900/40",
    emerald: "border-emerald-700/50 bg-emerald-900/20 text-emerald-300 hover:bg-emerald-900/40",
  };
  return (
    <button
      onClick={onClick}
      disabled={busy}
      title={title}
      className={`rounded-lg border px-2.5 py-1 text-xs transition disabled:opacity-40 whitespace-nowrap ${colors[color]}`}
    >
      {busy ? (busyLabel || "…") : label}
    </button>
  );
}

// ── Toast notification ────────────────────────────────────────────────────────

function useToast() {
  const [toasts, setToasts] = useState([]);
  const add = useCallback((msg, type = "ok") => {
    const id = Date.now();
    setToasts(t => [...t, { id, msg, type }]);
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 4000);
  }, []);
  return { toasts, add };
}

function Toasts({ toasts }) {
  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2">
      {toasts.map(t => (
        <div key={t.id} className={`rounded-xl border px-4 py-2.5 text-sm shadow-lg max-w-sm ${
          t.type === "ok"
            ? "border-emerald-700/50 bg-emerald-950/90 text-emerald-200"
            : "border-red-700/50 bg-red-950/90 text-red-200"
        }`}>
          {t.msg}
        </div>
      ))}
    </div>
  );
}

// ── Login ─────────────────────────────────────────────────────────────────────

function LoginForm({ onLogin }) {
  const [user, setUser] = useState("");
  const [pass, setPass] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    if (!user || !pass) { setErr("Töltsd ki mindkét mezőt."); return; }
    setBusy(true);
    await onLogin(user, pass, setErr);
    setBusy(false);
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
              value={user} onChange={e => setUser(e.target.value)}
              autoFocus autoComplete="username"
            />
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1.5">Jelszó</label>
            <input
              type="password"
              className="w-full rounded-xl border border-slate-700 bg-slate-800 px-3 py-2.5 text-slate-100 outline-none focus:ring-2 focus:ring-blue-500/40 text-sm"
              value={pass} onChange={e => setPass(e.target.value)}
              autoComplete="current-password"
            />
          </div>
          {err && <div className="text-sm text-red-400">{err}</div>}
          <button
            type="submit" disabled={busy}
            className="w-full rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-semibold py-2.5 text-sm transition disabled:opacity-50"
          >
            {busy ? "…" : "Bejelentkezés"}
          </button>
        </form>
      </div>
    </div>
  );
}

// ── Overview tab ──────────────────────────────────────────────────────────────

function StatCard({ label, value, sub, accent, alert }) {
  const accents = {
    blue:    "border-blue-700/30 bg-blue-950/20",
    emerald: "border-emerald-700/30 bg-emerald-950/20",
    amber:   "border-amber-700/30 bg-amber-950/20",
    rose:    "border-rose-700/30 bg-rose-950/20",
    slate:   "border-slate-700/30 bg-slate-800/20",
  };
  return (
    <div className={`rounded-2xl border p-4 ${accents[accent] || accents.slate}`}>
      <div className="text-xs text-slate-400 mb-1">{label}</div>
      <div className={`text-2xl font-semibold tabular-nums ${alert ? "text-rose-300" : "text-slate-100"}`}>
        {value ?? "—"}
      </div>
      {sub && <div className="text-xs text-slate-500 mt-0.5">{sub}</div>}
    </div>
  );
}

function OverviewTab({ stats, sessions }) {
  if (!stats) return <div className="text-slate-500 text-sm py-8 text-center">Betöltés…</div>;
  const activeSessions = sessions.filter(s => s.is_active);
  const missingInvoices = stats.alerts?.missing_invoices || 0;

  return (
    <div className="space-y-8">
      {missingInvoices > 0 && (
        <div className="rounded-xl border border-rose-700/50 bg-rose-950/30 px-4 py-3 flex items-center gap-3">
          <span className="text-rose-300 font-semibold text-sm">⚠ {missingInvoices} befejezett session-ból hiányzik a számla</span>
          <span className="text-xs text-rose-400/70">Ellenőrizd a Sessionök tabon</span>
        </div>
      )}

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
          <StatCard label="Hiányzó számlák" value={missingInvoices} accent={missingInvoices > 0 ? "rose" : "slate"} alert={missingInvoices > 0} />
        </div>
      </div>

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

      {activeSessions.length > 0 && (
        <div>
          <SectionHead>Aktív sessionök ({activeSessions.length})</SectionHead>
          <div className="overflow-x-auto rounded-xl border border-slate-800">
            <table className="w-full">
              <thead className="bg-slate-800/60">
                <tr><Th>#</Th><Th>Töltő</Th><Th>Email</Th><Th>Kezdés</Th><Th>Időtartam</Th><Th>Energia</Th><Th>Díj</Th></tr>
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

// ── Chargers tab ──────────────────────────────────────────────────────────────

function ChargersTab({ chargers, apiFetch, toast }) {
  const [resetBusy, setResetBusy] = useState(null);
  const [configOpen, setConfigOpen] = useState(null);
  const [configData, setConfigData] = useState(null);
  const [configLoading, setConfigLoading] = useState(false);

  async function doReset(cp, type = "Soft") {
    setResetBusy(cp.id);
    try {
      await apiFetch(`/api/admin/charge-points/${cp.id}/reset?reset_type=${type}`, { method: "POST" });
      toast(`${cp.ocpp_id} ${type} reset elküldve`, "ok");
    } catch (e) {
      toast(`Reset hiba: ${e.message}`, "err");
    } finally {
      setResetBusy(null);
    }
  }

  async function doGetConfig(cp) {
    setConfigOpen(cp.ocpp_id);
    setConfigData(null);
    setConfigLoading(true);
    try {
      const res = await apiFetch(`/api/admin/charge-points/${cp.id}/config`);
      setConfigData(res.config);
    } catch (e) {
      setConfigData({ error: e.message });
    } finally {
      setConfigLoading(false);
    }
  }

  return (
    <div>
      <SectionHead>Töltők ({chargers.length})</SectionHead>
      <div className="overflow-x-auto rounded-xl border border-slate-800">
        <table className="w-full">
          <thead className="bg-slate-800/60">
            <tr>
              <Th>ID</Th><Th>OCPP ID</Th><Th>Státusz</Th><Th>Helyszín</Th>
              <Th>Csatl.</Th><Th>Max kW</Th><Th>Model</Th><Th>Firmware</Th>
              <Th>Sorozatszám</Th><Th>Utoljára látva</Th><Th>Felvéve</Th><Th>Műveletek</Th>
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
                <Td className="whitespace-nowrap text-xs">{cp.last_seen_at ? `${timeAgo(cp.last_seen_at)} ezelőtt` : "—"}</Td>
                <Td className="whitespace-nowrap text-xs">{fmtDate(cp.created_at)}</Td>
                <Td>
                  <div className="flex gap-1.5 flex-wrap">
                    <ActionBtn
                      label="Soft Reset" color="amber"
                      busy={resetBusy === cp.id}
                      onClick={() => doReset(cp, "Soft")}
                      title="OCPP Soft Reset küldése"
                    />
                    <ActionBtn
                      label="Hard Reset" color="rose"
                      busy={resetBusy === cp.id}
                      onClick={() => doReset(cp, "Hard")}
                      title="OCPP Hard Reset küldése"
                    />
                    <ActionBtn
                      label="GetConfig" color="blue"
                      onClick={() => doGetConfig(cp)}
                      title="OCPP GetConfiguration lekérdezés"
                    />
                  </div>
                </Td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* GetConfig modal */}
      {configOpen && (
        <div className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-4" onClick={() => setConfigOpen(null)}>
          <div className="bg-slate-900 border border-slate-700 rounded-2xl shadow-2xl max-w-2xl w-full max-h-[80vh] flex flex-col" onClick={e => e.stopPropagation()}>
            <div className="px-5 py-4 border-b border-slate-700 flex items-center justify-between">
              <div className="font-semibold text-slate-100">GetConfiguration – {configOpen}</div>
              <button onClick={() => setConfigOpen(null)} className="text-slate-400 hover:text-slate-200 text-xl leading-none">×</button>
            </div>
            <div className="overflow-auto p-4 flex-1">
              {configLoading ? (
                <div className="text-slate-400 text-sm">Lekérdezés…</div>
              ) : configData?.error ? (
                <div className="text-red-400 text-sm">{configData.error}</div>
              ) : configData?.configurationKey ? (
                <table className="w-full text-xs">
                  <thead><tr><Th>Key</Th><Th>Value</Th><Th>Readonly</Th></tr></thead>
                  <tbody className="divide-y divide-slate-800">
                    {configData.configurationKey.map(k => (
                      <tr key={k.key}>
                        <Td className="font-mono">{k.key}</Td>
                        <Td className="font-mono">{k.value ?? "—"}</Td>
                        <Td>{k.readonly ? "igen" : "nem"}</Td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <pre className="text-xs text-slate-300 whitespace-pre-wrap">{JSON.stringify(configData, null, 2)}</pre>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Session expanded detail + actions ─────────────────────────────────────────

function SessionDetail({ s, apiFetch, toast, onRefresh }) {
  const [busy, setBusy] = useState(null);
  const [confirmForceClose, setConfirmForceClose] = useState(false);

  const missingInvoice = !s.is_active && s.anonymous_email && s.intent && !s.invoice_number;

  async function doAction(key, path, method = "POST", opts = {}) {
    setBusy(key);
    try {
      const res = await apiFetch(path, { method });
      toast(opts.ok || "Sikeres művelet", "ok");
      onRefresh();
      return res;
    } catch (e) {
      toast(opts.err ? opts.err(e) : `Hiba: ${e.message}`, "err");
    } finally {
      setBusy(null);
    }
  }

  return (
    <tr className="bg-slate-800/20">
      <td colSpan={10} className="px-4 py-4">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs mb-4">
          <div>
            <div className="text-slate-500 mb-0.5">OCPP Transaction ID</div>
            <div className="font-mono text-slate-300">{s.ocpp_transaction_id || "—"}</div>
          </div>
          <div>
            <div className="text-slate-500 mb-0.5">Helyszín</div>
            <div className="text-slate-300">{s.charge_point_location || "—"}</div>
          </div>
          <div>
            <div className="text-slate-500 mb-0.5">Mérő start / stop</div>
            <div className="font-mono text-slate-300">
              {s.meter_start_wh != null ? `${s.meter_start_wh} Wh` : "—"} → {s.meter_stop_wh != null ? `${s.meter_stop_wh} Wh` : "—"}
            </div>
          </div>
          <div>
            <div className="text-slate-500 mb-0.5">Befejezve</div>
            <div className="text-slate-300">{fmtDt(s.finished_at)}</div>
          </div>
          {s.invoice_number && (
            <div>
              <div className="text-slate-500 mb-0.5">Számlaszám</div>
              <div className="font-mono text-emerald-300">{s.invoice_number}</div>
            </div>
          )}
          {missingInvoice && (
            <div>
              <div className="text-slate-500 mb-0.5">Számla</div>
              <span className="inline-block rounded border border-rose-700/50 bg-rose-900/20 px-1.5 py-0.5 text-rose-300 text-xs">
                Hiányzik!
              </span>
            </div>
          )}
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
                <div className="text-slate-300 leading-relaxed">
                  {s.intent.billing_name}
                  {s.intent.billing_company && <><br />{s.intent.billing_company}</>}
                  <br />{[s.intent.billing_zip, s.intent.billing_city].filter(Boolean).join(" ")}, {s.intent.billing_country}
                  <br />{s.intent.billing_type === "business" ? "Céges" : "Magánszemély"}
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
        </div>

        {/* Műveletek */}
        <div className="border-t border-slate-700/50 pt-3">
          <div className="text-xs text-slate-500 mb-2">Műveletek</div>
          <div className="flex flex-wrap gap-2">
            {/* OCPP Stop – csak aktív, OCPP sessionre */}
            {s.is_active && s.ocpp_transaction_id && (
              <ActionBtn
                color="rose" label="OCPP Stop" busy={busy === "stop"}
                title="RemoteStop küldése a töltőnek (töltő online kell)"
                onClick={() => doAction("stop", `/api/admin/sessions/${s.id}/stop`, "POST", {
                  ok: "OCPP Stop elküldve",
                  err: e => `Stop hiba: ${e.message}`,
                })}
              />
            )}

            {/* Force close – aktív sessionre */}
            {s.is_active && (
              confirmForceClose ? (
                <div className="flex items-center gap-2 rounded-lg border border-rose-700/50 bg-rose-950/30 px-2.5 py-1">
                  <span className="text-xs text-rose-300">Biztosan lezárod OCPP nélkül?</span>
                  <ActionBtn color="rose" label="Igen" busy={busy === "forceclose"}
                    onClick={() => { setConfirmForceClose(false); doAction("forceclose", `/api/admin/sessions/${s.id}/force-close`, "POST", {
                      ok: "Session lezárva (DB), Stripe settle futott",
                      err: e => `Force close hiba: ${e.message}`,
                    }); }}
                  />
                  <button className="text-xs text-slate-400 hover:text-slate-200" onClick={() => setConfirmForceClose(false)}>Mégse</button>
                </div>
              ) : (
                <ActionBtn
                  color="amber" label="Force Close" busy={busy === "forceclose"}
                  title="OCPP nélkül zárja le a sessiont a DB-ben + Stripe settle"
                  onClick={() => setConfirmForceClose(true)}
                />
              )
            )}

            {/* Bizonylat email */}
            {s.anonymous_email && (
              <ActionBtn
                color="blue" label="Bizonylat email" busy={busy === "receipt"}
                title={`Bizonylat email újraküldése → ${s.anonymous_email}`}
                onClick={() => doAction("receipt", `/api/admin/sessions/${s.id}/resend-receipt`, "POST", {
                  ok: `Bizonylat email elküldve → ${s.anonymous_email}`,
                  err: e => `Email hiba: ${e.message}`,
                })}
              />
            )}

            {/* Számla kiállítás */}
            {s.anonymous_email && s.intent && !s.is_active && (
              <ActionBtn
                color={missingInvoice ? "emerald" : "slate"}
                label={s.invoice_number ? "Új számla (force)" : "Számla kiállítás"}
                busy={busy === "invoice"}
                title={s.invoice_number
                  ? `Már van számlaszám: ${s.invoice_number}. Új kiállítás force=true-val.`
                  : "Számla kiállítása számlázz.hu-n + küldés"}
                onClick={() => {
                  const force = !!s.invoice_number;
                  doAction("invoice", `/api/admin/sessions/${s.id}/resend-invoice?force=${force}`, "POST", {
                    ok: "Számla kiállítva és elküldve",
                    err: e => `Számla hiba: ${e.message}`,
                  });
                }}
              />
            )}

            {/* Stripe settle */}
            {!s.is_active && s.intent?.stripe_payment_intent_id && (
              <ActionBtn
                color="slate" label="Stripe Settle" busy={busy === "settle"}
                title="Manuális Stripe capture/cancel futtatása"
                onClick={() => doAction("settle", `/api/admin/sessions/${s.id}/stripe-settle`, "POST", {
                  ok: "Stripe settle lefutott",
                  err: e => `Settle hiba: ${e.message}`,
                })}
              />
            )}
          </div>
        </div>
      </td>
    </tr>
  );
}

// ── Sessions tab ──────────────────────────────────────────────────────────────

function SessionsTab({ sessions, apiFetch, toast, onRefresh, highlightMissing }) {
  const [showAll, setShowAll] = useState(false);
  const [expandedId, setExpandedId] = useState(null);
  const [onlyMissing, setOnlyMissing] = useState(highlightMissing);

  const active = sessions.filter(s => s.is_active);
  let finished = sessions.filter(s => !s.is_active);
  if (onlyMissing) {
    finished = finished.filter(s => s.anonymous_email && s.intent && !s.invoice_number);
  }
  const displayed = showAll ? finished : finished.slice(0, 30);

  const cols = (
    <thead className="bg-slate-800/60">
      <tr>
        <Th>#</Th><Th>Töltő</Th><Th>Email / Számlázási név</Th><Th>Kezdés</Th>
        <Th>Időtartam</Th><Th>Energia</Th><Th>Díj</Th><Th>Státusz</Th><Th>Számla</Th><Th></Th>
      </tr>
    </thead>
  );

  function SessionRow({ s }) {
    const expanded = expandedId === s.id;
    const missingInvoice = !s.is_active && s.anonymous_email && s.intent && !s.invoice_number;
    return (
      <>
        <tr
          className={`cursor-pointer transition ${expanded ? "bg-slate-800/40" : "hover:bg-slate-800/30"} ${missingInvoice ? "border-l-2 border-l-rose-600/50" : ""}`}
          onClick={() => setExpandedId(expanded ? null : s.id)}
        >
          <Td>
            <span className="font-mono text-xs">{s.id}</span>
            {s.is_active && <span className="ml-1.5 inline-block w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse align-middle" />}
          </Td>
          <Td><span className="font-mono text-xs">{s.charge_point_ocpp_id}</span></Td>
          <Td>
            <div className="text-xs">{s.anonymous_email || "—"}</div>
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
          <Td>
            {s.invoice_number
              ? <span className="font-mono text-xs text-emerald-400">{s.invoice_number}</span>
              : missingInvoice
                ? <span className="text-rose-400 text-xs font-semibold">Hiányzik!</span>
                : <span className="text-slate-600 text-xs">—</span>
            }
          </Td>
          <Td><span className="text-slate-500 text-xs">{expanded ? "▲" : "▼"}</span></Td>
        </tr>
        {expanded && (
          <SessionDetail key={`${s.id}-detail`} s={s} apiFetch={apiFetch} toast={toast} onRefresh={onRefresh} />
        )}
      </>
    );
  }

  return (
    <div className="space-y-8">
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

      <div>
        <div className="flex items-center gap-4 mb-3">
          <SectionHead>Befejezett sessionök ({finished.length})</SectionHead>
          <label className="flex items-center gap-1.5 text-xs text-slate-400 cursor-pointer -mt-3">
            <input
              type="checkbox" checked={onlyMissing}
              onChange={e => { setOnlyMissing(e.target.checked); setShowAll(false); }}
              className="accent-rose-500"
            />
            Csak hiányzó számlás
          </label>
        </div>
        <div className="overflow-x-auto rounded-xl border border-slate-800">
          <table className="w-full">
            {cols}
            <tbody className="divide-y divide-slate-800">
              {displayed.map(s => <SessionRow key={s.id} s={s} />)}
            </tbody>
          </table>
        </div>
        {finished.length > 30 && (
          <button className="mt-2 text-xs text-blue-400 hover:text-blue-300"
            onClick={() => setShowAll(v => !v)}>
            {showAll ? "Kevesebb mutatása" : `Mind mutatása (${finished.length})`}
          </button>
        )}
      </div>
    </div>
  );
}

// ── Intents tab ───────────────────────────────────────────────────────────────

function IntentsTab({ intents, apiFetch, toast, onRefresh }) {
  const [expandedId, setExpandedId] = useState(null);
  const [refundBusy, setRefundBusy] = useState(null);

  async function doRefund(intent) {
    setRefundBusy(intent.id);
    try {
      const res = await apiFetch(`/api/admin/intents/${intent.id}/refund`, { method: "POST" });
      toast(`Visszatérítés: ${res.action}`, "ok");
      onRefresh();
    } catch (e) {
      toast(`Refund hiba: ${e.message}`, "err");
    } finally {
      setRefundBusy(null);
    }
  }

  return (
    <div>
      <SectionHead>Charging intentek ({intents.length})</SectionHead>
      <div className="overflow-x-auto rounded-xl border border-slate-800">
        <table className="w-full">
          <thead className="bg-slate-800/60">
            <tr>
              <Th>#</Th><Th>Töltő</Th><Th>Email</Th><Th>Számlázási név</Th>
              <Th>Státusz</Th><Th>Zárolás</Th><Th>Típus</Th><Th>Lejár</Th><Th>Létrehozva</Th><Th></Th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {intents.map(i => {
              const expanded = expandedId === i.id;
              const canRefund = i.stripe_payment_intent_id && ["paid", "pending_payment"].includes(i.status);
              return (
                <>
                  <tr
                    key={i.id}
                    className={`cursor-pointer transition ${expanded ? "bg-slate-800/40" : "hover:bg-slate-800/30"}`}
                    onClick={() => setExpandedId(expanded ? null : i.id)}
                  >
                    <Td><span className="font-mono text-xs">{i.id}</span></Td>
                    <Td><span className="font-mono text-xs">{i.charge_point_ocpp_id}</span></Td>
                    <Td className="text-xs">{i.anonymous_email}</Td>
                    <Td className="text-xs">{i.billing_name || "—"}</Td>
                    <Td><Badge status={i.status} label={i.status} /></Td>
                    <Td>{fmtHuf(i.hold_amount_huf)}</Td>
                    <Td className="text-xs">{i.billing_type === "business" ? "Céges" : "Magán"}</Td>
                    <Td className="text-xs whitespace-nowrap">{fmtDt(i.expires_at)}</Td>
                    <Td className="text-xs whitespace-nowrap">{fmtDt(i.created_at)}</Td>
                    <Td>
                      {canRefund && (
                        <ActionBtn
                          color="rose" label="Visszatérítés" busy={refundBusy === i.id}
                          title="Azonnali Stripe cancel/refund"
                          onClick={e => { e.stopPropagation(); doRefund(i); }}
                        />
                      )}
                    </Td>
                  </tr>
                  {expanded && (
                    <tr key={`${i.id}-exp`} className="bg-slate-800/20">
                      <td colSpan={10} className="px-4 py-3">
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
                              <div className="text-slate-500 mb-0.5">Stripe Checkout Session</div>
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

// ── Search tab ────────────────────────────────────────────────────────────────

function SearchTab({ apiFetch, toast, onRefresh }) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  async function doSearch(e) {
    e?.preventDefault();
    if (!q.trim()) return;
    setLoading(true);
    try {
      const res = await apiFetch(`/api/admin/search?q=${encodeURIComponent(q.trim())}`);
      setResults(res);
    } catch (err) {
      toast(`Keresési hiba: ${err.message}`, "err");
    } finally {
      setLoading(false);
    }
  }

  const total = results ? results.sessions.length + results.intents.length + results.charge_points.length : 0;

  return (
    <div className="space-y-6">
      <form onSubmit={doSearch} className="flex gap-3">
        <input
          ref={inputRef}
          value={q} onChange={e => setQ(e.target.value)}
          placeholder="Email, session ID, számlaszám, OCPP ID…"
          className="flex-1 rounded-xl border border-slate-700 bg-slate-800 px-4 py-2.5 text-slate-100 outline-none focus:ring-2 focus:ring-blue-500/40 text-sm"
        />
        <button type="submit" disabled={loading || !q.trim()}
          className="rounded-xl bg-blue-600 hover:bg-blue-500 text-white px-5 py-2.5 text-sm font-semibold disabled:opacity-40 transition">
          {loading ? "…" : "Keresés"}
        </button>
      </form>

      {results && (
        <div className="space-y-6">
          <div className="text-xs text-slate-400">{total} találat a(z) „{results.query}" keresésre</div>

          {results.charge_points.length > 0 && (
            <div>
              <SectionHead>Töltők ({results.charge_points.length})</SectionHead>
              <div className="overflow-x-auto rounded-xl border border-slate-800">
                <table className="w-full">
                  <thead className="bg-slate-800/60">
                    <tr><Th>ID</Th><Th>OCPP ID</Th><Th>Státusz</Th><Th>Helyszín</Th><Th>Utoljára látva</Th></tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800">
                    {results.charge_points.map(cp => (
                      <tr key={cp.id} className="hover:bg-slate-800/30">
                        <Td>{cp.id}</Td>
                        <Td><span className="font-mono text-xs">{cp.ocpp_id}</span></Td>
                        <Td><Badge status={cp.status} label={cp.status} /></Td>
                        <Td>{cp.location_name || "—"}</Td>
                        <Td className="text-xs">{cp.last_seen_at ? `${timeAgo(cp.last_seen_at)} ezelőtt` : "—"}</Td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {results.sessions.length > 0 && (
            <div>
              <SectionHead>Sessionök ({results.sessions.length})</SectionHead>
              <div className="space-y-2">
                {results.sessions.map(s => {
                  const missingInvoice = !s.is_active && s.anonymous_email && s.intent && !s.invoice_number;
                  return (
                    <div key={s.id} className={`rounded-xl border p-4 text-sm ${missingInvoice ? "border-rose-700/40 bg-rose-950/10" : "border-slate-700 bg-slate-800/30"}`}>
                      <div className="flex items-start justify-between gap-4 mb-2">
                        <div className="flex items-center gap-3">
                          <span className="font-mono text-slate-400 text-xs">#{s.id}</span>
                          <span className="font-mono text-xs text-slate-300">{s.charge_point_ocpp_id}</span>
                          {s.is_active ? <Badge status="charging" label="aktív" /> : <Badge status="available" label="kész" />}
                          {missingInvoice && <span className="text-rose-400 text-xs font-semibold">Számla hiányzik!</span>}
                        </div>
                        {s.invoice_number && <span className="font-mono text-xs text-emerald-400">{s.invoice_number}</span>}
                      </div>
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs text-slate-400">
                        <div>{s.anonymous_email || "—"}</div>
                        <div>{fmtDt(s.started_at)}</div>
                        <div>{fmtKwh(s.energy_kwh)} · {fmtHuf(s.cost_huf)}</div>
                        <div>{s.intent?.billing_name || "—"}</div>
                      </div>
                      {/* Mini actions */}
                      <div className="flex gap-2 mt-3 flex-wrap">
                        {s.anonymous_email && (
                          <ActionBtn color="blue" label="Bizonylat email" onClick={async () => {
                            try {
                              await apiFetch(`/api/admin/sessions/${s.id}/resend-receipt`, { method: "POST" });
                              toast(`Email elküldve → ${s.anonymous_email}`, "ok");
                            } catch (e) { toast(`Hiba: ${e.message}`, "err"); }
                          }} />
                        )}
                        {missingInvoice && (
                          <ActionBtn color="emerald" label="Számla kiállítás" onClick={async () => {
                            try {
                              await apiFetch(`/api/admin/sessions/${s.id}/resend-invoice`, { method: "POST" });
                              toast("Számla kiállítva", "ok");
                              onRefresh();
                            } catch (e) { toast(`Hiba: ${e.message}`, "err"); }
                          }} />
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {results.intents.length > 0 && (
            <div>
              <SectionHead>Intentek ({results.intents.length})</SectionHead>
              <div className="space-y-2">
                {results.intents.map(i => (
                  <div key={i.id} className="rounded-xl border border-slate-700 bg-slate-800/30 p-4 text-sm">
                    <div className="flex items-center gap-3 mb-1">
                      <span className="font-mono text-slate-400 text-xs">#{i.id}</span>
                      <Badge status={i.status} label={i.status} />
                      <span className="text-xs text-slate-300">{i.anonymous_email}</span>
                      <span className="text-xs text-slate-500">{fmtHuf(i.hold_amount_huf)} zárolás</span>
                    </div>
                    <div className="text-xs text-slate-400">{i.billing_name} · {fmtDt(i.created_at)}</div>
                    {i.stripe_payment_intent_id && ["paid", "pending_payment"].includes(i.status) && (
                      <div className="mt-2">
                        <ActionBtn color="rose" label="Visszatérítés" onClick={async () => {
                          try {
                            const res = await apiFetch(`/api/admin/intents/${i.id}/refund`, { method: "POST" });
                            toast(`Visszatérítés: ${res.action}`, "ok");
                            onRefresh();
                          } catch (e) { toast(`Hiba: ${e.message}`, "err"); }
                        }} />
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {total === 0 && (
            <div className="text-slate-500 text-sm text-center py-8">Nincs találat.</div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────

const TABS = [
  { id: "overview",  label: "Áttekintés" },
  { id: "chargers",  label: "Töltők" },
  { id: "sessions",  label: "Sessionök" },
  { id: "intents",   label: "Intentek" },
  { id: "search",    label: "Keresés" },
];

export default function AdminPage() {
  const [token, setToken] = useState(() => sessionStorage.getItem("admin_token") || "");
  const [tab, setTab] = useState("overview");
  const [stats, setStats] = useState(null);
  const [chargers, setChargers] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [intents, setIntents] = useState([]);
  const [loading, setLoading] = useState(false);
  const [lastUpdated, setLastUpdated] = useState(null);
  const { toasts, add: toast } = useToast();

  const apiFetch = useCallback(async (path, opts = {}) => {
    const res = await fetch(path, {
      ...opts,
      headers: {
        Authorization: `Basic ${token}`,
        ...(opts.headers || {}),
      },
    });
    if (res.status === 401) {
      sessionStorage.removeItem("admin_token");
      setToken("");
      throw new Error("401");
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const msg = typeof data?.detail === "string"
        ? data.detail
        : data?.detail?.hint || data?.detail?.error || data?.error || `HTTP ${res.status}`;
      throw new Error(msg);
    }
    return data;
  }, [token]);

  const refresh = useCallback(async () => {
    if (!token) return;
    setLoading(true);
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
      if (e.message !== "401") toast("Frissítési hiba: " + e.message, "err");
    } finally {
      setLoading(false);
    }
  }, [token, apiFetch]);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, REFRESH_MS);
    return () => clearInterval(t);
  }, [refresh]);

  async function handleLogin(user, pass, setErr) {
    const t = btoa(`${user}:${pass}`);
    try {
      const res = await fetch("/api/admin/stats", { headers: { Authorization: `Basic ${t}` } });
      if (res.status === 401) { setErr("Hibás felhasználónév vagy jelszó."); return; }
      if (!res.ok) { setErr(`Szerverhiba: HTTP ${res.status}`); return; }
    } catch { setErr("Szerver nem elérhető."); return; }
    sessionStorage.setItem("admin_token", t);
    setToken(t);
  }

  const missingInvoices = stats?.alerts?.missing_invoices || 0;

  if (!token) return <LoginForm onLogin={handleLogin} />;

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
                  <div key={i} className="w-1 h-1 rounded-full bg-blue-400 animate-bounce"
                    style={{ animationDelay: `${i * 0.15}s` }} />
                ))}
              </div>
            )}
            {lastUpdated && !loading && (
              <span className="text-xs text-slate-500">
                {lastUpdated.toLocaleTimeString("hu-HU")}
              </span>
            )}
            {missingInvoices > 0 && (
              <button
                onClick={() => setTab("sessions")}
                className="rounded-lg border border-rose-700/50 bg-rose-950/40 px-2 py-0.5 text-xs text-rose-300 hover:bg-rose-950/70"
              >
                ⚠ {missingInvoices} hiányzó számla
              </button>
            )}
          </div>
          <div className="flex items-center gap-3">
            <button onClick={() => setTab("search")} className="text-xs text-blue-400 hover:text-blue-300">Keresés</button>
            <button onClick={refresh} className="text-xs text-slate-400 hover:text-slate-200">Frissít</button>
            <button onClick={() => { sessionStorage.removeItem("admin_token"); setToken(""); }}
              className="text-xs text-slate-500 hover:text-slate-300">Kilépés</button>
          </div>
        </div>
        <div className="mx-auto max-w-screen-2xl px-6">
          <div className="flex gap-0 border-t border-slate-800/50">
            {TABS.map(t => (
              <button key={t.id} onClick={() => setTab(t.id)}
                className={[
                  "px-4 py-2.5 text-sm font-medium border-b-2 transition -mb-px",
                  tab === t.id
                    ? "border-blue-500 text-blue-300"
                    : "border-transparent text-slate-400 hover:text-slate-200",
                ].join(" ")}>
                {t.label}
                {t.id === "sessions" && missingInvoices > 0 && (
                  <span className="ml-1.5 inline-block rounded-full bg-rose-600 text-white text-xs px-1.5 py-px leading-none">
                    {missingInvoices}
                  </span>
                )}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="mx-auto max-w-screen-2xl px-6 py-6">
        {tab === "overview" && <OverviewTab stats={stats} sessions={sessions} />}
        {tab === "chargers" && <ChargersTab chargers={chargers} apiFetch={apiFetch} toast={toast} />}
        {tab === "sessions" && (
          <SessionsTab
            sessions={sessions} apiFetch={apiFetch} toast={toast} onRefresh={refresh}
            highlightMissing={missingInvoices > 0}
          />
        )}
        {tab === "intents" && <IntentsTab intents={intents} apiFetch={apiFetch} toast={toast} onRefresh={refresh} />}
        {tab === "search" && <SearchTab apiFetch={apiFetch} toast={toast} onRefresh={refresh} />}
      </div>

      <Toasts toasts={toasts} />
    </div>
  );
}
