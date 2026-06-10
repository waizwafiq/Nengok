import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { activateAdvice, fetchAdvice } from "../api/advice";
import { Badge } from "./ui/Badge";
import { Button } from "./ui/Button";
import { Card } from "./ui/Card";

/**
 * Clustering advice from the retro pass. Proposed rows wait for a human
 * to activate them; the active row is the amendment the clusterer
 * currently appends. Renders nothing when no advice exists so installs
 * that never run `nengok improve` keep their layout.
 */
export function AdvicePanel() {
  const queryClient = useQueryClient();
  const advice = useQuery({
    queryKey: ["advice"],
    queryFn: () => fetchAdvice(),
    retry: false,
  });

  const activate = useMutation({
    mutationFn: (adviceId: string) => activateAdvice(adviceId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["advice"] });
    },
  });

  const rows = (advice.data ?? []).filter((row) => row.status !== "retired");
  if (advice.isLoading || advice.isError || rows.length === 0) {
    return null;
  }

  return (
    <>
      <section className="mb-3 mt-8 flex items-center justify-between">
        <h2 className="section-label">Clustering advice</h2>
      </section>
      <section>
        <Card padding="none">
          <ul className="divide-y divide-border">
            {rows.map((row) => (
              <li key={row.advice_id} className="flex items-start justify-between gap-4 px-4 py-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <Badge tone={row.status === "active" ? "fix" : "diagnosed"}>{row.status}</Badge>
                    {row.project ? (
                      <span className="text-xs text-muted-foreground">{row.project}</span>
                    ) : null}
                    {row.decided_by ? (
                      <span className="text-xs text-muted-foreground">
                        activated by {row.decided_by}
                      </span>
                    ) : null}
                  </div>
                  <p className="mt-1 whitespace-pre-wrap text-xs text-foreground">
                    {row.prompt_amendment}
                  </p>
                </div>
                {row.status === "proposed" ? (
                  <Button
                    variant="outline"
                    disabled={activate.isPending}
                    onClick={() => activate.mutate(row.advice_id)}
                  >
                    Activate
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
        </Card>
      </section>
    </>
  );
}
