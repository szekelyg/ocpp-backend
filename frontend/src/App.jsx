import { Routes, Route } from "react-router-dom";

import Home from "./pages/Home.jsx";
import PaySuccess from "./pages/PaySuccess.jsx";
import PayCancel from "./pages/PayCancel.jsx";
import ChargingPage from "./pages/ChargingPage.jsx";
import AdminPage from "./pages/AdminPage.jsx";
import Aszf from "./pages/Aszf.jsx";
import Adatkezeles from "./pages/Adatkezeles.jsx";
import NotFound from "./pages/NotFound.jsx";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/pay/success" element={<PaySuccess />} />
      <Route path="/pay/cancel" element={<PayCancel />} />
      <Route path="/charging/:sessionId" element={<ChargingPage />} />
      <Route path="/admin" element={<AdminPage />} />
      <Route path="/aszf" element={<Aszf />} />
      <Route path="/adatkezeles" element={<Adatkezeles />} />
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}