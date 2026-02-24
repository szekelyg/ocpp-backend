import { useMemo } from "react";

export default function PayCancel() {
  const params = useMemo(() => new URLSearchParams(window.location.search), []);
  const intentId = params.get("intent_id");

  return (
    <div style={{ maxWidth: 720, margin: "40px auto", padding: 20, fontFamily: "system-ui" }}>
      <h1>Fizetés megszakítva</h1>
      <p>A fizetést megszakítottad vagy lejárt.</p>
      <p>
        Intent ID: <b>{intentId || "—"}</b>
      </p>
      <a href="/" style={{ display: "inline-block", marginTop: 16 }}>Vissza a térképhez</a>
    </div>
  );
}