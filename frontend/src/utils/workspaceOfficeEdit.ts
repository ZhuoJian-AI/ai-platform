import type { WorkspaceOfficeEditStatus } from '../api/client';

export type WorkspaceOfficeEditOutcome =
  | { kind: 'pending' }
  | { kind: 'saved'; finalFileVersionId: string }
  | { kind: 'unchanged' }
  | { kind: 'failed'; error: string };

/**
 * Interpret only the status of the edit room that the user actually opened.
 * A logical file's current version may change for unrelated reasons and is
 * deliberately never accepted as proof that this room saved successfully.
 */
export function workspaceOfficeEditOutcome(
  value: WorkspaceOfficeEditStatus,
): WorkspaceOfficeEditOutcome {
  const status = String(value.save_status || value.status || '').trim().toLowerCase();
  if (value.final_file_version_id && ['closed', 'reconciled', 'saved', 'completed'].includes(status)) {
    return { kind: 'saved', finalFileVersionId: value.final_file_version_id };
  }
  if (['unchanged', 'no_changes', 'closed_without_changes'].includes(status)) {
    return { kind: 'unchanged' };
  }
  if (['failed', 'conflict', 'expired', 'rejected', 'cancelled'].includes(status)) {
    return { kind: 'failed', error: value.error || '平台未能把本次 WebOffice 编辑保存为文件版本' };
  }
  return { kind: 'pending' };
}
