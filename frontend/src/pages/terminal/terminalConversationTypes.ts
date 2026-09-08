import type { TerminalTaskMessage, WorkspaceFileListItem, WorkspaceFileRefV1 } from '../../api/client';
import type { ApprovalCardData } from '../../components/terminal/ApprovalCard';

export type TraceCategory = 'rag' | 'memory' | 'skill' | 'file' | 'policy';

export type Block =
  | { kind: 'phase'; index: number }
  | { kind: 'tool_call'; id: string; name: string; arguments: string;
      running: boolean; result?: { content: string; ok: boolean } }
  | { kind: 'text'; content: string }
  | { kind: 'trace'; category: TraceCategory; title: string; detail?: unknown }
  | { kind: 'meta'; subtype: 'memory'; data: unknown }
  | ({ kind: 'approval' } & ApprovalCardData);

export interface InvokedSkill {
  id: string;
  name: string;
  slug: string;
  scope_type?: string;
}

export interface MessageAttachment {
  file_id: string;
  workspace_id: string;
  path: string;
  name: string;
}

export interface MessageFileRef extends WorkspaceFileRefV1 {
  workspace_id?: string;
  workspace_name?: string;
  workspace_slug?: string;
  path?: string;
  canonical_path?: string;
  current_version_no?: number | null;
}

export interface ChatFileLink {
  id: string;
  path: string;
  name: string;
  originalName: string;
  size: number;
  mimeType: string | null;
  parseStatus: WorkspaceFileListItem['parse_status'];
  updatedAt: string;
}

export interface ArtifactOutput {
  fileId: string;
  path: string;
  name: string;
  mimeType: string;
  size?: number;
  width?: number;
  height?: number;
  parseStatus?: string;
  sourceLabel?: string;
}

export interface ChatMsg {
  role: 'user' | 'assistant';
  content: string;
  createdAt?: string;
  blocks?: Block[];
  id?: string;
  agentName?: string | null;
  attachments?: MessageAttachment[];
  fileRefs?: MessageFileRef[];
  invokedSkills?: InvokedSkill[];
  executionVerification?: TerminalTaskMessage['execution_verification'];
  artifacts?: ArtifactOutput[];
}
