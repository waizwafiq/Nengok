import type { HTMLAttributes, ReactNode } from "react";

interface Props extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  padding?: "none" | "sm" | "md" | "lg";
}

const PADDING: Record<NonNullable<Props["padding"]>, string> = {
  none: "",
  sm: "p-3",
  md: "p-4",
  lg: "p-5",
};

export function Card({ children, padding = "md", className = "", ...rest }: Props) {
  return (
    <div {...rest} className={`pane ${PADDING[padding]} ${className}`}>
      {children}
    </div>
  );
}
