import { useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { storeToken } from "../api/client";
import { Button } from "../components/ui/Button";
import { Card, CardDescription, CardHeader, CardTitle } from "../components/ui/Card";
import { InlineCode } from "../components/ui/InlineCode";

export function LoginPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [token, setToken] = useState("");

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const trimmed = token.trim();
    if (!trimmed) {
      return;
    }
    storeToken(trimmed);
    const redirect = params.get("redirect") ?? "/overview";
    navigate(redirect, { replace: true });
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card padding="lg" className="w-full max-w-sm">
        <CardHeader>
          <div>
            <CardTitle>Sign in to Nengok</CardTitle>
            <CardDescription>
              Paste the value of <InlineCode>dashboard_auth_token</InlineCode> from{" "}
              <InlineCode>~/.nengok/config.toml</InlineCode>.
            </CardDescription>
          </div>
        </CardHeader>
        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            Dashboard token
            <input
              type="password"
              autoFocus
              value={token}
              onChange={(event) => setToken(event.target.value)}
              className="rounded-md border border-border bg-background px-2.5 py-2 font-mono text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
              placeholder="paste token"
            />
          </label>
          <Button type="submit" disabled={!token.trim()}>
            Continue
          </Button>
        </form>
      </Card>
    </div>
  );
}
