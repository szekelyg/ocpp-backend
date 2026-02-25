import { useMemo } from "react";

export default function PaySuccess() {
  const params = useMemo(() => new URLSearchParams(window.location.search), []);
  const intentId = params.get("intent_id");

  return (
    <div style={{ maxWidth: 720, margin: "40px auto", padding: 20, fontFamily: "system-ui" }}>
      <h1>Sikeres fizetés</h1>
      <p>Köszönjük! A fizetés sikeres.</p>
      <p>
        Intent ID: <b>{intentId || "—"}</b>
      </p>
      <a href="/" style={{ display: "inline-block", marginTop: 16 }}>Vissza a térképhez</a>
    </div>
  );
}