import { forwardRef, type ButtonHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "default" | "secondary" | "outline" | "ghost" | "destructive";
  size?: "sm" | "md" | "lg";
}

export const Button = forwardRef<HTMLButtonElement, Props>(
  ({ variant = "default", size = "md", className, ...props }, ref) => (
    <button
      ref={ref}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-md font-medium transition-colors",
        "focus:outline-none focus:ring-2 focus:ring-ring/60 focus:ring-offset-1 focus:ring-offset-background",
        "disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" && "h-8 px-3 text-xs",
        size === "md" && "h-9 px-4 text-sm",
        size === "lg" && "h-10 px-5 text-sm",
        variant === "default" && "bg-primary text-primary-foreground hover:bg-primary/90",
        variant === "secondary" && "bg-secondary text-secondary-foreground hover:bg-secondary/80",
        variant === "outline" && "border border-border bg-transparent hover:bg-secondary",
        variant === "ghost" && "bg-transparent hover:bg-secondary/60",
        variant === "destructive" && "bg-destructive text-destructive-foreground hover:bg-destructive/90",
        className,
      )}
      {...props}
    />
  ),
);
Button.displayName = "Button";
