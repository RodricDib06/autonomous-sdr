import { Navigate, Outlet } from "react-router-dom";
import { useAuthStore } from "../store/authStore";

interface Props {
  children?: React.ReactNode;
  requireAdmin?: boolean;
  requireManager?: boolean;
}

export function ProtectedRoute({ children, requireAdmin, requireManager }: Props) {
  const { user, isAdmin, isManager } = useAuthStore();

  if (!user) return <Navigate to="/login" replace />;
  if (requireAdmin && !isAdmin()) return <Navigate to="/" replace />;
  if (requireManager && !isManager()) return <Navigate to="/" replace />;

  return children ? <>{children}</> : <Outlet />;
}
