import type { WorkspaceFile, WorkspaceFileListItem, WorkspaceFileRefV1, WorkspaceFileSummary } from '../api/client';

export type WorkspaceFileLike = Pick<WorkspaceFile, 'id' | 'workspace_id' | 'path'>
  & Partial<Pick<WorkspaceFile, 'workspace_name' | 'workspace_slug' | 'canonical_path' | 'internal_url'>>
  & Partial<Pick<WorkspaceFileListItem, 'original_filename'>>
  & Partial<Pick<WorkspaceFileSummary, 'presentation'>>;

const FILE_LINK_RE = /^\/f\/([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})\/?$/i;

export function workspaceFilePath(file: WorkspaceFileLike): string {
  return file.canonical_path || file.path;
}

export function workspaceFileLabel(file: WorkspaceFileLike): string {
  const path = workspaceFilePath(file);
  if (/^[^/]+:\//.test(path)) return path;
  const workspace = file.workspace_name || file.workspace_slug || file.workspace_id;
  return `${workspace}:/${path.replace(/^\/+/, '')}`;
}

export function workspaceInternalPath(fileId: string): string {
  return `/f/${encodeURIComponent(fileId)}`;
}

export function workspaceInternalUrl(file: WorkspaceFileLike, origin?: string, versionId?: string | null): string {
  const withVersion = (value: string) => {
    if (!versionId) return value;
    const url = new URL(value, origin || 'http://localhost');
    url.searchParams.set('version', versionId);
    return origin ? url.toString() : `${url.pathname}${url.search}`;
  };
  // 永久内部地址只由稳定 file ID 构造。后端的 internal_url 可以是相对地址，
  // 也不能让异常/陈旧主机名把复制链接带离当前 SaaS origin。
  const path = workspaceInternalPath(file.id);
  return withVersion(origin ? new URL(path, origin).toString() : path);
}

export function workspaceFileDestination(
  file: Pick<WorkspaceFileLike, 'id' | 'workspace_id'>,
  identity: { kind: 'admin' } | { kind: 'user'; organizationSlug: string },
  versionId?: string | null,
): string {
  const query = new URLSearchParams({
    view: 'workspace',
    workspace: file.workspace_id,
    file: file.id,
  });
  if (versionId) query.set('version', versionId);
  const base = identity.kind === 'user'
    ? `/${encodeURIComponent(identity.organizationSlug)}/terminal`
    : '/agent/workspaces';
  return `${base}?${query.toString()}`;
}

/** 只接受本站永久文件地址，避免把外站伪造的 /f/:id 当作已授权平台文件。 */
export function parseWorkspaceInternalUrl(raw: string, origin?: string): { fileId: string; versionId?: string } | null {
  const value = raw.trim();
  if (!value) return null;
  try {
    const base = origin || (typeof window !== 'undefined' ? window.location.origin : 'http://localhost');
    const url = new URL(value, base);
    if (url.origin !== new URL(base).origin) return null;
    const fileId = FILE_LINK_RE.exec(url.pathname)?.[1];
    if (!fileId) return null;
    const versionId = url.searchParams.get('version')?.trim() || undefined;
    return { fileId, versionId };
  } catch {
    return null;
  }
}

/** 新旧协议并发发送，旧服务忽略 file_refs_v1，新服务仍能处理 attachment_file_ids。 */
export function buildTaskRunFilePayload(attachmentFileIds: string[], fileRefs: WorkspaceFileRefV1[]) {
  return {
    attachment_file_ids: [...attachmentFileIds],
    file_refs_v1: fileRefs.map((ref) => ({ ...ref })),
  };
}
