// frontend/src/pages/MySessions.jsx
// "Töltéseim": a bejelentkezett fiók (Energiafelhő-fiók vagy e-mail-kód) töltései a
// GET /api/me/sessions végpontból – lapozva, összesítéssel, számla-letöltéssel.
import { useCallback, useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import AppHeader from "../components/ui/AppHeader";
import AppFooter from "../components/ui/AppFooter";
import LoginAutofill from "../components/ui/LoginAutofill";
import useAuth from "../hooks/useAuth";
import { apiFetch } from "../utils/auth";
import { formatHu } from "../utils/format";

const PAGE = 20;

function fmtKwh(v) {
  if (v == null) return "—";
  return `${Number(v).toLocaleString("hu-HU", { minimumFractionDigits: 1, maximumFractionDigits: 2 })} kWh`;
}

function fmtHuf(v) {
  if (v == null) return "—";
  return `${Math.round(Number(v)).toLocaleString("hu-HU")} Ft`;
}

function fmtDuration(s) {
  if (s == null || s < 0) return "—";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h > 0) return `${h} ó ${m} p`;
  return `${m} p`;
}

const STATUS = {
  active: { label: "Folyamatban", cls: "badgeGood" },
  waiting: { label: "Autóra vár", cls: "badgeWarn" },
  finished: { label: "Befejezve", cls: "badgeOk" },
  timed_out: { label: "Nem indult el", cls: "badgeMuted" },
};

function SessionRow({ s, onInvoice, invoiceBusy }) {
  const st = STATUS[s.status] || { label: s.status, cls: "badgeMuted" };
  return (
    <li className="listItem hover:shadow-none">
      <div className="listItemTop">
        <div className="min-w-0">
          <div className="listItemTitle truncate">{s.charge_point?.name || s.charge_point?.ocpp_id || "Töltő"}</div>
          {s.charge_point?.address && (
            <div className="text-xs text-ink-muted truncate mt-0.5">{s.charge_point.address}</div>
          )}
        </div>
        <span className={`badge ${st.cls} shrink-0`}>{st.label}</span>
      </div>

      <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-2 text-sm">
        <div>
          <div className="label">Kezdés</div>
          <div className="text-ink">{formatHu(s.started_at)}</div>
        </div>
        <div>
          <div className="label">Időtartam</div>
          <div className="text-ink tabular-nums">{fmtDuration(s.duration_s)}</div>
        </div>
        <div>
          <div className="label">Energia</div>
          <div className="text-ink font-semibold tabular-nums">{fmtKwh(s.energy_kwh)}</div>
        </div>
        <div>
          <div className="label">Díj</div>
          <div className="text-ink font-semibold tabular-nums">{fmtHuf(s.cost_huf)}</div>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs">
        <span className="text-ink-muted">
          #{s.id}
          {s.invoice_number ? ` · Számla: ${s.invoice_number}` : ""}
        </span>
        <div className="flex gap-2">
          {s.status === "active" || s.status === "waiting" ? (
            <Link to={`/charging/${s.id}`} className="btn btnPrimary !py-1.5 !px-3 !text-xs">
              Töltés megnyitása →
            </Link>
          ) : null}
          {s.invoice_url && (
            <button
              type="button"
              className="btn !py-1.5 !px-3 !text-xs"
              disabled={invoiceBusy === s.id}
              onClick={() => onInvoice(s)}
            >
              {invoiceBusy === s.id ? "Letöltés…" : "Számla (PDF)"}
            </button>
          )}
        </div>
      </div>
    </li>
  );
}

export default function MySessions() {
  const { me, loading: authLoading, loggedIn, source, logout, reload } = useAuth();
  const location = useLocation();

  const [data, setData] = useState(null);       // { sessions, total, total_kwh, total_huf }
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [invoiceBusy, setInvoiceBusy] = useState(null);

  const load = useCallback(async (offset = 0, append = false) => {
    setLoading(true);
    setErr("");
    try {
      const res = await apiFetch(`/api/me/sessions?limit=${PAGE}&offset=${offset}`, {
        headers: { Accept: "application/json" },
      });
      if (!res.ok) throw new Error(res.status === 401 ? "A belépés lejárt. Kérjük lépj be újra." : `Hiba: ${res.status}`);
      const body = await res.json();
      setData((prev) => (append && prev
        ? { ...body, sessions: [...prev.sessions, ...body.sessions] }
        : body));
    } catch (e) {
      setErr(e?.message || "Nem sikerült betölteni a töltéseket.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (loggedIn) load(0);
    else setData(null);
  }, [loggedIn, load]);

  async function openInvoice(s) {
    setInvoiceBusy(s.id);
    try {
      const res = await apiFetch(s.invoice_url, { headers: { Accept: "application/pdf" } });
      if (!res.ok) throw new Error(res.status === 502 ? "A számla most nem érhető el a Számlázz.hu-n. Próbáld később." : `Hiba: ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `szamla_${s.invoice_number || s.id}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (e) {
      setErr(e?.message || "A számla letöltése nem sikerült.");
    } finally {
      setInvoiceBusy(null);
    }
  }

  const returnTo = location.pathname + location.search;

  return (
    <div className="min-h-screen flex flex-col">
      <AppHeader />

      <div className="mx-auto max-w-3xl w-full p-6 space-y-5 flex-1">
        <div className="headerRow">
          <div>
            <h1 className="text-2xl md:text-3xl font-extrabold tracking-tight text-ink">Töltéseim</h1>
            <p className="subtitle mt-1">
              A fiókodhoz tartozó töltések, díjak és számlák egy helyen.
            </p>
          </div>
          <Link to="/" className="btn btnGhost">← Töltők</Link>
        </div>

        {/* Nincs belépve */}
        {!authLoading && !loggedIn && (
          <div className="card">
            <div className="cardHeader">
              <div className="cardTitle">Belépés</div>
              <div className="cardSub mt-0.5">Válaszd az Energiafelhő-fiókot, vagy kérj belépési kódot e-mailben.</div>
            </div>
            <div className="cardBody space-y-4">
              {/* Energiafelhő-fiók gomb (ha van Keycloak) + e-mail-kódos út egyben */}
              <LoginAutofill returnTo={returnTo} onLoggedIn={() => reload()} />
              <p className="text-xs text-ink-muted">
                Regisztráció nélkül is tölthetsz: a töltés után kapott e-mail linkjével bármikor
                megnézheted az adott töltést.
              </p>
            </div>
          </div>
        )}

        {/* Belépve */}
        {loggedIn && (
          <>
            <div className="card">
              <div className="cardBody flex flex-wrap items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="kicker">Belépve</div>
                  <div className="font-semibold text-ink truncate">{me?.name || me?.email}</div>
                  <div className="text-xs text-ink-muted truncate">
                    {me?.email}
                    {source === "keycloak" ? " · Energiafelhő-fiók" : " · e-mail-kódos belépés"}
                  </div>
                </div>
                <button type="button" className="btn btnGhost" onClick={() => logout({ redirectTo: "/toltesek" })}>
                  Kijelentkezés
                </button>
              </div>
              <div className="accentLine" />
            </div>

            {data && (
              <div className="grid grid-cols-3 gap-3">
                {[
                  ["Töltések", `${data.total} db`],
                  ["Összes energia", fmtKwh(data.total_kwh)],
                  ["Összes díj", fmtHuf(data.total_huf)],
                ].map(([k, v]) => (
                  <div key={k} className="card cardBody">
                    <div className="kicker">{k}</div>
                    <div className="mt-1 text-lg sm:text-2xl font-extrabold text-ink tabular-nums">{v}</div>
                  </div>
                ))}
              </div>
            )}

            {err && <div className="errorBanner">{err}</div>}

            <div className="card">
              <div className="cardHeader flex items-center justify-between">
                <div>
                  <div className="cardTitle">Töltések</div>
                  <div className="cardSub mt-0.5">
                    {data ? `${data.sessions.length} / ${data.total} megjelenítve` : "Betöltés…"}
                  </div>
                </div>
                <button type="button" className="btn btnGhost !py-1.5 !text-xs" disabled={loading} onClick={() => load(0)}>
                  Frissítés
                </button>
              </div>
              <div className="cardBody">
                {data && data.sessions.length === 0 && !loading && (
                  <div className="text-center py-6 text-sm text-ink-soft">
                    Ehhez a fiókhoz még nem tartozik töltés.
                    <div className="mt-3">
                      <Link to="/" className="btn btnPrimary inline-flex">Töltő választása →</Link>
                    </div>
                  </div>
                )}
                {data && data.sessions.length > 0 && (
                  <ul className="list">
                    {data.sessions.map((s) => (
                      <SessionRow key={s.id} s={s} onInvoice={openInvoice} invoiceBusy={invoiceBusy} />
                    ))}
                  </ul>
                )}
                {data && data.sessions.length < data.total && (
                  <div className="mt-4 text-center">
                    <button type="button" className="btn" disabled={loading}
                      onClick={() => load(data.sessions.length, true)}>
                      {loading ? "Betöltés…" : "További töltések"}
                    </button>
                  </div>
                )}
                {!data && loading && (
                  <div className="flex justify-center gap-1.5 py-6">
                    {["bg-brand-yellow", "bg-brand-blue", "bg-brand-green"].map((c, i) => (
                      <div key={i} className={`w-2 h-2 rounded-full animate-bounce ${c}`}
                        style={{ animationDelay: `${i * 0.15}s` }} />
                    ))}
                  </div>
                )}
              </div>
            </div>
          </>
        )}
      </div>

      <AppFooter />
    </div>
  );
}
