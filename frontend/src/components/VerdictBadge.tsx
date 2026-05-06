import { Badge } from "./ui/badge";
import { Flame, TrendingUp, Snowflake } from "lucide-react";

export function VerdictBadge({ verdict }: { verdict: string | null | undefined }) {
  if (!verdict) return <span className="text-xs text-muted-foreground">—</span>;

  const map = {
    Hot: { variant: "hot" as const, icon: Flame },
    Warm: { variant: "warm" as const, icon: TrendingUp },
    Cold: { variant: "cold" as const, icon: Snowflake },
  };

  const config = map[verdict as keyof typeof map];
  if (!config) return <Badge variant="secondary">{verdict}</Badge>;
  const Icon = config.icon;

  return (
    <Badge variant={config.variant} className="gap-1">
      <Icon className="w-3 h-3" />
      {verdict}
    </Badge>
  );
}
