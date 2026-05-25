import type { HTMLAttributes } from "react";
import { cn } from "../../lib/cn";

export function Skeleton({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      {...rest}
      className={cn("animate-pulse rounded-md bg-muted/70", className)}
      aria-hidden="true"
    />
  );
}
