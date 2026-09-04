import { useEffect, useRef, useState } from 'react';
import { terminal, type WorkspaceFileEvent } from '../api/client';
import { advanceWorkspaceFileConnection, decodeWorkspaceFileStreamFrame } from '../utils/workspaceFileEvents';

type FileEventListener = (event: WorkspaceFileEvent) => void;
type FileStreamReadyListener = () => void;

/**
 * 监听当前员工有权看到的文件版本事件。
 *
 * 使用带 Authorization 的 fetch 流，而不是 EventSource；游标只用于当前页面会话，
 * 页面重新加载时工作空间查询会先取得最新快照，因此不会依赖 SSE 充当数据源。
 */
export function useWorkspaceFileEvents(
  enabled: boolean,
  onEvent: FileEventListener,
  onReady?: FileStreamReadyListener,
): WorkspaceFileEvent | null {
  const listenerRef = useRef(onEvent);
  const readyListenerRef = useRef(onReady);
  const [latest, setLatest] = useState<WorkspaceFileEvent | null>(null);
  listenerRef.current = onEvent;
  readyListenerRef.current = onReady;

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    let cursor = 0;
    let retryDelay = 500;

    const connect = async () => {
      while (!controller.signal.aborted) {
        try {
          const response = await terminal.streamWorkspaceFileEvents(cursor, controller.signal);
          if (response.status === 401 || response.status === 403) return;
          if (!response.ok || !response.body) throw new Error(`file event stream HTTP ${response.status}`);
          retryDelay = 500;
          const reader = response.body.getReader();
          const decoder = new TextDecoder();
          let buffer = '';
          let connectionState = { cursor, baselineHandled: false };
          const dispatchForConnection = (block: string) => {
            const frame = decodeWorkspaceFileStreamFrame(block);
            if (!frame) return;
            const step = advanceWorkspaceFileConnection(connectionState, frame);
            connectionState = step.state;
            cursor = step.state.cursor;
            if (step.refreshSnapshot) {
              // 列表快照可能早于 SSE baseline：每次连接以一次重新拉取封住这个竞态窗口。
              readyListenerRef.current?.();
            }
            if (!step.event) return;
            setLatest(step.event);
            listenerRef.current(step.event);
          };
          while (!controller.signal.aborted) {
            const { done, value } = await reader.read();
            buffer += decoder.decode(value, { stream: !done });
            const blocks = buffer.split(/\r?\n\r?\n/);
            buffer = blocks.pop() || '';
            blocks.forEach(dispatchForConnection);
            if (done) {
              if (buffer.trim()) dispatchForConnection(buffer);
              break;
            }
          }
        } catch (error) {
          if (controller.signal.aborted || (error as Error).name === 'AbortError') return;
        }
        await new Promise((resolve) => window.setTimeout(resolve, retryDelay));
        retryDelay = Math.min(retryDelay * 2, 15_000);
      }
    };

    void connect();
    return () => controller.abort();
  }, [enabled]);

  return latest;
}
