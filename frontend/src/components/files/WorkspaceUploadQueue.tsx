import { useCallback, useMemo, useRef, useState, type ChangeEvent, type ReactNode } from 'react';
import { Badge, Popover, Progress, Typography } from 'antd';

import type { WorkspaceUploadOptions } from '../../api/client';

export const WORKSPACE_UPLOAD_BATCH_LIMIT = 5;

export function WorkspaceUploadPicker({
  children, disabled = false, onSelect, onLimitExceeded,
}: {
  children: ReactNode;
  disabled?: boolean;
  onSelect: (files: File[]) => void;
  onLimitExceeded?: (selectedCount: number) => void;
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);

  const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
    const selected = Array.from(event.currentTarget.files || []);
    // Reset immediately. A later selection is always a new batch and can be
    // appended while the previous batch is still uploading.
    event.currentTarget.value = '';
    if (!selected.length) return;
    if (selected.length > WORKSPACE_UPLOAD_BATCH_LIMIT) {
      onLimitExceeded?.(selected.length);
    }
    onSelect(selected.slice(0, WORKSPACE_UPLOAD_BATCH_LIMIT));
  };

  return (
    <span
      style={{ display: 'inline-flex' }}
      onClick={(event) => {
        if (disabled) {
          event.preventDefault();
          return;
        }
        inputRef.current?.click();
      }}
    >
      {children}
      <input
        ref={inputRef}
        type="file"
        multiple
        disabled={disabled}
        aria-label="上传文件，单次最多 5 个"
        onChange={handleChange}
        style={{ display: 'none' }}
      />
    </span>
  );
}

export interface WorkspaceUploadRequest {
  workspaceId: string;
  path: string;
  file: File;
  /** Set only after an explicit user confirmation to create a version in place. */
  targetFileId?: string;
  baseVersionId?: string;
  idempotencyKey?: string;
}

export type WorkspaceUploadQueueStatus = 'queued' | 'uploading' | 'validating' | 'success' | 'error';

export interface WorkspaceUploadQueueItem extends WorkspaceUploadRequest {
  id: string;
  progress: number;
  status: WorkspaceUploadQueueStatus;
  error?: string;
}

export function workspaceUploadErrorText(error: unknown): string {
  const candidate = error as { status?: unknown; message?: unknown; body?: unknown };
  const status = typeof candidate?.status === 'number' ? candidate.status : 0;
  const message = typeof candidate?.message === 'string' ? candidate.message : '';
  const detail = candidate?.body && typeof candidate.body === 'object'
    ? (candidate.body as { detail?: unknown }).detail
    : null;
  const code = detail && typeof detail === 'object'
    ? (detail as { code?: unknown }).code
    : null;
  if (status === 409 && code === 'workspace_file_version_conflict') {
    return '原文件刚被其他人更新，未覆盖对方版本；请刷新后重新确认';
  }
  if (status === 409 && code === 'workspace_file_active_edit_conflict') {
    return '该文件正在 WebOffice 协同编辑，未覆盖活动编辑内容；请稍后再试';
  }
  if (status === 409 && code === 'workspace_file_idempotency_conflict') {
    return '本次上传标识与先前操作冲突，未写入文件；请重新选择文件再试';
  }
  if (status === 409 && (code === 'workspace_file_path_conflict' || !message.includes('分片上传'))) {
    return '同路径文件已存在，未覆盖原文件；请刷新后确认作为新版本上传，或改名上传';
  }
  if (status === 403) return '权限已变更，当前无法上传或更新此文件';
  return message || '上传失败';
}

interface UseWorkspaceUploadQueueOptions<T> {
  upload: (request: WorkspaceUploadRequest, options: WorkspaceUploadOptions) => Promise<T>;
  onSuccess?: (value: T, request: WorkspaceUploadRequest) => void;
  onError?: (error: unknown, request: WorkspaceUploadRequest) => void;
  concurrency?: number;
}

/**
 * A persistent upload queue. Every file owns its own request and progress
 * callbacks, so choosing more files never replaces or aborts an in-flight
 * upload. A small concurrency cap keeps aggregate throughput high without
 * overwhelming the browser or OSS connection.
 */
export function useWorkspaceUploadQueue<T>({
  upload, onSuccess, onError, concurrency = 2,
}: UseWorkspaceUploadQueueOptions<T>) {
  const [items, setItems] = useState<WorkspaceUploadQueueItem[]>([]);
  const pendingRef = useRef<WorkspaceUploadQueueItem[]>([]);
  const activeRef = useRef(0);
  const uploadRef = useRef(upload);
  const successRef = useRef(onSuccess);
  const errorRef = useRef(onError);
  const pumpRef = useRef<() => void>(() => undefined);
  uploadRef.current = upload;
  successRef.current = onSuccess;
  errorRef.current = onError;

  const updateItem = useCallback((id: string, patch: Partial<WorkspaceUploadQueueItem>) => {
    setItems((current) => current.map((item) => item.id === id ? { ...item, ...patch } : item));
  }, []);

  const runItem = useCallback((item: WorkspaceUploadQueueItem) => {
    activeRef.current += 1;
    updateItem(item.id, { status: 'uploading', progress: 0, error: undefined });
    uploadRef.current(item, {
      onProgress: (progress) => updateItem(item.id, { progress, status: 'uploading' }),
      onUploadComplete: () => updateItem(item.id, { progress: 100, status: 'validating' }),
    })
      .then((value) => {
        updateItem(item.id, { progress: 100, status: 'success' });
        successRef.current?.(value, item);
      })
      .catch((error: unknown) => {
        updateItem(item.id, {
          status: 'error',
          error: workspaceUploadErrorText(error),
        });
        errorRef.current?.(error, item);
      })
      .finally(() => {
        activeRef.current -= 1;
        pumpRef.current();
      });
  }, [updateItem]);

  const pump = useCallback(() => {
    while (activeRef.current < concurrency && pendingRef.current.length > 0) {
      const next = pendingRef.current.shift();
      if (next) runItem(next);
    }
  }, [concurrency, runItem]);
  pumpRef.current = pump;

  const enqueue = useCallback((requests: WorkspaceUploadRequest[]) => {
    if (!requests.length) return;
    const created = requests.map((request, index): WorkspaceUploadQueueItem => ({
      ...request,
      id: `${Date.now()}-${index}-${crypto.randomUUID?.() || Math.random().toString(36).slice(2)}`,
      progress: 0,
      status: 'queued',
    }));
    pendingRef.current.push(...created);
    setItems((current) => [...current, ...created].slice(-30));
    queueMicrotask(() => pumpRef.current());
  }, []);

  const clearFinished = useCallback(() => {
    setItems((current) => current.filter((item) => !['success', 'error'].includes(item.status)));
  }, []);

  const activeCount = items.filter((item) => ['queued', 'uploading', 'validating'].includes(item.status)).length;
  const completedCount = items.filter((item) => item.status === 'success').length;
  const failedCount = items.filter((item) => item.status === 'error').length;
  const overallProgress = items.length
    ? Math.round(items.reduce((total, item) => total + item.progress, 0) / items.length)
    : 0;

  return {
    items, enqueue, clearFinished, activeCount, completedCount, failedCount, overallProgress,
  };
}

export function WorkspaceUploadQueueStatus({
  items, activeCount, completedCount, failedCount, overallProgress, onClearFinished,
}: {
  items: WorkspaceUploadQueueItem[];
  activeCount: number;
  completedCount: number;
  failedCount: number;
  overallProgress: number;
  onClearFinished: () => void;
}) {
  const visibleItems = useMemo(() => [...items].reverse(), [items]);
  if (!items.length) return null;

  const content = (
    <div style={{ width: 340, maxHeight: 320, overflowY: 'auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
        <Typography.Text strong>上传队列</Typography.Text>
        {(completedCount > 0 || failedCount > 0) && (
          <Typography.Link onClick={onClearFinished}>清除已完成</Typography.Link>
        )}
      </div>
      {visibleItems.map((item) => (
        <div key={item.id} style={{ marginBottom: 10 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
            <Typography.Text ellipsis style={{ maxWidth: 240 }} title={item.file.name}>
              {item.file.name}
            </Typography.Text>
            <Typography.Text type={item.status === 'error' ? 'danger' : 'secondary'} style={{ fontSize: 12 }}>
              {item.status === 'queued' ? '排队中'
                : item.status === 'uploading' ? `${item.progress}%`
                  : item.status === 'validating' ? '校验中'
                    : item.status === 'success' ? '已完成' : '失败'}
            </Typography.Text>
          </div>
          <Progress
            percent={item.progress}
            size="small"
            status={item.status === 'error' ? 'exception' : item.status === 'success' ? 'success' : 'active'}
            showInfo={false}
          />
          {item.error && <Typography.Text type="danger" style={{ fontSize: 11 }}>{item.error}</Typography.Text>}
        </div>
      ))}
    </div>
  );

  return (
    <Popover content={content} trigger="click" placement="bottomRight">
      <div style={{ width: 190, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8 }} title="点击查看每个文件的上传进度">
        <Badge count={activeCount} size="small" showZero={false}>
          <Typography.Text style={{ fontSize: 12, whiteSpace: 'nowrap' }}>
            {activeCount ? `上传中 ${activeCount} 个` : failedCount ? `${failedCount} 个失败` : `${completedCount} 个已完成`}
          </Typography.Text>
        </Badge>
        <Progress percent={overallProgress} size="small" showInfo={false} style={{ flex: 1, margin: 0 }} />
      </div>
    </Popover>
  );
}
