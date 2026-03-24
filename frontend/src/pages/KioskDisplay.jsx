import { useEffect, useState } from "react";
import { QRCodeSVG } from "qrcode.react";

const MESSAGES = [
  { main: "Töltse fel autóját", sub: "gyorsan és egyszerűen" },
  { main: "Olvassa be a QR-kódot", sub: "a töltés indításához" },
  { main: "Bankkártyás fizetés", sub: "regisztráció nélkül" },
  { main: "170 Ft / kWh", sub: "bruttó, 27% ÁFÁ-val" },
];

const INTERVAL_MS = 5000;

export default function KioskDisplay() {
  const [idx, setIdx] = useState(0);
  const [visible, setVisible] = useState(true);

  const url = window.location.origin;

  useEffect(() => {
    const timer = setInterval(() => {
      // fade out → váltás → fade in
      setVisible(false);
      setTimeout(() => {
        setIdx((i) => (i + 1) % MESSAGES.length);
        setVisible(true);
      }, 400);
    }, INTERVAL_MS);
    return () => clearInterval(timer);
  }, []);

  const msg = MESSAGES[idx];

  return (
    <div
      className="min-h-screen bg-slate-950 flex flex-col items-center justify-center gap-10 p-8 select-none"
      style={{ fontFamily: "system-ui, sans-serif" }}
    >
      {/* Logo / cím */}
      <div className="text-center">
        <div className="text-3xl font-black tracking-tight text-white">
          ⚡ Napos töltő
        </div>
        <div className="text-slate-400 text-sm mt-1 tracking-wide uppercase">
          EV töltőállomás
        </div>
      </div>

      {/* QR kód */}
      <div className="bg-white rounded-3xl p-5 shadow-2xl">
        <QRCodeSVG
          value={url}
          size={220}
          bgColor="#ffffff"
          fgColor="#0f172a"
          level="M"
        />
      </div>

      {/* Görgetett üzenet */}
      <div
        className="text-center transition-opacity duration-400"
        style={{ opacity: visible ? 1 : 0, minHeight: "5rem" }}
      >
        <div className="text-4xl font-bold text-white leading-tight">
          {msg.main}
        </div>
        <div className="text-xl text-slate-400 mt-2">
          {msg.sub}
        </div>
      </div>

      {/* Ár kiemelés – mindig látszik */}
      <div className="rounded-2xl border border-emerald-700/50 bg-emerald-950/40 px-8 py-4 text-center">
        <div className="text-xs text-emerald-400/70 uppercase tracking-widest mb-1">
          Töltési díj
        </div>
        <div className="text-5xl font-black text-emerald-300 tracking-tight">
          170 <span className="text-2xl font-semibold text-emerald-400">Ft/kWh</span>
        </div>
      </div>

      {/* URL hint */}
      <div className="text-slate-600 text-sm tracking-wide">
        {url}
      </div>
    </div>
  );
}
