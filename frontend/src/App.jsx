import { Routes, Route } from "react-router-dom";

import Home from "./pages/Home.jsx";
import PaySuccess from "./pages/PaySuccess.jsx";
import PayCancel from "./pages/PayCancel.jsx";
import NotFound from "./pages/NotFound.jsx";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/pay/success" element={<PaySuccess />} />
      <Route path="/pay/cancel" element={<PayCancel />} />
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}