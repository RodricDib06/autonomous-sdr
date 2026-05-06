import { type LucideIcon } from "lucide-react";
import { Card, CardContent } from "./ui/card";
import { cn } from "../lib/utils";

interface StatCardProps {
  title: string;
  value: string | number;
  sub?: string;
  icon: LucideIcon;
  trend?: { value: number; label: string };
  accent?: "violet" | "emerald" | "orange" | "red" | "blue";
  loading?: boolean;
}

const accentMap = {
  violet: "from-violet-500/20 to-violet-500/5 border-violet-500/20",
  emerald: "from-emerald-500/20 to-emerald-500/5 border-emerald-500/20",
  orange: "from-orange-500/20 to-orange-500/5 border-orange-500/20",
  red: "from-red-500/20 to-red-500/5 border-red-500/20",
  blue: "from-blue-500/20 to-blue-500/5 border-blue-500/20",
};

const iconAccentMap = {
  violet: "bg-violet-500/20 text-violet-400",
  emerald: "bg-emerald-500/20 text-emerald-400",
  orange: "bg-orange-500/20 text-orange-400",
  red: "bg-red-500/20 text-red-400",
  blue: "bg-blue-500/20 text-blue-400",
};

export function StatCard({ title, value, sub, icon: Icon, trend, accent = "violet", loading }: StatCardProps) {
  return (
    <Card className={cn("relative overflow-hidden bg-gradient-to-br border", accentMap[accent])}>
      <CardContent className="p-5">
        {loading ? (
          <div className="space-y-2">
            <div className="skeleton h-4 w-24 rounded" />
            <div className="skeleton h-8 w-16 rounded" />
          </div>
        ) : (
          <>
            <div className="flex items-start justify-between">
              <div>
                <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">{title}</p>
                <p className="mt-1 text-2xl font-bold tracking-tight">{value}</p>
                {sub && <p className="mt-1 text-xs text-muted-foreground">{sub}</p>}
              </div>
              <div className={cn("p-2.5 rounded-lg", iconAccentMap[accent])}>
                <Icon className="w-5 h-5" />
              </div>
            </div>
            {trend && (
              <div className="mt-3 flex items-center gap-1 text-xs">
                <span className={trend.value >= 0 ? "text-emerald-400" : "text-red-400"}>
                  {trend.value >= 0 ? "▲" : "▼"} {Math.abs(trend.value)}%
                </span>
                <span className="text-muted-foreground">{trend.label}</span>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
