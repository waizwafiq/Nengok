import { useCallback, useEffect, useState } from "react";

const FALLBACK_WIDTH = 560;

/**
 * Width of the chart's wrapping div, tracked with ResizeObserver. The
 * ref is a callback so the observer attaches even when the chart first
 * renders an empty state and the wrapper div mounts later. jsdom
 * (vitest) has no ResizeObserver and reports zero-size rects, so the
 * ref measures once and falls back to a fixed width there to keep
 * chart output deterministic in tests.
 */
export function useContainerWidth(
  fallback = FALLBACK_WIDTH,
): [(node: HTMLDivElement | null) => void, number] {
  const [node, setNode] = useState<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(fallback);

  const ref = useCallback(
    (next: HTMLDivElement | null) => {
      setNode(next);
      if (next && typeof ResizeObserver === "undefined") {
        setWidth(next.getBoundingClientRect().width || fallback);
      }
    },
    [fallback],
  );

  useEffect(() => {
    if (!node || typeof ResizeObserver === "undefined") {
      return;
    }
    const observer = new ResizeObserver((entries) => {
      const next = entries[0]?.contentRect.width;
      if (next) {
        setWidth(next);
      }
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [node]);

  return [ref, width];
}
