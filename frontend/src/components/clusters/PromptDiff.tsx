import { useMemo } from "react";
import ReactDiffViewer, { DiffMethod } from "react-diff-viewer-continued";
import { Card } from "../ui/Card";

interface Props {
  prompt: string | null;
}

/**
 * Side-by-side diff of the baseline prompt vs. the Nengok-proposed fix.
 *
 * The bundle on disk lives in `prompt.md` and looks like:
 *
 *     ## Baseline prompt
 *     ```
 *     <baseline body>
 *     ```
 *
 *     ## Prompt body
 *     ```
 *     <proposed body>
 *     ```
 *
 * Both blocks are parsed out of the markdown. Mustache placeholders
 * like `{{input}}` are rendered with distinct styling so reviewers
 * can tell template variables apart from prose.
 */
export function PromptDiff({ prompt }: Props) {
  const parsed = useMemo(() => parsePromptArtifact(prompt), [prompt]);

  if (!parsed) {
    return (
      <Card padding="md" className="border border-dashed border-border bg-card text-center">
        <p className="text-sm text-muted-foreground">No prompt artifact yet.</p>
        <p className="mt-2 text-xs text-muted-foreground">
          The fixer writes one once a candidate prompt has been proposed.
        </p>
      </Card>
    );
  }

  if (parsed.baseline === parsed.proposed) {
    return (
      <Card padding="md" className="border border-dashed border-border bg-card text-center">
        <p className="text-sm text-muted-foreground">
          The proposed prompt is identical to the baseline.
        </p>
      </Card>
    );
  }

  return (
    <div className="pane overflow-x-auto text-xs">
      <ReactDiffViewer
        oldValue={parsed.baseline}
        newValue={parsed.proposed}
        splitView
        useDarkTheme={false}
        leftTitle="Baseline"
        rightTitle="Proposed"
        compareMethod={DiffMethod.LINES}
        renderContent={renderPromptLine}
      />
    </div>
  );
}

function renderPromptLine(source: string) {
  const parts = splitOnPlaceholders(source);
  return (
    <span>
      {parts.map((part, index) =>
        part.kind === "placeholder" ? (
          <span
            key={index}
            className="px-1 rounded bg-status-diagnosed/15 text-status-diagnosed font-mono"
          >
            {part.text}
          </span>
        ) : (
          <span key={index}>{part.text}</span>
        ),
      )}
    </span>
  );
}

interface ParsedPrompt {
  baseline: string;
  proposed: string;
}

interface PromptSegment {
  kind: "text" | "placeholder";
  text: string;
}

const BASELINE_HEADING = /^##\s+Baseline prompt\s*$/m;
const PROPOSED_HEADING = /^##\s+Prompt body\s*$/m;
const PLACEHOLDER = /\{\{[^}]+\}\}/g;

function parsePromptArtifact(markdown: string | null): ParsedPrompt | null {
  if (!markdown) {
    return null;
  }

  const proposed = extractCodeBlockAfter(markdown, PROPOSED_HEADING);
  if (proposed === null) {
    return null;
  }
  const baseline = extractCodeBlockAfter(markdown, BASELINE_HEADING) ?? "";
  return { baseline, proposed };
}

function extractCodeBlockAfter(markdown: string, heading: RegExp): string | null {
  const match = heading.exec(markdown);
  if (!match || match.index === undefined) {
    return null;
  }
  const tail = markdown.slice(match.index + match[0].length);
  const fenceMatch = /```[a-zA-Z0-9_-]*\n([\s\S]*?)\n```/.exec(tail);
  if (!fenceMatch) {
    return null;
  }
  return fenceMatch[1];
}

function splitOnPlaceholders(line: string): PromptSegment[] {
  const segments: PromptSegment[] = [];
  let cursor = 0;
  PLACEHOLDER.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = PLACEHOLDER.exec(line)) !== null) {
    if (match.index > cursor) {
      segments.push({ kind: "text", text: line.slice(cursor, match.index) });
    }
    segments.push({ kind: "placeholder", text: match[0] });
    cursor = match.index + match[0].length;
  }
  if (cursor < line.length) {
    segments.push({ kind: "text", text: line.slice(cursor) });
  }
  return segments.length > 0 ? segments : [{ kind: "text", text: line }];
}
