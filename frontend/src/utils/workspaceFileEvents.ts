import type { WorkspaceFileEvent } from '../api/client';

export interface WorkspaceFileStreamFrame {
  /** Highest outbox row covered by this frame, including the initial snapshot baseline. */
  cursor: number;
  /** Cursor-only frames are connection/progress markers, not business events. */
  event: WorkspaceFileEvent | null;
}

export interface WorkspaceFileConnectionState {
  cursor: number;
  baselineHandled: boolean;
}

export interface WorkspaceFileConnectionStep {
  state: WorkspaceFileConnectionState;
  event: WorkspaceFileEvent | null;
  refreshSnapshot: boolean;
}

/**
 * Apply one decoded frame to a single SSE connection.
 *
 * The first cursor-only frame always asks the caller to refresh its HTTP list
 * snapshot. Later cursor-only progress frames only advance the cursor, so a
 * long run of filtered (unauthorised) events is not scanned again on reconnect.
 */
export function advanceWorkspaceFileConnection(
  state: WorkspaceFileConnectionState,
  frame: WorkspaceFileStreamFrame,
): WorkspaceFileConnectionStep {
  if (frame.cursor < state.cursor) return { state, event: null, refreshSnapshot: false };
  const previousCursor = state.cursor;
  const nextState = { ...state, cursor: Math.max(state.cursor, frame.cursor) };
  if (!frame.event) {
    const refreshSnapshot = !state.baselineHandled;
    return { state: { ...nextState, baselineHandled: true }, event: null, refreshSnapshot };
  }
  const event = frame.event.id > previousCursor ? frame.event : null;
  return { state: nextState, event, refreshSnapshot: false };
}

/**
 * Parse one SSE block and reject malformed/untrusted payloads.
 *
 * A newly opened stream first emits a cursor-only frame. Advancing the browser
 * cursor before the first business event prevents a reconnect from taking a
 * second "start now" snapshot and skipping changes made during the disconnect.
 */
export function decodeWorkspaceFileStreamFrame(block: string): WorkspaceFileStreamFrame | null {
  const payload = block
    .split(/\r?\n/)
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trimStart())
    .join('\n');
  if (!payload) return null;
  try {
    const value = JSON.parse(payload) as Partial<WorkspaceFileEvent> & { cursor?: unknown };
    if (value.cursor !== undefined && (value.file_id === undefined || value.file_id === null)) {
      const cursor = Number(value.cursor);
      if (!Number.isSafeInteger(cursor) || cursor < 0) return null;
      return { cursor, event: null };
    }
    const id = Number(value.id);
    if (!Number.isSafeInteger(id) || id < 0 || typeof value.file_id !== 'string' || !value.file_id) return null;
    const event = {
      id,
      file_id: value.file_id,
      version_id: typeof value.version_id === 'string' && value.version_id ? value.version_id : null,
      event_type: typeof value.event_type === 'string' && value.event_type ? value.event_type : 'file_version_changed',
    };
    return { cursor: id, event };
  } catch {
    return null;
  }
}

/** Backwards-compatible event-only decoder used by focused unit tests/callers. */
export function decodeWorkspaceFileEvent(block: string): WorkspaceFileEvent | null {
  return decodeWorkspaceFileStreamFrame(block)?.event ?? null;
}
