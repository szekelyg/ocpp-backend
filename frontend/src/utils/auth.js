// frontend/src/utils/auth.js
// Bejelentkezés-kezelés egy helyen. Egyetlen fiókos belépés van: az egységes
// Energiafelhő-fiók (Keycloak) – Authorization Code + PKCE, public kliens. A token-készletet
// (access/refresh/id) a localStorage "ef_kc_session" kulcs alatt tartjuk, az access tokent
// lejárat előtt a refresh tokennel frissítjük. A backend `Authorization: Bearer …`-ként
// fogadja (/api/me/*, /api/intents/, /api/sessions/{id}/stop). Kártyaadat sehol nem szerepel.
//
// A régi e-mail-kódos belépés (localStorage "ef_auth_token") 2026-09-22-én megszűnt: a kulcsot
// itt már csak töröljük, belépettnek nem számít. A vendég-töltés és a nyugta-link (intent-token,
// sessionStorage, lásd ChargingPage) ettől független.

const LEGACY_EMAIL_TOKEN_KEY = "ef_auth_token";      // megszűnt e-mail-kódos token – csak takarítás
export const KC_SESSION_KEY = "ef_kc_session";       // Keycloak tokenek
const PKCE_KEY = "ef_kc_pkce";                       // sessionStorage: state + verifier + returnTo
const CHANGE_EVENT = "ef-auth-change";
// Ennyivel a lejárat előtt már frissítünk (az access token Keycloakban alapból 5 perces).
const REFRESH_SKEW_S = 30;

export const CALLBACK_PATH = "/auth/keycloak/callback";

// ── tárolás ────────────────────────────────────────────────────────────────

function lsGet(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}
function lsSet(key, val) {
  try { localStorage.setItem(key, val); } catch { /* ignore */ }
}
function lsDel(key) {
  try { localStorage.removeItem(key); } catch { /* ignore */ }
}

function notify() {
  try { window.dispatchEvent(new Event(CHANGE_EVENT)); } catch { /* ignore */ }
}

/** Fel-/leiratkozás a belépési állapot változására (fejléc, oldalak). */
export function onAuthChange(fn) {
  window.addEventListener(CHANGE_EVENT, fn);
  window.addEventListener("storage", fn);
  return () => {
    window.removeEventListener(CHANGE_EVENT, fn);
    window.removeEventListener("storage", fn);
  };
}

function readKc() {
  const raw = lsGet(KC_SESSION_KEY);
  if (!raw) return null;
  try {
    const s = JSON.parse(raw);
    return s && s.access_token ? s : null;
  } catch {
    return null;
  }
}

function writeKc(tokens) {
  const now = Math.floor(Date.now() / 1000);
  const prev = readKc() || {};
  const s = {
    access_token: tokens.access_token,
    refresh_token: tokens.refresh_token || prev.refresh_token || null,
    id_token: tokens.id_token || prev.id_token || null,
    expires_at: now + (Number(tokens.expires_in) || 300),
    refresh_expires_at: tokens.refresh_expires_in ? now + Number(tokens.refresh_expires_in) : (prev.refresh_expires_at || null),
  };
  lsSet(KC_SESSION_KEY, JSON.stringify(s));
  return s;
}

// A megszűnt belépés ottmaradt tokenje: egyszer, betöltéskor kitakarítjuk.
lsDel(LEGACY_EMAIL_TOKEN_KEY);

/** Csak a helyi tárolót üríti (a Keycloak SSO-session megmarad). */
export function clearAuth() {
  lsDel(LEGACY_EMAIL_TOKEN_KEY);
  lsDel(KC_SESSION_KEY);
  notify();
}

/** "keycloak" | null – szinkron, hálózat nélkül. */
export function authSource() {
  return readKc() ? "keycloak" : null;
}

export function isLoggedIn() {
  return authSource() !== null;
}

// ── Keycloak konfiguráció (a backend adja, nem titkos) ─────────────────────

let _configPromise = null;

export function getKeycloakConfig() {
  if (!_configPromise) {
    _configPromise = fetch("/api/auth/keycloak/config", { headers: { Accept: "application/json" } })
      .then((r) => (r.ok ? r.json() : { enabled: false }))
      .catch(() => ({ enabled: false }))
      .then((cfg) => {
        if (!cfg || !cfg.enabled || !cfg.authorization_endpoint || !cfg.token_endpoint || !cfg.client_id) {
          return { enabled: false };
        }
        return cfg;
      });
  }
  return _configPromise;
}

// ── PKCE ───────────────────────────────────────────────────────────────────

function b64url(bytes) {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function randomString(len = 64) {
  const arr = new Uint8Array(len);
  crypto.getRandomValues(arr);
  return b64url(arr).slice(0, len);
}

async function sha256b64url(text) {
  const data = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return b64url(new Uint8Array(digest));
}

function redirectUri() {
  return `${window.location.origin}${CALLBACK_PATH}`;
}

/**
 * Átirányítás a Keycloak belépő oldalára. `returnTo`: hova jöjjünk vissza a callback után
 * (csak saját, "/"-rel kezdődő útvonal – nyílt átirányítás ellen).
 */
export async function startKeycloakLogin({ returnTo = "/toltesek" } = {}) {
  const cfg = await getKeycloakConfig();
  if (!cfg.enabled) throw new Error("A fiókos belépés jelenleg nem elérhető.");
  if (!window.isSecureContext || !crypto?.subtle) {
    throw new Error("A fiókos belépéshez https-en kell megnyitni az oldalt.");
  }
  const verifier = randomString(64);
  const challenge = await sha256b64url(verifier);
  const state = randomString(32);
  const safeReturn = typeof returnTo === "string" && returnTo.startsWith("/") && !returnTo.startsWith("//")
    ? returnTo
    : "/toltesek";
  try {
    sessionStorage.setItem(PKCE_KEY, JSON.stringify({ state, verifier, returnTo: safeReturn }));
  } catch {
    throw new Error("A böngésző nem engedi a munkamenet-tárolót; a belépés nem indítható.");
  }
  const url = new URL(cfg.authorization_endpoint);
  url.searchParams.set("client_id", cfg.client_id);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("scope", "openid email profile");
  url.searchParams.set("redirect_uri", redirectUri());
  url.searchParams.set("state", state);
  url.searchParams.set("code_challenge", challenge);
  url.searchParams.set("code_challenge_method", "S256");
  window.location.assign(url.toString());
}

async function tokenRequest(cfg, params) {
  const body = new URLSearchParams({ client_id: cfg.client_id, ...params });
  const res = await fetch(cfg.token_endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: body.toString(),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || !data.access_token) {
    const err = new Error(data.error_description || data.error || `Token hiba (${res.status})`);
    err.code = data.error || "token_error";
    throw err;
  }
  return data;
}

/**
 * A /auth/keycloak/callback oldal hívja: state-ellenőrzés, code → token csere (PKCE),
 * tárolás. Visszaadja a returnTo útvonalat.
 */
export async function completeKeycloakLogin(search) {
  const params = new URLSearchParams(search || window.location.search);
  const code = params.get("code");
  const state = params.get("state");
  const error = params.get("error");
  let saved = null;
  try { saved = JSON.parse(sessionStorage.getItem(PKCE_KEY) || "null"); } catch { saved = null; }
  try { sessionStorage.removeItem(PKCE_KEY); } catch { /* ignore */ }

  if (error) {
    throw new Error(params.get("error_description") || `Belépés megszakítva (${error}).`);
  }
  if (!code || !state) throw new Error("Hiányzó belépési adatok a visszairányításban.");
  if (!saved || saved.state !== state) {
    throw new Error("A belépési kérés nem azonosítható (lejárt vagy más böngészőfülből indult). Próbáld újra.");
  }
  const cfg = await getKeycloakConfig();
  if (!cfg.enabled) throw new Error("A fiókos belépés jelenleg nem elérhető.");
  const tokens = await tokenRequest(cfg, {
    grant_type: "authorization_code",
    code,
    redirect_uri: redirectUri(),
    code_verifier: saved.verifier,
  });
  writeKc(tokens);
  notify();
  return saved.returnTo || "/toltesek";
}

let _refreshing = null;

async function refreshKc(session) {
  if (!session.refresh_token) return null;
  if (!_refreshing) {
    _refreshing = (async () => {
      const cfg = await getKeycloakConfig();
      if (!cfg.enabled) return null;
      try {
        const tokens = await tokenRequest(cfg, { grant_type: "refresh_token", refresh_token: session.refresh_token });
        return writeKc(tokens);
      } catch {
        // lejárt SSO-session / visszavont token → kijelentkezett állapot
        lsDel(KC_SESSION_KEY);
        notify();
        return null;
      } finally {
        _refreshing = null;
      }
    })();
  }
  return _refreshing;
}

/** Érvényes Keycloak access token (szükség esetén frissítve), különben "". */
export async function getAccessToken() {
  const kc = readKc();
  if (!kc) return "";
  const now = Math.floor(Date.now() / 1000);
  if (kc.expires_at - REFRESH_SKEW_S > now) return kc.access_token;
  const fresh = await refreshKc(kc);
  return fresh ? fresh.access_token : "";
}

/** `{ Authorization: "Bearer …" }` vagy `{}`. */
export async function authHeaders() {
  const t = await getAccessToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

/**
 * fetch + Bearer. 401-re (érvénytelen/lejárt token) kiüríti a helyi belépést, hogy a
 * felület ne ragadjon "belépve, de minden 401" állapotban.
 */
export async function apiFetch(url, opts = {}) {
  const headers = { ...(opts.headers || {}), ...(await authHeaders()) };
  const res = await fetch(url, { ...opts, headers });
  if (res.status === 401 && headers.Authorization) clearAuth();
  return res;
}

/**
 * Kijelentkezés. Keycloak-belépésnél a Keycloak end-session végpontjára is elmegyünk
 * (id_token_hint + post_logout_redirect_uri), hogy az SSO-session is záruljon.
 */
export async function logout({ redirectTo = "/" } = {}) {
  const kc = readKc();
  clearAuth();
  if (!kc) {
    window.location.assign(redirectTo);
    return;
  }
  const cfg = await getKeycloakConfig();
  if (cfg.enabled && cfg.end_session_endpoint && kc.id_token) {
    const url = new URL(cfg.end_session_endpoint);
    url.searchParams.set("id_token_hint", kc.id_token);
    url.searchParams.set("post_logout_redirect_uri", `${window.location.origin}${redirectTo}`);
    window.location.assign(url.toString());
    return;
  }
  window.location.assign(redirectTo);
}
