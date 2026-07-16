import { NavLink } from "react-router-dom";
import {
  LayoutDashboard, Users2, Upload, BarChart3,
  Settings, Zap, ChevronRight, LogOut, GitBranch, FlaskConical, Target, Radio, MessageSquare, ShieldCheck, ListOrdered, History,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { cn } from "../../lib/utils";
import { useAuthStore } from "../../store/authStore";
import { Badge } from "../ui/badge";
import { healthApi } from "../../lib/api";

const navItems = [
  { to: "/", icon: LayoutDashboard, label: "Dashboard" },
  { to: "/leads", icon: Zap, label: "Leads" },
  { to: "/signals", icon: Radio, label: "Signals" },
  { to: "/inbox", icon: MessageSquare, label: "Inbox" },
  { to: "/approvals", icon: ShieldCheck, label: "Approvals" },
  { to: "/sequences", icon: ListOrdered, label: "Sequences" },
  { to: "/icp", icon: Target, label: "ICP Builder" },
  { to: "/pipeline", icon: GitBranch, label: "Pipeline" },
  { to: "/ab-tests", icon: FlaskConical, label: "A/B Tests" },
  { to: "/import", icon: Upload, label: "Import" },
  { to: "/analytics", icon: BarChart3, label: "Analytics" },
  { to: "/backtests", icon: History, label: "Backtests" },
];

const adminItems = [
  { to: "/users", icon: Users2, label: "Users" },
  { to: "/settings", icon: Settings, label: "Settings" },
];

function WorkerStatus() {
  const { data } = useQuery({
    queryKey: ["health"],
    queryFn: healthApi.check,
    refetchInterval: 15_000,
    retry: false,
  });

  const active = data?.worker_active ?? false;

  return (
    <div className="flex items-center gap-2 px-3 py-2 mx-3 rounded-lg bg-secondary/50 border border-border">
      <span className="relative flex h-2 w-2 shrink-0">
        {active && (
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
        )}
        <span className={cn(
          "relative inline-flex rounded-full h-2 w-2",
          active ? "bg-emerald-400" : "bg-red-500"
        )} />
      </span>
      <span className="text-xs text-muted-foreground">
        Worker {active ? "running" : "offline"}
      </span>
    </div>
  );
}

export function Sidebar() {
  const { user, logout, isAdmin } = useAuthStore();

  return (
    <aside className="fixed inset-y-0 left-0 z-30 w-60 flex flex-col bg-card border-r border-border">
      {/* Logo */}
      <div className="flex items-center gap-3 px-5 py-5 border-b border-border">
        <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-violet-600 to-indigo-600 shadow-lg">
          <Zap className="w-4 h-4 text-white" />
        </div>
        <div>
          <p className="font-semibold text-sm tracking-tight gradient-text">AutonomousSDR</p>
          <p className="text-[10px] text-muted-foreground">AI Lead Intelligence</p>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
        <p className="px-2 mb-2 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/60">
          Workspace
        </p>
        {navItems.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }) =>
              cn(
                "group flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-all",
                isActive
                  ? "bg-primary/15 text-primary"
                  : "text-muted-foreground hover:bg-secondary hover:text-foreground"
              )
            }
          >
            {({ isActive }) => (
              <>
                <Icon className={cn("w-4 h-4 shrink-0", isActive ? "text-primary" : "text-muted-foreground group-hover:text-foreground")} />
                <span className="flex-1">{label}</span>
                {isActive && <ChevronRight className="w-3 h-3 text-primary/60" />}
              </>
            )}
          </NavLink>
        ))}

        {isAdmin() && (
          <>
            <p className="px-2 mt-4 mb-2 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/60">
              Admin
            </p>
            {adminItems.map(({ to, icon: Icon, label }) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  cn(
                    "group flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-all",
                    isActive
                      ? "bg-primary/15 text-primary"
                      : "text-muted-foreground hover:bg-secondary hover:text-foreground"
                  )
                }
              >
                {({ isActive }) => (
                  <>
                    <Icon className={cn("w-4 h-4 shrink-0", isActive ? "text-primary" : "text-muted-foreground")} />
                    <span className="flex-1">{label}</span>
                    {isActive && <ChevronRight className="w-3 h-3 text-primary/60" />}
                  </>
                )}
              </NavLink>
            ))}
          </>
        )}
      </nav>

      {/* Worker status */}
      <div className="pb-2">
        <WorkerStatus />
      </div>

      {/* User footer */}
      <div className="p-3 border-t border-border">
        <div className="flex items-center gap-3 rounded-lg px-3 py-2">
          <div className="flex items-center justify-center w-8 h-8 rounded-full bg-gradient-to-br from-violet-600 to-indigo-600 text-white text-xs font-semibold shrink-0">
            {user?.email.slice(0, 2).toUpperCase()}
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-xs font-medium truncate">{user?.email}</p>
            <Badge variant={user?.role as "admin" | "manager" | "rep"} className="mt-0.5 text-[10px] px-1.5 py-0">
              {user?.role}
            </Badge>
          </div>
          <button
            onClick={logout}
            title="Sign out"
            className="p-1 rounded-md text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors"
          >
            <LogOut className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </aside>
  );
}
