import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

interface Props extends HTMLAttributes<HTMLSpanElement> {
  variant?: "default" | "secondary" | "outline" | "success" | "warning" | "danger";
}

export function Badge({ variant = "default", className, ...props }: Props) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium",
        variant === "default" && "bg-primary/15 text-primary",
        variant === "secondary" && "bg-muted text-muted-foreground",
        variant === "outline" && "border border-border text-foreground",
        variant === "success" && "bg-success/15 text-success",
        variant === "warning" && "bg-warning/15 text-warning",
        variant === "danger" && "bg-destructive/15 text-destructive",
        className,
      )}
      {...props}
    />
  );
}
