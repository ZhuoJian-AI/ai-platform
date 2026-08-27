import type { WorkspaceAuditEvent, WorkspaceFilePresentation } from '../api/client';

type DisplayableFile = {
  id: string;
  path: string;
  original_filename?: string;
  presentation?: WorkspaceFilePresentation;
};

export function workspaceDisplayName(file: DisplayableFile): string {
  if (file.presentation?.display_name) return file.presentation.display_name;
  if (file.original_filename) return file.original_filename;
  return file.path.split('/').pop() || file.path;
}

export function workspaceSourceLabel(file: DisplayableFile): string | null {
  const source = file.presentation;
  if (!source) return null;
  if (source.source_kind === 'skill') {
    return source.skill_display_name ? `由技能「${source.skill_display_name}」生成` : '由技能生成';
  }
  if (source.source_kind === 'platform_tool') return '由平台工具生成';
  return source.source_kind === 'upload' ? '用户上传' : null;
}

export function workspaceVisiblePath(file: DisplayableFile): string {
  const displayName = workspaceDisplayName(file);
  if (/^(?:技能输出|平台工具输出)\/[0-9a-f-]{36}\//i.test(file.path)) {
    const root = file.path.split('/')[0];
    const task = file.presentation?.source_task_title || '任务产物';
    return `${root}/${task}/${displayName}`;
  }
  return file.path;
}

const AUDIT_LABELS: Record<string, string> = {
  upload_initiated: '开始上传文件', upload_completed: '上传文件完成',
  file_created: '创建文件', file_updated: '更新文件', file_deleted: '删除文件',
  file_restored: '从回收站恢复文件', version_restored: '恢复历史版本',
  file_published: '发布文件', file_received: '接收跨部门文件', share_created: '创建分享链接',
  bulk_deleted: '批量删除文件', folder_created: '创建文件夹', folder_deleted: '删除文件夹',
};

export function auditTitle(event: WorkspaceAuditEvent): string {
  return AUDIT_LABELS[event.action] ?? '工作空间操作';
}

export function auditSummary(event: WorkspaceAuditEvent): string {
  const metadata = event.metadata ?? {};
  const candidate = metadata.display_name ?? metadata.filename ?? metadata.name ?? metadata.path ?? metadata.target_path;
  const filename = typeof candidate === 'string' ? candidate.split('/').pop() : null;
  const status = metadata.status === 'failed' ? '失败' : metadata.status === 'success' ? '成功' : null;
  const target = typeof metadata.target_path === 'string' ? `目标：${metadata.target_path.split('/').slice(0, -1).join('/') || '根目录'}` : null;
  return [event.actor_display_name || '系统', new Date(event.created_at).toLocaleString(), filename, target, status]
    .filter(Boolean).join(' · ');
}

export function redactArtifactIdentifiers(text: string, files: DisplayableFile[]): string {
  let result = text;
  for (const file of files) {
    const displayName = workspaceDisplayName(file);
    if (file.id) result = result.split(file.id).join(displayName);
    if (file.path) result = result.split(file.path).join(displayName);
  }
  return result
    .replace(
      /(?:技能输出|平台工具输出)\/[0-9a-f-]{36}\/\d{8}-\d{6}-[0-9a-f]{8}-([^\s|)]+)/gi,
      '$1',
    )
    .replace(/\bfile[_ -]?id\s*[:=：]?\s*[0-9a-f-]{36}\b/gi, '文件')
    .replace(/\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b/gi, '内部标识')
    .replace(/\b\d{8}-\d{6}-[0-9a-f]{8}-(?=[^\s|)]+)/gi, '');
}
