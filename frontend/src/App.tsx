import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Layout } from "./components/layout/Layout";
import { ProtectedRoute } from "./components/ProtectedRoute";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Leads from "./pages/Leads";
import Import from "./pages/Import";
import Analytics from "./pages/Analytics";
import Pipeline from "./pages/Pipeline";
import ABTests from "./pages/ABTests";
import Users from "./pages/Users";
import Settings from "./pages/Settings";
import ICP from "./pages/ICP";
import Signals from "./pages/Signals";
import Inbox from "./pages/Inbox";
import Approvals from "./pages/Approvals";
import Sequences from "./pages/Sequences";
import Backtests from "./pages/Backtests";
import Campaigns from "./pages/Campaigns";
import { OnboardingWizard } from "./components/OnboardingWizard";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 10_000, retry: 1 },
  },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route element={<ProtectedRoute />}>
            <Route element={<><Layout /><OnboardingWizard /></>}>
              <Route index element={<Dashboard />} />
              <Route path="leads" element={<Leads />} />
              <Route path="signals" element={<Signals />} />
              <Route path="inbox" element={<Inbox />} />
              <Route path="approvals" element={<Approvals />} />
              <Route path="campaigns" element={<Campaigns />} />
              <Route path="sequences" element={<Sequences />} />
              <Route path="icp" element={<ICP />} />
              <Route path="pipeline" element={<Pipeline />} />
              <Route path="ab-tests" element={<ABTests />} />
              <Route element={<ProtectedRoute requireManager />}>
                <Route path="import" element={<Import />} />
                <Route path="analytics" element={<Analytics />} />
                <Route path="backtests" element={<Backtests />} />
              </Route>
              <Route element={<ProtectedRoute requireAdmin />}>
                <Route path="users" element={<Users />} />
              </Route>
              <Route path="settings" element={<Settings />} />
            </Route>
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
