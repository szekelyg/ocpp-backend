import { useEffect, useMemo, useState } from "react";
import StatusBadge from "../ui/StatusBadge";
import { placeLines, timeAgo } from "../../utils/format";
import PayModal from "../ui/PayModal";

const STARTABLE = new Set(["available", "preparing", "finishing"]);

function isStartable(status) {
  return STARTABLE.has(String(status || "").toLowerCase());
}

function isCarConnected(status) {
  return ["preparing", "finishing"].includes(String(status || "").toLowerCase());
}

const HOLD_OPTIONS = [
  { value: 5000,  label: "5 000 Ft" },
  { value: 15000, label: "15 000 Ft" },
  { value: 25000, label: "25 000 Ft" },
];

function Field({ label, children }) {
  return (
    <div>
      <label className="block text-xs text-slate-400 mb-1.5">{label}</label>
      {children}
    </div>
  );
}

const inputCls = "w-full rounded-xl border border-slate-700 bg-slate-800 px-3 py-2.5 text-slate-100 outline-none focus:ring-2 focus:ring-blue-500/40 text-sm disabled:opacity-50";

export default function SelectedChargerCard({ cp, onModalChange, autoOpenModal, onAutoOpenDone, compact = false }) {
  const [email, setEmail] = useState("");
  const [holdAmount, setHoldAmount] = useState(5000);

  // Számlázás
  const [billingType, setBillingType] = useState("personal");
  const [billingName, setBillingName] = useState("");
  const [billingStreet, setBillingStreet] = useState("");
  const [billingZip, setBillingZip] = useState("");
  const [billingCity, setBillingCity] = useState("");
  const [billingCountry, setBillingCountry] = useState("HU");
  const [billingCompany, setBillingCompany] = useState("");
  const [billingTaxNumber, setBillingTaxNumber] = useState("");

  const [showPay, setShowPay] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [minAck, setMinAck] = useState(false);

  const lines = useMemo(() => (cp ? placeLines(cp) : ["", ""]), [cp]);
  const canStart = cp && isStartable(cp.status) && !busy;

  useEffect(() => {
    if (!autoOpenModal || !cp) return;
    onAutoOpenDone?.();
    if (!isStartable(cp.status)) return;
    setErr("");
    setShowPay(true);
    onModalChange?.(true);
  }, [autoOpenModal, cp]);

  if (!cp) {
    return (
      <div className="text-slate-500 text-sm text-center py-4">
        Válasszon töltőt a listából vagy a térképről.
      </div>
    );
  }

  function openModal() {
    setErr("");
    setMinAck(false);
    setShowPay(true);
    onModalChange?.(true);
  }

  function closeModal() {
    if (busy) return;
    setShowPay(false);
    onModalChange?.(false);
  }

  async function startFlow() {
    setErr("");

    const e = (email || "").trim();
    if (!e) { setErr("Adja meg az email-címét."); return; }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e)) {
      setErr("Az email-cím formátuma nem megfelelő."); return;
    }
    if (!billingName.trim()) { setErr("Adja meg a számlázási nevet."); return; }
    if (!billingStreet.trim()) { setErr("Adja meg az utcát, házszámot."); return; }
    if (!billingZip.trim()) { setErr("Adja meg az irányítószámot."); return; }
    if (!billingCity.trim()) { setErr("Adja meg a várost."); return; }
    if (!billingCountry.trim()) { setErr("Adja meg az országot."); return; }
    if (billingType === "business") {
      if (!billingCompany.trim()) { setErr("Adja meg a cégnevet."); return; }
      if (!billingTaxNumber.trim()) { setErr("Adja meg az adószámot."); return; }
    }

    setBusy(true);
    try {
      const res = await fetch("/api/intents/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          charge_point_id: cp.id,
          connector_id: 1,
          email: e,
          hold_amount_huf: holdAmount,
          billing_type: billingType,
          billing_name: billingName.trim(),
          billing_street: billingStreet.trim(),
          billing_zip: billingZip.trim(),
          billing_city: billingCity.trim(),
          billing_country: billingCountry.trim().toUpperCase(),
          billing_company: billingType === "business" ? billingCompany.trim() : null,
          billing_tax_number: billingType === "business" ? billingTaxNumber.trim() : null,
        }),
      });

      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(
          typeof data?.detail === "string"
            ? data.detail
            : data?.detail?.error || data?.error || "Nem sikerült a fizetési folyamatot elindítani."
        );
      }

      const url = data?.checkout_url;
      if (!url) throw new Error("A szerver nem adott vissza fizetési linket.");
      if (!/^https:\/\//i.test(url)) throw new Error("Érvénytelen fizetési hivatkozás.");

      onModalChange?.(false);
      window.location.href = url;
    } catch (e) {
      setErr(e?.message || "Váratlan hiba történt. Kérjük próbálja újra.");
      setBusy(false);
    }
  }

  const statusStr = String(cp.status || "").toLowerCase();

  return (
    <div className="space-y-4">
      {/* Helyszín & státusz – compact módban elrejtve */}
      {!compact && (
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="font-semibold text-slate-100 leading-tight">
              {lines[0] || cp.ocpp_id || "—"}
            </div>
            {lines[1] && (
              <div className="text-sm text-slate-400 mt-0.5">{lines[1]}</div>
            )}
            <div className="text-xs text-slate-500 mt-1">
              Aktív: {timeAgo(cp.last_seen_at)}
            </div>
          </div>
          <StatusBadge status={cp.status} />
        </div>
      )}

      {/* Csatlakozó infó */}
      {(cp.connector_type || cp.max_power_kw) && (
        <div className="flex flex-wrap gap-2">
          {cp.connector_type && (
            <span className="inline-flex items-center gap-1 rounded-lg bg-slate-800 border border-slate-700 px-2.5 py-1 text-xs text-slate-300">
              <span className="text-slate-500">Csatlakozó</span>
              <span className="font-medium text-slate-100">{cp.connector_type}</span>
            </span>
          )}
          {cp.max_power_kw && (
            <span className="inline-flex items-center gap-1 rounded-lg bg-slate-800 border border-slate-700 px-2.5 py-1 text-xs text-slate-300">
              <span className="text-slate-500">Max. teljesítmény</span>
              <span className="font-medium text-slate-100">{cp.max_power_kw} kW</span>
            </span>
          )}
        </div>
      )}

      {/* Állapot tájékoztató */}
      {statusStr === "available" && (
        <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-3 text-xs text-slate-400">
          A töltő szabad és használatra kész. Fizetés után csatlakoztassa az autót.
        </div>
      )}
      {(statusStr === "preparing" || statusStr === "finishing") && (
        <div className="rounded-xl border border-amber-800/40 bg-amber-950/20 p-3 text-xs text-amber-300">
          Az autó már csatlakoztatva van — fizetés után a töltés azonnal elindul.
        </div>
      )}
      {statusStr === "charging" && (
        <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-3 text-xs text-slate-400">
          Ez a töltő jelenleg foglalt. Kérjük válasszon másik állomást.
        </div>
      )}
      {!["available", "preparing", "finishing", "charging"].includes(statusStr) && (
        <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-3 text-xs text-slate-400">
          A töltés indítása jelenleg nem lehetséges ezen az állomáson.
        </div>
      )}

      {/* Gombok */}
      <div className="flex flex-col gap-2 sm:flex-row">
        <button
          type="button"
          className="btn btnPrimary flex-1"
          disabled={!canStart}
          onClick={openModal}
        >
          {busy ? "Átirányítás…" : "Töltés indítása"}
        </button>

        {typeof cp.latitude === "number" && typeof cp.longitude === "number" && (
          <button
            type="button"
            className="btn btnGhost"
            onClick={() => window.open(`https://www.google.com/maps?q=${cp.latitude},${cp.longitude}`, "_blank")}
          >
            Útvonal
          </button>
        )}
      </div>

      {/* Fizetési modal */}
      <PayModal open={showPay} busy={busy} onClose={closeModal}>
        <div className="text-slate-100 font-semibold text-base">Töltés indítása</div>
        <div className="mt-1 text-slate-400 text-sm">
          {isCarConnected(cp.status)
            ? "Az autó már csatlakoztatva van — fizetés után a töltés azonnal elindul."
            : "Fizetés után csatlakoztassa az autót a töltőhöz."}
        </div>

        {/* Ár kiemelés */}
        {cp.price_huf_per_kwh > 0 && (
          <div className="mt-3 rounded-xl border border-emerald-700/40 bg-emerald-950/30 px-3 py-2.5 flex items-center justify-between">
            <div>
              <div className="text-xs text-emerald-400/70 mb-0.5">Töltési díj</div>
              <div className="text-lg font-bold text-emerald-300">
                {cp.price_huf_per_kwh.toLocaleString("hu-HU")} Ft<span className="text-sm font-normal text-emerald-400/70">/kWh</span>
              </div>
              <div className="text-xs text-emerald-400/50 mt-0.5">bruttó, 27% ÁFÁ-val</div>
            </div>
            {cp.min_charge_huf > 0 && (
              <div className="text-right">
                <div className="text-xs text-emerald-400/70 mb-0.5">Minimum terhelés</div>
                <div className="text-base font-semibold text-emerald-200">
                  {cp.min_charge_huf.toLocaleString("hu-HU")} Ft
                </div>
                <div className="text-xs text-emerald-400/50 mt-0.5">
                  ≈ {((cp.min_charge_huf / cp.price_huf_per_kwh)).toFixed(2).replace(".", ",")} kWh
                </div>
              </div>
            )}
          </div>
        )}

        {/* Hold magyarázat */}
        <div className="mt-3 rounded-xl border border-blue-800/40 bg-blue-950/30 px-3 py-2.5 space-y-1.5">
          <div className="text-xs font-semibold text-blue-300">Hogyan működik a fizetés?</div>
          <div className="text-xs text-blue-200/70">
            A kártyádon <span className="font-semibold text-blue-200">csak zárolásra kerül</span> a
            választott összeg — tényleges terhelés nem történik. A töltés végén kizárólag a
            felhasznált energia díja kerül levonásra; a maradék zárolás automatikusan felszabadul.
          </div>
          <div className="text-xs text-blue-200/50 pt-0.5 border-t border-blue-800/30">
            Ha nem töltöttél semmit, <span className="text-blue-200/70">0 Ft kerül levonásra</span>.
            {cp.min_charge_huf > 0 && (
              <> A bankkártyás feldolgozás minimuma <span className="text-blue-200/70 font-semibold">{cp.min_charge_huf.toLocaleString("hu-HU")} Ft</span> — nagyon rövid töltésnél is legalább ennyi kerül levonásra.</>
            )}
          </div>
        </div>

        {/* ── MINIMUM DÍJ ELFOGADÁSA ── */}
        {cp.min_charge_huf > 0 && (
          <label className="mt-4 flex items-start gap-3 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={minAck}
              onChange={(e) => setMinAck(e.target.checked)}
              disabled={busy}
              className="mt-0.5 h-4 w-4 rounded border-slate-600 bg-slate-800 accent-blue-500 cursor-pointer shrink-0"
            />
            <span className="text-xs text-slate-300 leading-relaxed">
              Tudomásul veszem, hogy a bankkártyás feldolgozás minimuma{" "}
              <span className="font-semibold text-white">
                {cp.min_charge_huf.toLocaleString("hu-HU")} Ft
              </span>
              {cp.price_huf_per_kwh > 0 && (
                <> (≈ {(cp.min_charge_huf / cp.price_huf_per_kwh).toFixed(2).replace(".", ",")} kWh)</>
              )}
              . Nagyon rövid töltés esetén is legalább ez az összeg kerül levonásra.
            </span>
          </label>
        )}

        {/* ── SZÁMLÁZÁSI ADATOK ── */}
        <div className="mt-5">
          <div className="text-xs font-semibold text-slate-300 uppercase tracking-wide mb-3">
            Számlázási adatok
          </div>

          {/* Számla típusa */}
          <div className="grid grid-cols-2 gap-2 mb-4">
            {[
              { value: "personal", label: "Magánszemély" },
              { value: "business", label: "Céges" },
            ].map((opt) => (
              <button
                key={opt.value}
                type="button"
                disabled={busy}
                onClick={() => setBillingType(opt.value)}
                className={[
                  "rounded-xl border py-2.5 text-sm font-semibold transition",
                  billingType === opt.value
                    ? "border-blue-500 bg-blue-600/30 text-blue-200"
                    : "border-slate-700 bg-slate-800/50 text-slate-300 hover:border-slate-600",
                ].join(" ")}
              >
                {opt.label}
              </button>
            ))}
          </div>

          <div className="space-y-3">
            {/* Név */}
            <Field label={billingType === "business" ? "Kapcsolattartó neve" : "Teljes név"}>
              <input
                className={inputCls}
                value={billingName}
                onChange={(e) => setBillingName(e.target.value)}
                placeholder="Kovács János"
                disabled={busy}
              />
            </Field>

            {/* Céges mezők */}
            {billingType === "business" && (
              <>
                <Field label="Cégnév">
                  <input
                    className={inputCls}
                    value={billingCompany}
                    onChange={(e) => setBillingCompany(e.target.value)}
                    placeholder="Példa Kft."
                    disabled={busy}
                  />
                </Field>
                <Field label="Adószám">
                  <input
                    className={inputCls}
                    value={billingTaxNumber}
                    onChange={(e) => setBillingTaxNumber(e.target.value)}
                    placeholder="12345678-1-23"
                    disabled={busy}
                  />
                </Field>
              </>
            )}

            {/* Cím */}
            <Field label="Utca, házszám">
              <input
                className={inputCls}
                value={billingStreet}
                onChange={(e) => setBillingStreet(e.target.value)}
                placeholder="Kossuth Lajos utca 1."
                disabled={busy}
              />
            </Field>

            {/* Irányítószám + Város */}
            <div className="grid grid-cols-5 gap-2">
              <div className="col-span-2">
                <Field label="Irányítószám">
                  <input
                    className={inputCls}
                    value={billingZip}
                    onChange={(e) => setBillingZip(e.target.value)}
                    placeholder="1234"
                    disabled={busy}
                    maxLength={10}
                  />
                </Field>
              </div>
              <div className="col-span-3">
                <Field label="Város">
                  <input
                    className={inputCls}
                    value={billingCity}
                    onChange={(e) => setBillingCity(e.target.value)}
                    placeholder="Budapest"
                    disabled={busy}
                  />
                </Field>
              </div>
            </div>

            {/* Ország */}
            <Field label="Ország (ISO kód)">
              <input
                className={inputCls}
                value={billingCountry}
                onChange={(e) => setBillingCountry(e.target.value.toUpperCase())}
                placeholder="HU"
                disabled={busy}
                maxLength={4}
              />
            </Field>
          </div>
        </div>

        {/* ── ZÁROLÁSI ÖSSZEG ── */}
        <div className="mt-5">
          <div className="text-xs font-semibold text-slate-300 uppercase tracking-wide mb-3">
            Zárolási keret
          </div>
          <div className="grid grid-cols-3 gap-2">
            {HOLD_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                disabled={busy}
                onClick={() => setHoldAmount(opt.value)}
                className={[
                  "rounded-xl border py-2.5 text-sm font-semibold transition",
                  holdAmount === opt.value
                    ? "border-blue-500 bg-blue-600/30 text-blue-200"
                    : "border-slate-700 bg-slate-800/50 text-slate-300 hover:border-slate-600",
                ].join(" ")}
              >
                {opt.label}
              </button>
            ))}
          </div>
          <div className="mt-1.5 text-xs text-slate-500">
            Hosszabb töltéshez válasszon nagyobb keretet. A tényleges levonás ettől független.
          </div>
        </div>

        {/* ── EMAIL ── */}
        <div className="mt-5">
          <div className="text-xs font-semibold text-slate-300 uppercase tracking-wide mb-3">
            Kapcsolat
          </div>
          <Field label="Email-cím — ide érkezik az értesítő és a számla">
            <input
              className={inputCls}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="pelda@domain.hu"
              disabled={busy}
              type="email"
            />
          </Field>
        </div>

        {err && <div className="mt-3 text-sm text-red-400">{err}</div>}

        <div className="mt-5 flex gap-2 justify-end">
          <button type="button" className="btn btnGhost" onClick={closeModal} disabled={busy}>
            Mégse
          </button>
          <button
            type="button"
            className="btn btnPrimary"
            disabled={busy || !isStartable(cp.status) || (cp.min_charge_huf > 0 && !minAck)}
            onClick={startFlow}
          >
            {busy ? "Átirányítás…" : `Zárolás: ${holdAmount.toLocaleString("hu-HU")} Ft →`}
          </button>
        </div>
      </PayModal>
    </div>
  );
}
