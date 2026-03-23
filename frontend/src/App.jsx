import { Routes, Route, Navigate } from "react-router-dom";

import Home from "./pages/Home.jsx";
import PaySuccess from "./pages/PaySuccess.jsx";
import PayCancel from "./pages/PayCancel.jsx";
import ChargingPage from "./pages/ChargingPage.jsx";
import NotFound from "./pages/NotFound.jsx";

import AdminLogin from "./admin/AdminLogin.jsx";
import AdminLayout from "./admin/AdminLayout.jsx";
import AdminDashboard from "./admin/AdminDashboard.jsx";
import AdminSessions from "./admin/AdminSessions.jsx";
import AdminChargePoints from "./admin/AdminChargePoints.jsx";
import AdminIntents from "./admin/AdminIntents.jsx";

function RequireAdmin({ children }) {
  const token = localStorage.getItem("admin_token");
  if (!token) return <Navigate to="/admin/login" replace />;
  return children;
}

export default function App() {
  return (
    <Routes>
      {/* Public */}
      <Route path="/" element={<Home />} />
      <Route path="/pay/success" element={<PaySuccess />} />
      <Route path="/pay/cancel" element={<PayCancel />} />
      <Route path="/charging/:sessionId" element={<ChargingPage />} />

      {/* Admin */}
      <Route path="/admin/login" element={<AdminLogin />} />
      <Route
        path="/admin"
        element={
          <RequireAdmin>
            <AdminLayout />
          </RequireAdmin>
        }
      >
        <Route index element={<AdminDashboard />} />
        <Route path="sessions" element={<AdminSessions />} />
        <Route path="charge-points" element={<AdminChargePoints />} />
        <Route path="intents" element={<AdminIntents />} />
      </Route>

      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}