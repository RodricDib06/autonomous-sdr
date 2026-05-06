import { RefreshCw } from "lucide-react";
import { Button } from "../ui/button";
import { useQueryClient } from "@tanstack/react-query";

interface HeaderProps {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
}

export function Header({ title, subtitle, actions }: HeaderProps) {
  const queryClient = useQueryClient();

  return (
    <header className="flex items-center justify-between px-8 py-5 border-b border-border bg-card/50 backdrop-blur-sm sticky top-0 z-20">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="text-sm text-muted-foreground mt-0.5">{subtitle}</p>}
      </div>
      <div className="flex items-center gap-2">
        {actions}
        <Button
          variant="ghost"
          size="icon"
          title="Refresh data"
          onClick={() => queryClient.invalidateQueries()}
          className="text-muted-foreground"
        >
          <RefreshCw className="w-4 h-4" />
        </Button>
      </div>
    </header>
  );
}
