// Admin API helper

const BASE = "/api/admin";

function getToken() {
  return localStorage.getItem("admin_token");
}

async function apiFetch(path, options = {}) {
  const token = getToken();
  const res = await fetch(BASE + path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
  });

  if (res.status === 401) {
    localStorage.removeItem("admin_token");
    window.location.href = "/admin/login";
    return;
  }

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const msg =
      typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail || data);
    throw new Error(msg || `HTTP ${res.status}`);
  }
  return data;
}

export const api = {
  login: (username, password) =>
    apiFetch("/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),

  stats: () => apiFetch("/stats"),

  sessions: (params = {}) => {
    const q = new URLSearchParams();
    if (params.limit) q.set("limit", params.limit);
    if (params.offset) q.set("offset", params.offset);
    if (params.active_only) q.set("active_only", "true");
    if (params.cp_id) q.set("cp_id", params.cp_id);
    if (params.email) q.set("email", params.email);
    return apiFetch(`/sessions?${q}`);
  },

  stopSession: (id) => apiFetch(`/sessions/${id}/stop`, { method: "POST" }),

  remoteStart: (charge_point_id, connector_id = 1, user_tag = "ADMIN") =>
    apiFetch("/sessions/remote-start", {
      method: "POST",
      body: JSON.stringify({ charge_point_id, connector_id, user_tag }),
    }),

  chargePoints: () => apiFetch("/charge-points"),

  createChargePoint: (data) =>
    apiFetch("/charge-points", { method: "POST", body: JSON.stringify(data) }),

  updateChargePoint: (id, data) =>
    apiFetch(`/charge-points/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  deleteChargePoint: (id) =>
    apiFetch(`/charge-points/${id}`, { method: "DELETE" }),

  intents: (params = {}) => {
    const q = new URLSearchParams();
    if (params.limit) q.set("limit", params.limit);
    if (params.offset) q.set("offset", params.offset);
    if (params.status) q.set("status", params.status);
    return apiFetch(`/intents?${q}`);
  },
};
