import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "danger" | "neutral";

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  children: ReactNode;
}

const VARIANTS: Record<Variant, string> = {
  primary: "bg-status-fix text-white hover:opacity-90",
  danger: "bg-status-escalated text-white hover:opacity-90",
  neutral: "border border-neutral-300 text-neutral-700 hover:bg-neutral-100",
};

export function Button({ variant = "primary", className = "", children, ...rest }: Props) {
  return (
    <button
      {...rest}
      className={`px-4 py-2 rounded-md text-sm transition-colors disabled:opacity-50 ${VARIANTS[variant]} ${className}`}
    >
      {children}
    </button>
  );
}
