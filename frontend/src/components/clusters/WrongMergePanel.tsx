import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { flagMergeWrong } from "../../api/approvals";
import { parseMemberSpans } from "../../lib/clusterHelpers";
import { SectionHeader } from "../layout/SectionHeader";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";

interface Props {
  clusterId: string;
  memberSpansJson: string;
  onDetached: () => void;
}

/**
 * Flag a machine merge as wrong: pick the member spans that do not
 * belong here and detach them so the next cycle re-clusters them on
 * their own. Hidden when the cluster has a single member, since there
 * is nothing to split.
 */
export function WrongMergePanel({ clusterId, memberSpansJson, onDetached }: Props) {
  const members = parseMemberSpans(memberSpansJson);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const detach = useMutation({
    mutationFn: () => flagMergeWrong(clusterId, [...selected]),
    onSuccess: () => {
      setSelected(new Set());
      onDetached();
    },
  });

  if (members.length < 2) {
    return null;
  }

  function toggle(spanId: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(spanId)) {
        next.delete(spanId);
      } else {
        next.add(spanId);
      }
      return next;
    });
  }

  return (
    <section>
      <SectionHeader title="Wrong merge?" />
      <Card>
        <p className="text-xs text-muted-foreground">
          Select the member spans that describe a different root cause. Detaching them records
          merge feedback and re-queues the spans for the next cycle.
        </p>
        <ul className="mt-3 max-h-40 space-y-1 overflow-y-auto">
          {members.map((spanId) => (
            <li key={spanId}>
              <label className="flex items-center gap-2 text-xs text-foreground">
                <input
                  type="checkbox"
                  checked={selected.has(spanId)}
                  onChange={() => toggle(spanId)}
                />
                <span className="entity-id">{spanId}</span>
              </label>
            </li>
          ))}
        </ul>
        <div className="mt-3 flex items-center justify-between gap-3">
          {detach.isError ? (
            <p className="text-xs text-destructive">Could not detach the selected spans.</p>
          ) : (
            <span className="text-xs text-muted-foreground">
              {selected.size} span{selected.size === 1 ? "" : "s"} selected
            </span>
          )}
          <Button
            variant="outline"
            disabled={selected.size === 0 || selected.size === members.length || detach.isPending}
            onClick={() => detach.mutate()}
          >
            Detach selected spans
          </Button>
        </div>
      </Card>
    </section>
  );
}
