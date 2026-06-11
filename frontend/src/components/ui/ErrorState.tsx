import type { ReactNode } from "react";
import { Card } from "./Card";
import { InlineCode } from "./InlineCode";

interface ErrorStateProps {
  title: string;
  hint?: ReactNode;
}

export function ErrorState({ title, hint }: ErrorStateProps) {
  return (
    <Card padding="lg">
      <p className="text-sm text-destructive">{title}</p>
      {hint ? <p className="mt-2 text-xs text-muted-foreground">{hint}</p> : null}
    </Card>
  );
}

export function RestartServerHint() {
  return (
    <>
      Start it with <InlineCode>nengok dashboard</InlineCode> and reload this page.
    </>
  );
}
