import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cn } from "../../lib/cn";

type Variant = "primary" | "outline" | "secondary" | "ghost" | "destructive";
type Size = "sm" | "default" | "lg" | "icon";

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  children: ReactNode;
}

const VARIANTS: Record<Variant, string> = {
  primary: "bg-primary text-primary-foreground hover:bg-primary/90",
  outline:
    "border border-border bg-background text-foreground hover:bg-muted",
  secondary:
    "bg-secondary text-secondary-foreground hover:bg-secondary/80",
  ghost: "text-foreground hover:bg-muted",
  destructive:
    "bg-destructive/10 text-destructive hover:bg-destructive/20",
};

const SIZES: Record<Size, string> = {
  sm: "h-7 px-2.5 text-xs rounded-md gap-1",
  default: "h-8 px-2.5 text-sm rounded-lg gap-1.5",
  lg: "h-9 px-3 text-sm rounded-lg gap-1.5",
  icon: "size-8 rounded-lg",
};

export function Button({
  variant = "primary",
  size = "default",
  className,
  children,
  ...rest
}: Props) {
  return (
    <button
      {...rest}
      className={cn(
        "inline-flex shrink-0 items-center justify-center font-medium whitespace-nowrap transition-all outline-none select-none",
        "focus-visible:ring-3 focus-visible:ring-ring/50",
        "active:translate-y-px disabled:pointer-events-none disabled:opacity-50",
        "[&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
    >
      {children}
    </button>
  );
}
