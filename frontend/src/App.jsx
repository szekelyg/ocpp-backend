import { useEffect } from "react";
import { Routes, Route } from "react-router-dom";

import Home from "./pages/Home.jsx";
import PaySuccess from "./pages/PaySuccess.jsx";
import PayCancel from "./pages/PayCancel.jsx";
import ChargingPage from "./pages/ChargingPage.jsx";
import AdminPage from "./pages/AdminPage.jsx";
import Aszf from "./pages/Aszf.jsx";
import NotFound from "./pages/NotFound.jsx";
import MySessions from "./pages/MySessions.jsx";
import KeycloakCallback from "./pages/KeycloakCallback.jsx";
import KeycloakStart from "./pages/KeycloakStart.jsx";
import { revalidateSession } from "./utils/auth";

export default function App() {
  // Oldalbetöltéskor: a tárolt belépés még érvényes-e a Keycloaknál (lásd utils/auth.js).
  useEffect(() => {
    if (window.location.pathname.startsWith("/auth/keycloak")) return;
    revalidateSession();
  }, []);

  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/pay/success" element={<PaySuccess />} />
      <Route path="/pay/cancel" element={<PayCancel />} />
      <Route path="/charging/:sessionId" element={<ChargingPage />} />
      <Route path="/admin" element={<AdminPage />} />
      <Route path="/aszf" element={<Aszf />} />
      <Route path="/adatkezeles" element={<AdatkezelesAtiranyitas />} />
      <Route path="/toltesek" element={<MySessions />} />
      <Route path="/auth/keycloak" element={<KeycloakStart />} />
      <Route path="/auth/keycloak/callback" element={<KeycloakCallback />} />
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}
// Energiafelhő, 2026-10-08: egyetlen, közös adatkezelési tájékoztató van (az ev-re is kiterjed);
// a régi /adatkezeles cím (ÁSZF, e-mailek, könyvjelzők) oda visz tovább.
function AdatkezelesAtiranyitas() {
  window.location.replace("https://my.energiafelho.hu/adatkezeles");
  return null;
}
