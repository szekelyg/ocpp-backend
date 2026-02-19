import { useEffect, useState } from "react";

function App() {
  const [chargers, setChargers] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchChargers = async () => {
    try {
      const res = await fetch("/api/charge-points/");
      const data = await res.json();
      setChargers(data);
      setLoading(false);
    } catch (err) {
      console.error("Hiba a töltők lekérésekor:", err);
    }
  };

  useEffect(() => {
    fetchChargers();
    const interval = setInterval(fetchChargers, 5000);
    return () => clearInterval(interval);
  }, []);

  const statusColor = (status) => {
    switch (status) {
      case "available":
        return "#2ecc71";
      case "charging":
        return "#e67e22";
      case "unavailable":
        return "#e74c3c";
      default:
        return "#95a5a6";
    }
  };

  if (loading) return <div style={{ padding: 40 }}>Betöltés...</div>;

  return (
    <div style={{ padding: 40, fontFamily: "Arial" }}>
      <h1>EV Charging</h1>
      <div style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
        {chargers.map((cp) => (
          <div
            key={cp.id}
            style={{
              border: "1px solid #ddd",
              borderRadius: 12,
              padding: 20,
              width: 280,
              boxShadow: "0 4px 10px rgba(0,0,0,0.05)",
            }}
          >
            <h3>{cp.ocpp_id}</h3>
            <p>{cp.vendor} {cp.model}</p>
            <div
              style={{
                marginTop: 10,
                padding: "6px 12px",
                borderRadius: 20,
                background: statusColor(cp.status),
                color: "white",
                display: "inline-block",
              }}
            >
              {cp.status}
            </div>
            <p style={{ marginTop: 10, fontSize: 12 }}>
              Last seen: {cp.last_seen_at || "—"}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

export default App;