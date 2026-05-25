import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "../../lib/cn";

type Padding = "none" | "sm" | "md" | "lg";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  padding?: Padding;
}

const PADDING: Record<Padding, string> = {
  none: "",
  sm: "p-3",
  md: "p-4",
  lg: "p-5",
};

export function Card({ children, padding = "md", className, ...rest }: CardProps) {
  return (
    <div
      {...rest}
      className={cn(
        "rounded-xl bg-card text-card-foreground ring-1 ring-foreground/10 overflow-hidden",
        PADDING[padding],
        className,
      )}
    >
      {children}
    </div>
  );
}

export function CardHeader({
  children,
  className,
  ...rest
}: HTMLAttributes<HTMLDivElement> & { children: ReactNode }) {
  return (
    <div {...rest} className={cn("flex items-start justify-between gap-3 mb-3", className)}>
      {children}
    </div>
  );
}

export function CardTitle({
  children,
  className,
  ...rest
}: HTMLAttributes<HTMLHeadingElement> & { children: ReactNode }) {
  return (
    <h3 {...rest} className={cn("text-base font-medium text-foreground", className)}>
      {children}
    </h3>
  );
}

export function CardDescription({
  children,
  className,
  ...rest
}: HTMLAttributes<HTMLParagraphElement> & { children: ReactNode }) {
  return (
    <p {...rest} className={cn("text-xs text-muted-foreground", className)}>
      {children}
    </p>
  );
}
