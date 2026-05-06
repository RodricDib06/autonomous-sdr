import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "../../lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary/20 text-primary",
        secondary: "border-transparent bg-secondary text-secondary-foreground",
        destructive: "border-transparent bg-destructive/20 text-red-400 border-red-900",
        outline: "text-foreground",
        hot: "border-transparent bg-red-500/20 text-red-400 border-red-900/50",
        warm: "border-transparent bg-orange-500/20 text-orange-400 border-orange-900/50",
        cold: "border-transparent bg-blue-500/20 text-blue-400 border-blue-900/50",
        success: "border-transparent bg-emerald-500/20 text-emerald-400 border-emerald-900/50",
        warning: "border-transparent bg-yellow-500/20 text-yellow-400 border-yellow-900/50",
        admin: "border-transparent bg-violet-500/20 text-violet-400 border-violet-900/50",
        manager: "border-transparent bg-indigo-500/20 text-indigo-400 border-indigo-900/50",
        rep: "border-transparent bg-slate-500/20 text-slate-400 border-slate-700/50",
      },
    },
    defaultVariants: { variant: "default" },
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
