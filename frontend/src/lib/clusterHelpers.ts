/**
 * Parse the member_spans_json column into a list of span ids. Returns
 * an empty list for malformed JSON so callers never branch on parse
 * errors. Shared by ClusterCard, ClusterDetailPage, and WrongMergePanel
 * so the three stay in agreement about what counts as a member.
 */
export function parseMemberSpans(json: string): string[] {
  try {
    const parsed: unknown = JSON.parse(json);
    return Array.isArray(parsed) ? parsed.map(String) : [];
  } catch {
    return [];
  }
}
