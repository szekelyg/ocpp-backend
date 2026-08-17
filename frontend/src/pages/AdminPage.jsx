import { useState, useEffect, useCallback, useRef } from "react";
import { getCurrentPosition, ACCURACY_WARN_M } from "../utils/geolocate";
import CoordPicker from "../components/map/CoordPicker";

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
  available:       "bg-[#e6faf4] text-[#037a5c] border-[#04cd99]/40",
  charging:        "bg-[#eef3ff] text-brand-action border-brand-blue/40",
  preparing:       "bg-brand-cream text-brand-amber border-brand-yellow/60",
  finishing:       "bg-brand-cream text-brand-amber border-brand-yellow/60",
  offline:         "bg-slate-100 text-ink-muted border-slate-200",
  faulted:         "bg-rose-50 text-rose-600 border-rose-300",
  paid:            "bg-[#e6faf4] text-[#037a5c] border-[#04cd99]/40",
  pending_payment: "bg-brand-cream text-brand-amber border-brand-yellow/60",
  expired:         "bg-slate-100 text-ink-muted border-slate-200",
  cancelled:       "bg-slate-100 text-ink-muted border-slate-200",
  failed:          "bg-rose-50 text-rose-600 border-rose-300",
};

function Badge({ status, label }) {
  const cls = STATUS_COLORS[String(status || "").toLowerCase()]
    || "bg-slate-100 text-ink-muted border-slate-200";
  return (
    <span className={`inline-block rounded-md border px-1.5 py-0.5 text-xs font-medium ${cls}`}>
      {label || status || "—"}
    </span>
  );
}

// ── Shared primitives ─────────────────────────────────────────────────────────

function Th({ children, className = "" }) {
  return (
    <th className={`px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-ink-muted whitespace-nowrap ${className}`}>
      {children}
    </th>
  );
}
function Td({ children, className = "" }) {
  return <td className={`px-3 py-2 text-sm text-ink-soft align-top ${className}`}>{children}</td>;
}
function SectionHead({ children }) {
  return <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-muted mb-3">{children}</h2>;
}

// ── Action button ─────────────────────────────────────────────────────────────

function ActionBtn({ onClick, busy, label, busyLabel, color = "slate", title }) {
  const colors = {
    slate:   "border-brand-line bg-white text-ink-soft hover:bg-brand-panel",
    blue:    "border-brand-blue/40 bg-[#eef3ff] text-brand-action hover:bg-[#dde8ff]",
    rose:    "border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100",
    amber:   "border-brand-yellow/60 bg-brand-cream text-brand-amber hover:bg-[#ffedc2]",
    emerald: "border-[#04cd99]/40 bg-[#e6faf4] text-[#037a5c] hover:bg-[#d2f5ea]",
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
            ? "border-[#04cd99]/40 bg-[#e6faf4] text-[#037a5c]"
            : "border-rose-200 bg-rose-50 text-rose-700"
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
    <div className="min-h-screen flex items-center justify-center p-6">
      <div className="w-full max-w-sm bg-white border border-brand-line rounded-2xl p-8 shadow-card">
        <div className="text-center mb-6">
          <div className="text-2xl font-bold text-ink">Admin</div>
          <div className="text-sm text-ink-soft mt-1">Energiafelhő Kft.</div>
        </div>
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="block text-xs text-ink-soft mb-1.5">Felhasználónév</label>
            <input
              className="field"
              value={user} onChange={e => setUser(e.target.value)}
              autoFocus autoComplete="username"
            />
          </div>
          <div>
            <label className="block text-xs text-ink-soft mb-1.5">Jelszó</label>
            <input
              type="password"
              className="field"
              value={pass} onChange={e => setPass(e.target.value)}
              autoComplete="current-password"
            />
          </div>
          {err && <div className="text-sm text-rose-600">{err}</div>}
          <button
            type="submit" disabled={busy}
            className="w-full rounded-xl bg-brand-action hover:bg-[#2451bd] text-white font-semibold py-2.5 text-sm transition disabled:opacity-50"
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
    blue:    "border-brand-blue/40 bg-[#eef3ff]",
    emerald: "border-[#04cd99]/40 bg-[#e6faf4]",
    amber:   "border-brand-yellow/60 bg-brand-cream",
    rose:    "border-rose-200 bg-rose-50",
    slate:   "border-brand-line bg-white",
  };
  return (
    <div className={`rounded-2xl border p-4 ${accents[accent] || accents.slate}`}>
      <div className="text-xs text-ink-soft mb-1">{label}</div>
      <div className={`text-2xl font-semibold tabular-nums ${alert ? "text-rose-600" : "text-ink"}`}>
        {value ?? "—"}
      </div>
      {sub && <div className="text-xs text-ink-muted mt-0.5">{sub}</div>}
    </div>
  );
}

function OverviewTab({ stats, sessions }) {
  if (!stats) return <div className="text-ink-muted text-sm py-8 text-center">Betöltés…</div>;
  const activeSessions = sessions.filter(s => s.is_active);
  const missingInvoices = stats.alerts?.missing_invoices || 0;

  return (
    <div className="space-y-8">
      {missingInvoices > 0 && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 flex items-center gap-3">
          <span className="text-rose-700 font-semibold text-sm">⚠ {missingInvoices} befejezett session-ból hiányzik a számla</span>
          <span className="text-xs text-rose-600/80">Ellenőrizd a Sessionök tabon</span>
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
            <div key={st} className="flex items-center gap-2 rounded-xl border border-brand-line bg-white px-3 py-2">
              <Badge status={st} label={st} />
              <span className="text-ink font-semibold text-sm">{cnt}</span>
            </div>
          ))}
        </div>
      </div>

      {activeSessions.length > 0 && (
        <div>
          <SectionHead>Aktív sessionök ({activeSessions.length})</SectionHead>
          <div className="overflow-x-auto rounded-xl border border-brand-line">
            <table className="w-full">
              <thead className="bg-brand-panel">
                <tr><Th>#</Th><Th>Töltő</Th><Th>Email</Th><Th>Kezdés</Th><Th>Időtartam</Th><Th>Energia</Th><Th>Díj</Th></tr>
              </thead>
              <tbody className="divide-y divide-brand-line">
                {activeSessions.map(s => (
                  <tr key={s.id} className="hover:bg-brand-panel">
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

const CONNECTOR_TYPES = ["Type 2", "CCS2", "CHAdeMO", "Type 1", "Schuko"];

const MISSING_LABELS = {
  location: "helyszín",
  location_name: "helyszín neve",
  coordinates: "koordináta",
  connector_type: "csatlakozó típus",
  max_power_kw: "teljesítmény",
};

function Field({ label, hint, children }) {
  return (
    <label className="block">
      <div className="label mb-1">{label}</div>
      {children}
      {hint && <div className="text-xs text-ink-muted mt-1">{hint}</div>}
    </label>
  );
}

const INPUT_CLS =
  "field";

function ChargerConfigModal({ cp, busy, onClose, onSave }) {
  const [form, setForm] = useState({
    location_name: cp.location_name || "",
    address_text: cp.address_text || "",
    latitude: cp.latitude ?? "",
    longitude: cp.longitude ?? "",
    connector_type: cp.connector_type || "",
    max_power_kw: cp.max_power_kw ?? "",
  });

  const set = (k) => (e) => setForm(f => ({ ...f, [k]: e.target.value }));

  // Telepítéskor a szerelő a töltő mellett áll a telefonjával – innen a koordináta.
  const [geoBusy, setGeoBusy] = useState(false);
  const [geoErr, setGeoErr] = useState("");
  const [geoAccuracy, setGeoAccuracy] = useState(null);

  async function fillFromPhone() {
    setGeoBusy(true);
    setGeoErr("");
    setGeoAccuracy(null);
    try {
      const pos = await getCurrentPosition();
      setForm(f => ({
        ...f,
        latitude: pos.latitude.toFixed(6),
        longitude: pos.longitude.toFixed(6),
      }));
      setGeoAccuracy(pos.accuracy);
    } catch (e) {
      setGeoErr(e.message);
    } finally {
      setGeoBusy(false);
    }
  }

  function buildPatch() {
    const num = (v) => (v === "" || v === null ? null : Number(v));
    return {
      location_name: form.location_name.trim(),
      address_text: form.address_text.trim(),
      latitude: num(form.latitude),
      longitude: num(form.longitude),
      connector_type: form.connector_type,
      max_power_kw: num(form.max_power_kw),
    };
  }

  const coordsBad =
    (form.latitude !== "" && !Number.isFinite(Number(form.latitude))) ||
    (form.longitude !== "" && !Number.isFinite(Number(form.longitude)));

  // Az ellenőrző térkép csak akkor jelenik meg, ha van értelmes pont.
  const pickerLat = Number(form.latitude);
  const pickerLng = Number(form.longitude);
  const showPicker =
    form.latitude !== "" && form.longitude !== "" && !coordsBad &&
    Number.isFinite(pickerLat) && Number.isFinite(pickerLng);

  // Térképi igazítás után a mezők is a marker helyét mutatják, és a
  // pontosság-visszajelzés eltűnik – az már nem a mért pozícióra igaz.
  const pickFromMap = (lat, lng) => {
    setForm(f => ({ ...f, latitude: lat.toFixed(6), longitude: lng.toFixed(6) }));
    setGeoAccuracy(null);
  };

  return (
    <div className="fixed inset-0 bg-ink/40 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div
        className="bg-white border border-brand-line rounded-2xl shadow-card max-w-lg w-full max-h-[90vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        <div className="px-5 py-4 border-b border-brand-line flex items-center justify-between">
          <div>
            <div className="font-semibold text-ink">Töltő beállítása</div>
            <div className="font-mono text-xs text-ink-soft">{cp.ocpp_id}</div>
          </div>
          <button onClick={onClose} className="text-ink-soft hover:text-ink text-xl leading-none">×</button>
        </div>

        <div className="overflow-auto p-5 space-y-4 flex-1">
          {!cp.is_published && (cp.missing_fields || []).length > 0 && (
            <div className="rounded-lg border border-brand-yellow/60 bg-brand-cream px-3 py-2 text-xs text-brand-amber">
              Publikáláshoz hiányzik: {(cp.missing_fields || []).map(f => MISSING_LABELS[f] || f).join(", ")}
            </div>
          )}

          <Field label="Helyszín neve" hint="Ez jelenik meg a térképen és a töltő kártyáján.">
            <input className={INPUT_CLS} value={form.location_name} onChange={set("location_name")}
                   placeholder="pl. Vörösmarty tér – bal oszlop" />
          </Field>

          <Field label="Cím" hint="Formátum: 1051 Budapest, Vörösmarty tér 1. – így az OCPI is helyesen bontja szét.">
            <input className={INPUT_CLS} value={form.address_text} onChange={set("address_text")}
                   placeholder="1051 Budapest, Vörösmarty tér 1." />
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Szélesség (lat)">
              <input className={INPUT_CLS} value={form.latitude} onChange={set("latitude")}
                     inputMode="decimal" placeholder="47.49790" />
            </Field>
            <Field label="Hosszúság (lng)">
              <input className={INPUT_CLS} value={form.longitude} onChange={set("longitude")}
                     inputMode="decimal" placeholder="19.04020" />
            </Field>
          </div>
          <div className="-mt-2 space-y-2">
            <button
              type="button"
              onClick={fillFromPhone}
              disabled={geoBusy}
              className="flex w-full items-center justify-center gap-2 rounded-xl border border-brand-action bg-brand-action/5 px-3 py-2.5 text-sm font-semibold text-brand-action hover:bg-brand-action/10 disabled:opacity-60 transition"
            >
              <span className="text-base leading-none">{geoBusy ? "⏳" : "📍"}</span>
              {geoBusy ? "Helymeghatározás…" : "Kitöltés a telefon helyzetéből"}
            </button>

            {geoErr && (
              <div className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
                {geoErr}
              </div>
            )}

            {geoAccuracy != null && (
              geoAccuracy > ACCURACY_WARN_M ? (
                <div className="hint">
                  Beolvasva, de a pontosság csak <span className="font-bold">±{Math.round(geoAccuracy)} m</span> —
                  ennyi hibával a marker a szomszéd utcába is eshet. Menj ki a szabad égbolt alá, és mérj újra,
                  vagy írd be kézzel a koordinátát.
                </div>
              ) : (
                <div className="rounded-xl bg-[#e6faf4] px-3 py-2 text-xs text-[#037a5c]">
                  Beolvasva, pontosság ±{Math.round(geoAccuracy)} m. Mentés előtt érdemes ránézni a térképen.
                </div>
              )
            )}

            {showPicker && (
              <>
                <CoordPicker lat={pickerLat} lng={pickerLng} onPick={pickFromMap} />
                <div className="text-xs text-ink-muted">
                  Ezt a pontot látja a vásárló. Ha nem stimmel, húzd a markert a helyére, vagy kattints a
                  térképre.
                </div>
              </>
            )}

            <div className="text-xs text-ink-muted">
              A telefon helyzete a töltő mellett állva a legpontosabb. Kézzel is megadható: Google Mapsen jobb
              klikk a pontra → a koordináta másolható. Töltőnként külön pontot adj meg, különben a szomszédos
              oszlop markerével fedésbe kerül.
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Csatlakozó típusa">
              <select className={INPUT_CLS} value={form.connector_type} onChange={set("connector_type")}>
                <option value="">– válassz –</option>
                {CONNECTOR_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            </Field>
            <Field label="Max teljesítmény (kW)">
              <input className={INPUT_CLS} value={form.max_power_kw} onChange={set("max_power_kw")}
                     inputMode="decimal" placeholder="22" />
            </Field>
          </div>
          <div className="text-xs text-ink-muted -mt-2">
            Ebből számol az OCPI AC/DC-t és amperszámot a roaming partnereknek – ha üresen marad,
            a rendszer 22 kW-os Type 2-nek hirdetné meg.
          </div>
        </div>

        <div className="px-5 py-4 border-t border-brand-line flex flex-wrap gap-2 justify-end">
          <button
            onClick={onClose}
            className="rounded-lg border border-brand-line px-3 py-1.5 text-sm text-ink-soft hover:bg-brand-panel"
          >
            Mégse
          </button>
          <button
            onClick={() => onSave(buildPatch())}
            disabled={busy || coordsBad}
            className="rounded-lg bg-brand-action px-3 py-1.5 text-sm text-white hover:bg-[#2451bd] disabled:opacity-40"
          >
            {busy ? "Mentés…" : "Mentés"}
          </button>
          {!cp.is_published && (
            <button
              onClick={() => onSave(buildPatch(), { publish: true })}
              disabled={busy || coordsBad}
              className="rounded-lg border border-emerald-700/50 bg-emerald-900/30 px-3 py-1.5 text-sm text-emerald-200 hover:bg-emerald-900/60 disabled:opacity-40"
            >
              {busy ? "Mentés…" : "Mentés és publikálás"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function ChargersTab({ chargers, apiFetch, toast, onRefresh }) {
  const [resetBusy, setResetBusy] = useState(null);
  const [configOpen, setConfigOpen] = useState(null);
  const [configData, setConfigData] = useState(null);
  const [configLoading, setConfigLoading] = useState(false);
  const [testBusy, setTestBusy] = useState(null);
  const [editCp, setEditCp] = useState(null);
  const [saveBusy, setSaveBusy] = useState(false);
  const [publishBusy, setPublishBusy] = useState(null);
  const [deleteBusy, setDeleteBusy] = useState(null);

  const STARTABLE = ["available", "preparing", "finishing"];

  const pending = chargers.filter(cp => !cp.is_published);
  const live = chargers.filter(cp => cp.is_published);

  async function doTestCharge(cp) {
    const email = window.prompt(
      "Teszt töltés – ide megy a bizonylat/számla:",
      "szerviz@energiafelho.hu"
    );
    if (email === null) return; // mégse
    setTestBusy(cp.id);
    try {
      const res = await apiFetch(`/api/admin/charge-points/${cp.id}/test-charge`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          connector_id: 1,
          email: email.trim() || undefined,
          hold_amount_huf: 5000,
        }),
      });
      if (res.checkout_url) {
        toast(`Teszt fizetés megnyitva (intent #${res.intent_id})`, "ok");
        window.open(res.checkout_url, "_blank", "noopener");
      } else {
        toast("Nem érkezett checkout link", "err");
      }
    } catch (e) {
      toast(`Teszt töltés hiba: ${e.message}`, "err");
    } finally {
      setTestBusy(null);
    }
  }

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

  async function saveConfig(cp, patch, { publish = null } = {}) {
    const body = { ...patch };
    if (publish !== null) body.is_published = publish;
    setSaveBusy(true);
    try {
      await apiFetch(`/api/admin/charge-points/${cp.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      toast(
        publish === true ? `${cp.ocpp_id} publikálva – megjelent az éles appban`
        : publish === false ? `${cp.ocpp_id} visszavonva az éles appból`
        : `${cp.ocpp_id} beállításai mentve`,
        "ok"
      );
      setEditCp(null);
      onRefresh?.();
      return true;
    } catch (e) {
      const d = e.detail;
      const msg = d?.error === "incomplete_configuration"
        ? `Hiányzó adat: ${(d.missing_fields || []).map(f => MISSING_LABELS[f] || f).join(", ")}`
        : e.message;
      toast(`Mentés hiba: ${msg}`, "err");
      return false;
    } finally {
      setSaveBusy(false);
    }
  }

  async function doTogglePublish(cp) {
    if (cp.is_published && !window.confirm(
      `${cp.ocpp_id} visszavonása: eltűnik az éles appból és az OCPI-ból. Biztos?`
    )) return;
    setPublishBusy(cp.id);
    try {
      await saveConfig(cp, {}, { publish: !cp.is_published });
    } finally {
      setPublishBusy(null);
    }
  }

  async function doDelete(cp) {
    if (!window.confirm(
      `${cp.ocpp_id} törlése véglegesen. Csak előzmény nélküli (pl. elgépelt ID-val létrejött) töltőnél megy. Biztos?`
    )) return;
    setDeleteBusy(cp.id);
    try {
      await apiFetch(`/api/admin/charge-points/${cp.id}`, { method: "DELETE" });
      toast(`${cp.ocpp_id} törölve`, "ok");
      onRefresh?.();
    } catch (e) {
      const d = e.detail;
      const msg = d?.error === "charge_point_has_history"
        ? `Nem törölhető: ${d.sessions} session és ${d.intents} intent tartozik hozzá.`
        : e.message;
      toast(`Törlés hiba: ${msg}`, "err");
    } finally {
      setDeleteBusy(null);
    }
  }

  function ChargerRow({ cp }) {
    return (
      <tr className="hover:bg-brand-panel">
        <Td>{cp.id}</Td>
        <Td><span className="font-mono text-xs text-ink">{cp.ocpp_id}</span></Td>
        <Td><Badge status={cp.status} label={cp.status} /></Td>
        <Td>
          <div>{cp.location_name || <span className="text-brand-amber">nincs helyszín</span>}</div>
          {cp.address_text && <div className="text-xs text-ink-muted">{cp.address_text}</div>}
          {cp.latitude != null && cp.longitude != null && (
            <div className="text-xs text-ink-muted font-mono">
              {cp.latitude.toFixed(5)}, {cp.longitude.toFixed(5)}
            </div>
          )}
        </Td>
        <Td>{cp.connector_type || <span className="text-brand-amber">—</span>}</Td>
        <Td>{cp.max_power_kw ? `${cp.max_power_kw} kW` : <span className="text-brand-amber">—</span>}</Td>
        <Td>{[cp.vendor, cp.model].filter(Boolean).join(" ") || "—"}</Td>
        <Td className="font-mono text-xs">{cp.firmware_version || "—"}</Td>
        <Td className="font-mono text-xs">{cp.serial_number || "—"}</Td>
        <Td className="whitespace-nowrap text-xs">{cp.last_seen_at ? `${timeAgo(cp.last_seen_at)} ezelőtt` : "—"}</Td>
        <Td className="whitespace-nowrap text-xs">{fmtDate(cp.created_at)}</Td>
        <Td>
          <div className="flex gap-1.5 flex-wrap">
            <ActionBtn
              label="Beállítás" color="blue"
              onClick={() => setEditCp(cp)}
              title="Helyszín, koordináta, csatlakozó, teljesítmény"
            />
            {cp.is_published ? (
              <ActionBtn
                label="Visszavonás" color="amber"
                busy={publishBusy === cp.id}
                onClick={() => doTogglePublish(cp)}
                title="Elrejtés az éles appból és az OCPI-ból"
              />
            ) : (
              <ActionBtn
                label="Publikálás" color="emerald"
                busy={publishBusy === cp.id}
                onClick={() => doTogglePublish(cp)}
                title={cp.publishable ? "Megjelenítés az éles appban" : "Előbb töltsd ki a hiányzó adatokat"}
              />
            )}
            {STARTABLE.includes(String(cp.status || "").toLowerCase()) && (
              <ActionBtn
                label="Teszt töltés" color="emerald"
                busy={testBusy === cp.id}
                onClick={() => doTestCharge(cp)}
                title="Admin teszt töltés a teljes Stripe-folyamaton (5 Ft/kWh, ~200 Ft capture). Publikálás előtt is megy."
              />
            )}
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
            {!cp.is_published && (
              <ActionBtn
                label="Törlés" color="rose"
                busy={deleteBusy === cp.id}
                onClick={() => doDelete(cp)}
                title="Téves/elgépelt ID-val létrejött sor törlése"
              />
            )}
          </div>
        </Td>
      </tr>
    );
  }

  function ChargerTable({ rows }) {
    return (
      <div className="overflow-x-auto rounded-xl border border-brand-line">
        <table className="w-full">
          <thead className="bg-brand-panel">
            <tr>
              <Th>ID</Th><Th>OCPP ID</Th><Th>Státusz</Th><Th>Helyszín</Th>
              <Th>Csatl.</Th><Th>Max kW</Th><Th>Model</Th><Th>Firmware</Th>
              <Th>Sorozatszám</Th><Th>Utoljára látva</Th><Th>Felvéve</Th><Th>Műveletek</Th>
            </tr>
          </thead>
          <tbody className="divide-y divide-brand-line">
            {rows.map(cp => <ChargerRow key={cp.id} cp={cp} />)}
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {pending.length > 0 && (
        <div className="rounded-xl border border-brand-yellow/60 bg-brand-cream p-4">
          <SectionHead>⚠ Konfigurálásra vár ({pending.length})</SectionHead>
          <p className="text-xs text-ink-soft mb-3 max-w-3xl">
            Ezek a töltők felcsatlakoztak, de <span className="text-brand-amber">még nem látszanak</span> az
            éles appban és a roaming partnereknél. Add meg a helyszínt, a koordinátát, a csatlakozó típusát
            és a teljesítményt, teszteld a „Teszt töltés" gombbal, majd publikáld.
          </p>
          <ChargerTable rows={pending} />
        </div>
      )}

      <div>
        <SectionHead>Éles töltők ({live.length})</SectionHead>
        {live.length === 0 ? (
          <div className="rounded-xl border border-brand-line p-4 text-sm text-ink-muted">
            Nincs publikált töltő – az éles app üres térképet mutat.
          </div>
        ) : (
          <ChargerTable rows={live} />
        )}
      </div>

      {editCp && (
        <ChargerConfigModal
          cp={editCp}
          busy={saveBusy}
          onClose={() => setEditCp(null)}
          onSave={(patch, opts) => saveConfig(editCp, patch, opts)}
        />
      )}

      {/* GetConfig modal */}
      {configOpen && (
        <div className="fixed inset-0 bg-ink/40 z-50 flex items-center justify-center p-4" onClick={() => setConfigOpen(null)}>
          <div className="bg-white border border-brand-line rounded-2xl shadow-card max-w-2xl w-full max-h-[80vh] flex flex-col" onClick={e => e.stopPropagation()}>
            <div className="px-5 py-4 border-b border-brand-line flex items-center justify-between">
              <div className="font-semibold text-ink">GetConfiguration – {configOpen}</div>
              <button onClick={() => setConfigOpen(null)} className="text-ink-soft hover:text-ink text-xl leading-none">×</button>
            </div>
            <div className="overflow-auto p-4 flex-1">
              {configLoading ? (
                <div className="text-ink-soft text-sm">Lekérdezés…</div>
              ) : configData?.error ? (
                <div className="text-rose-600 text-sm">{configData.error}</div>
              ) : configData?.configurationKey ? (
                <table className="w-full text-xs">
                  <thead><tr><Th>Key</Th><Th>Value</Th><Th>Readonly</Th></tr></thead>
                  <tbody className="divide-y divide-brand-line">
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
                <pre className="text-xs text-ink-soft whitespace-pre-wrap">{JSON.stringify(configData, null, 2)}</pre>
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
    <tr className="bg-brand-panel/60">
      <td colSpan={10} className="px-4 py-4">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs mb-4">
          <div>
            <div className="text-ink-muted mb-0.5">OCPP Transaction ID</div>
            <div className="font-mono text-ink-soft">{s.ocpp_transaction_id || "—"}</div>
          </div>
          <div>
            <div className="text-ink-muted mb-0.5">Helyszín</div>
            <div className="text-ink-soft">{s.charge_point_location || "—"}</div>
          </div>
          <div>
            <div className="text-ink-muted mb-0.5">Mérő start / stop</div>
            <div className="font-mono text-ink-soft">
              {s.meter_start_wh != null ? `${s.meter_start_wh} Wh` : "—"} → {s.meter_stop_wh != null ? `${s.meter_stop_wh} Wh` : "—"}
            </div>
          </div>
          <div>
            <div className="text-ink-muted mb-0.5">Befejezve</div>
            <div className="text-ink-soft">{fmtDt(s.finished_at)}</div>
          </div>
          {s.invoice_number && (
            <div>
              <div className="text-ink-muted mb-0.5">Számlaszám</div>
              <div className="font-mono text-[#037a5c]">{s.invoice_number}</div>
            </div>
          )}
          {missingInvoice && (
            <div>
              <div className="text-ink-muted mb-0.5">Számla</div>
              <span className="inline-block rounded border border-rose-200 bg-rose-50 px-1.5 py-0.5 text-rose-700 text-xs">
                Hiányzik!
              </span>
            </div>
          )}
          {s.intent && (
            <>
              <div>
                <div className="text-ink-muted mb-0.5">Fizetési státusz</div>
                <Badge status={s.intent.status} label={s.intent.status} />
              </div>
              <div>
                <div className="text-ink-muted mb-0.5">Zárolás</div>
                <div className="text-ink-soft">{fmtHuf(s.intent.hold_amount_huf)}</div>
              </div>
              <div>
                <div className="text-ink-muted mb-0.5">Számlázás</div>
                <div className="text-ink-soft leading-relaxed">
                  {s.intent.billing_name}
                  {s.intent.billing_company && <><br />{s.intent.billing_company}</>}
                  <br />{[s.intent.billing_zip, s.intent.billing_city].filter(Boolean).join(" ")}, {s.intent.billing_country}
                  <br />{s.intent.billing_type === "business" ? "Céges" : "Magánszemély"}
                </div>
              </div>
              {s.intent.stripe_payment_intent_id && (
                <div>
                  <div className="text-ink-muted mb-0.5">Stripe PI</div>
                  <div className="font-mono text-ink-soft text-xs break-all">{s.intent.stripe_payment_intent_id}</div>
                </div>
              )}
              {s.intent.last_error && (
                <div className="col-span-2">
                  <div className="text-ink-muted mb-0.5">Utolsó hiba</div>
                  <div className="text-rose-600">{s.intent.last_error}</div>
                </div>
              )}
            </>
          )}
        </div>

        {/* Műveletek */}
        <div className="border-t border-brand-line pt-3">
          <div className="text-xs text-ink-muted mb-2">Műveletek</div>
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
                <div className="flex items-center gap-2 rounded-lg border border-rose-200 bg-rose-50 px-2.5 py-1">
                  <span className="text-xs text-rose-700">Biztosan lezárod OCPP nélkül?</span>
                  <ActionBtn color="rose" label="Igen" busy={busy === "forceclose"}
                    onClick={() => { setConfirmForceClose(false); doAction("forceclose", `/api/admin/sessions/${s.id}/force-close`, "POST", {
                      ok: "Session lezárva (DB), Stripe settle futott",
                      err: e => `Force close hiba: ${e.message}`,
                    }); }}
                  />
                  <button className="text-xs text-ink-soft hover:text-ink" onClick={() => setConfirmForceClose(false)}>Mégse</button>
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

function SessionsTab({ sessions, chargers, apiFetch, toast, onRefresh, highlightMissing }) {
  const [showAll, setShowAll] = useState(false);
  const [expandedId, setExpandedId] = useState(null);
  const [onlyMissing, setOnlyMissing] = useState(highlightMissing);
  const [cpFilter, setCpFilter] = useState("");

  const filtered = cpFilter ? sessions.filter(s => s.charge_point_ocpp_id === cpFilter) : sessions;
  const active = filtered.filter(s => s.is_active);
  let finished = filtered.filter(s => !s.is_active);
  if (onlyMissing) {
    finished = finished.filter(s => s.anonymous_email && s.intent && !s.invoice_number);
  }
  const displayed = showAll ? finished : finished.slice(0, 30);

  const cols = (
    <thead className="bg-brand-panel">
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
          className={`cursor-pointer transition ${expanded ? "bg-brand-panel" : "hover:bg-brand-panel"} ${missingInvoice ? "border-l-2 border-l-rose-600/50" : ""}`}
          onClick={() => setExpandedId(expanded ? null : s.id)}
        >
          <Td>
            <span className="font-mono text-xs">{s.id}</span>
            {s.is_active && <span className="ml-1.5 inline-block w-1.5 h-1.5 rounded-full bg-brand-green animate-pulse align-middle" />}
          </Td>
          <Td><span className="font-mono text-xs">{s.charge_point_ocpp_id}</span></Td>
          <Td>
            <div className="text-xs">{s.anonymous_email || "—"}</div>
            {s.intent?.billing_name && <div className="text-xs text-ink-muted">{s.intent.billing_name}</div>}
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
              ? <span className="font-mono text-xs text-[#037a5c]">{s.invoice_number}</span>
              : missingInvoice
                ? <span className="text-rose-600 text-xs font-semibold">Hiányzik!</span>
                : <span className="text-ink-muted text-xs">—</span>
            }
          </Td>
          <Td><span className="text-ink-muted text-xs">{expanded ? "▲" : "▼"}</span></Td>
        </tr>
        {expanded && (
          <SessionDetail key={`${s.id}-detail`} s={s} apiFetch={apiFetch} toast={toast} onRefresh={onRefresh} />
        )}
      </>
    );
  }

  const cpOptions = [...new Set(sessions.map(s => s.charge_point_ocpp_id).filter(Boolean))].sort();

  return (
    <div className="space-y-8">
      {/* Töltő szűrő */}
      <div className="flex items-center gap-3">
        <label className="text-xs text-ink-soft shrink-0">Töltő:</label>
        <select
          value={cpFilter} onChange={e => { setCpFilter(e.target.value); setShowAll(false); setExpandedId(null); }}
          className="rounded-lg border border-brand-line bg-white px-3 py-1.5 text-sm text-ink outline-none focus:ring-2 focus:ring-brand-action/30"
        >
          <option value="">Összes töltő</option>
          {cpOptions.map(id => <option key={id} value={id}>{id}</option>)}
        </select>
        {cpFilter && (
          <button onClick={() => setCpFilter("")} className="text-xs text-ink-muted hover:text-ink">× törlés</button>
        )}
      </div>

      <div>
        <SectionHead>Aktív sessionök ({active.length})</SectionHead>
        {active.length === 0 ? (
          <div className="text-ink-muted text-sm py-4">Nincs aktív session.</div>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-brand-line">
            <table className="w-full">
              {cols}
              <tbody className="divide-y divide-brand-line">
                {active.map(s => <SessionRow key={s.id} s={s} />)}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div>
        <div className="flex items-center gap-4 mb-3">
          <SectionHead>Befejezett sessionök ({finished.length})</SectionHead>
          <label className="flex items-center gap-1.5 text-xs text-ink-soft cursor-pointer -mt-3">
            <input
              type="checkbox" checked={onlyMissing}
              onChange={e => { setOnlyMissing(e.target.checked); setShowAll(false); }}
              className="accent-rose-500"
            />
            Csak hiányzó számlás
          </label>
        </div>
        <div className="overflow-x-auto rounded-xl border border-brand-line">
          <table className="w-full">
            {cols}
            <tbody className="divide-y divide-brand-line">
              {displayed.map(s => <SessionRow key={s.id} s={s} />)}
            </tbody>
          </table>
        </div>
        {finished.length > 30 && (
          <button className="mt-2 text-xs text-brand-action hover:underline"
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
  const [cpFilter, setCpFilter] = useState("");

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

  const cpOptions = [...new Set(intents.map(i => i.charge_point_ocpp_id).filter(Boolean))].sort();
  const displayed = cpFilter ? intents.filter(i => i.charge_point_ocpp_id === cpFilter) : intents;

  return (
    <div>
      <div className="flex items-center gap-3 mb-4">
        <SectionHead>Charging intentek ({displayed.length})</SectionHead>
        <div className="flex items-center gap-2 -mt-3">
          <label className="text-xs text-ink-soft shrink-0">Töltő:</label>
          <select
            value={cpFilter} onChange={e => { setCpFilter(e.target.value); setExpandedId(null); }}
            className="rounded-lg border border-brand-line bg-white px-3 py-1.5 text-sm text-ink outline-none focus:ring-2 focus:ring-brand-action/30"
          >
            <option value="">Összes töltő</option>
            {cpOptions.map(id => <option key={id} value={id}>{id}</option>)}
          </select>
          {cpFilter && (
            <button onClick={() => setCpFilter("")} className="text-xs text-ink-muted hover:text-ink">× törlés</button>
          )}
        </div>
      </div>
      <div className="overflow-x-auto rounded-xl border border-brand-line">
        <table className="w-full">
          <thead className="bg-brand-panel">
            <tr>
              <Th>#</Th><Th>Töltő</Th><Th>Email</Th><Th>Számlázási név</Th>
              <Th>Státusz</Th><Th>Zárolás</Th><Th>Típus</Th><Th>Lejár</Th><Th>Létrehozva</Th><Th></Th>
            </tr>
          </thead>
          <tbody className="divide-y divide-brand-line">
            {displayed.map(i => {
              const expanded = expandedId === i.id;
              const canRefund = i.stripe_payment_intent_id && ["paid", "pending_payment"].includes(i.status);
              return (
                <>
                  <tr
                    key={i.id}
                    className={`cursor-pointer transition ${expanded ? "bg-brand-panel" : "hover:bg-brand-panel"}`}
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
                    <tr key={`${i.id}-exp`} className="bg-brand-panel/60">
                      <td colSpan={10} className="px-4 py-3">
                        <div className="grid grid-cols-2 md:grid-cols-3 gap-4 text-xs">
                          <div>
                            <div className="text-ink-muted mb-0.5">Cím</div>
                            <div className="text-ink-soft">
                              {[i.billing_zip, i.billing_city, i.billing_street, i.billing_country].filter(Boolean).join(", ")}
                            </div>
                          </div>
                          {i.billing_company && (
                            <div>
                              <div className="text-ink-muted mb-0.5">Cégnév</div>
                              <div className="text-ink-soft">{i.billing_company}</div>
                            </div>
                          )}
                          {i.billing_tax_number && (
                            <div>
                              <div className="text-ink-muted mb-0.5">Adószám</div>
                              <div className="font-mono text-ink-soft">{i.billing_tax_number}</div>
                            </div>
                          )}
                          {i.stripe_payment_intent_id && (
                            <div>
                              <div className="text-ink-muted mb-0.5">Stripe PI</div>
                              <div className="font-mono text-ink-soft break-all">{i.stripe_payment_intent_id}</div>
                            </div>
                          )}
                          {i.payment_provider_ref && (
                            <div>
                              <div className="text-ink-muted mb-0.5">Stripe Checkout Session</div>
                              <div className="font-mono text-ink-soft break-all">{i.payment_provider_ref}</div>
                            </div>
                          )}
                          {i.cancel_reason && (
                            <div>
                              <div className="text-ink-muted mb-0.5">Törlés oka</div>
                              <div className="text-ink-soft">{i.cancel_reason}</div>
                            </div>
                          )}
                          {i.last_error && (
                            <div className="col-span-2">
                              <div className="text-ink-muted mb-0.5">Utolsó hiba</div>
                              <div className="text-rose-600">{i.last_error}</div>
                            </div>
                          )}
                          <div>
                            <div className="text-ink-muted mb-0.5">Frissítve</div>
                            <div className="text-ink-soft">{fmtDt(i.updated_at)}</div>
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
          className="flex-1 field"
        />
        <button type="submit" disabled={loading || !q.trim()}
          className="rounded-xl bg-brand-action hover:bg-[#2451bd] text-white px-5 py-2.5 text-sm font-semibold disabled:opacity-40 transition">
          {loading ? "…" : "Keresés"}
        </button>
      </form>

      {results && (
        <div className="space-y-6">
          <div className="text-xs text-ink-soft">{total} találat a(z) „{results.query}" keresésre</div>

          {results.charge_points.length > 0 && (
            <div>
              <SectionHead>Töltők ({results.charge_points.length})</SectionHead>
              <div className="overflow-x-auto rounded-xl border border-brand-line">
                <table className="w-full">
                  <thead className="bg-brand-panel">
                    <tr><Th>ID</Th><Th>OCPP ID</Th><Th>Státusz</Th><Th>Helyszín</Th><Th>Utoljára látva</Th></tr>
                  </thead>
                  <tbody className="divide-y divide-brand-line">
                    {results.charge_points.map(cp => (
                      <tr key={cp.id} className="hover:bg-brand-panel">
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
                    <div key={s.id} className={`rounded-xl border p-4 text-sm ${missingInvoice ? "border-rose-200 bg-rose-50" : "border-brand-line bg-white"}`}>
                      <div className="flex items-start justify-between gap-4 mb-2">
                        <div className="flex items-center gap-3">
                          <span className="font-mono text-ink-soft text-xs">#{s.id}</span>
                          <span className="font-mono text-xs text-ink-soft">{s.charge_point_ocpp_id}</span>
                          {s.is_active ? <Badge status="charging" label="aktív" /> : <Badge status="available" label="kész" />}
                          {missingInvoice && <span className="text-rose-600 text-xs font-semibold">Számla hiányzik!</span>}
                        </div>
                        {s.invoice_number && <span className="font-mono text-xs text-[#037a5c]">{s.invoice_number}</span>}
                      </div>
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs text-ink-soft">
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
                  <div key={i.id} className="rounded-xl border border-brand-line bg-white p-4 text-sm">
                    <div className="flex items-center gap-3 mb-1">
                      <span className="font-mono text-ink-soft text-xs">#{i.id}</span>
                      <Badge status={i.status} label={i.status} />
                      <span className="text-xs text-ink-soft">{i.anonymous_email}</span>
                      <span className="text-xs text-ink-muted">{fmtHuf(i.hold_amount_huf)} zárolás</span>
                    </div>
                    <div className="text-xs text-ink-soft">{i.billing_name} · {fmtDt(i.created_at)}</div>
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
            <div className="text-ink-muted text-sm text-center py-8">Nincs találat.</div>
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
      const err = new Error(msg);
      err.detail = data?.detail;   // strukturált hiba (pl. missing_fields) a hívónak
      err.status = res.status;
      throw err;
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
    <div className="min-h-screen">
      {/* Header */}
      <div className="border-b border-brand-line bg-white/90 sticky top-0 z-10">
        <div className="mx-auto max-w-screen-2xl px-6 py-3 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <span className="font-bold text-ink">Admin Dashboard</span>
            {loading && (
              <div className="flex gap-1">
                {[0,1,2].map(i => (
                  <div key={i} className="w-1 h-1 rounded-full bg-brand-action animate-bounce"
                    style={{ animationDelay: `${i * 0.15}s` }} />
                ))}
              </div>
            )}
            {lastUpdated && !loading && (
              <span className="text-xs text-ink-muted">
                {lastUpdated.toLocaleTimeString("hu-HU")}
              </span>
            )}
            {missingInvoices > 0 && (
              <button
                onClick={() => setTab("sessions")}
                className="rounded-lg border border-rose-200 bg-rose-50 px-2 py-0.5 text-xs text-rose-700 hover:bg-rose-100"
              >
                ⚠ {missingInvoices} hiányzó számla
              </button>
            )}
          </div>
          <div className="flex items-center gap-3">
            <button onClick={() => setTab("search")} className="text-xs text-brand-action hover:underline">Keresés</button>
            <button onClick={refresh} className="text-xs text-ink-soft hover:text-ink">Frissít</button>
            <button onClick={() => { sessionStorage.removeItem("admin_token"); setToken(""); }}
              className="text-xs text-ink-muted hover:text-ink">Kilépés</button>
          </div>
        </div>
        <div className="mx-auto max-w-screen-2xl px-6">
          <div className="flex gap-0 border-t border-brand-line">
            {TABS.map(t => (
              <button key={t.id} onClick={() => setTab(t.id)}
                className={[
                  "px-4 py-2.5 text-sm font-medium border-b-2 transition -mb-px",
                  tab === t.id
                    ? "border-brand-action text-brand-action"
                    : "border-transparent text-ink-soft hover:text-ink",
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
        {tab === "chargers" && (
          <ChargersTab chargers={chargers} apiFetch={apiFetch} toast={toast} onRefresh={refresh} />
        )}
        {tab === "sessions" && (
          <SessionsTab
            sessions={sessions} chargers={chargers} apiFetch={apiFetch} toast={toast} onRefresh={refresh}
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
