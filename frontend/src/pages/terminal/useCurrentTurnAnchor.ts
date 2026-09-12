import { useCallback, useEffect, useRef } from 'react';

/** Position once per turn/open, never follow token or media layout changes. */
export function useCurrentTurnAnchor(scope: string | null, turnCount: number, open = true) {
  const listRef = useRef<HTMLDivElement>(null);
  const jump = useCallback(() => {
    const turns = listRef.current?.querySelectorAll<HTMLElement>('[data-user-turn]');
    turns?.[turns.length - 1]?.scrollIntoView({ block: 'start', behavior: 'instant' });
  }, []);
  useEffect(() => {
    if (!open || !turnCount) return;
    const frame = requestAnimationFrame(jump);
    return () => cancelAnimationFrame(frame);
  }, [scope, turnCount, open, jump]);
  return { listRef, jump };
}
