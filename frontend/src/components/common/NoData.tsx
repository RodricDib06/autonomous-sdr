import { Inbox, type LucideIcon } from 'lucide-react';

interface NoDataProps {
  message?: string;
  icon?: LucideIcon;
}

export function NoData({ message = 'No data yet', icon: Icon = Inbox }: NoDataProps) {
  return (
    <div className="flex flex-col items-center justify-center py-12 gap-3 text-center">
      <Icon className="w-8 h-8 text-muted-foreground/40" aria-hidden="true" />
      <p className="text-sm text-muted-foreground">{message}</p>
    </div>
  );
}
