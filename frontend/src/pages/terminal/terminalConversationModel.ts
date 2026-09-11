import type { TerminalTaskMessage } from '../../api/client';
import type {
  ArtifactOutput, Block, ChatMsg, MessageAttachment, MessageFileRef, TraceCategory,
} from './terminalConversationTypes';

export async function consumeTerminalEventStream(
  response: Response,
  onEvent: (event: Record<string, unknown>) => void,
): Promise<void> {
  if (!response.body) throw new Error('任务执行连接没有返回数据流');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  const consumeLine = (line: string): boolean => {
    if (!line.startsWith('data: ')) return false;
    let event: Record<string, unknown>;
    try {
      event = JSON.parse(line.slice(6)) as Record<string, unknown>;
    } catch { /* 无法解析的控制行直接忽略 */
      return false;
    }
    onEvent(event);
    return event.type === 'final';
  };
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';
    for (const line of lines) {
      if (consumeLine(line)) {
        await reader.cancel().catch(() => undefined);
        return;
      }
    }
  }
  buffer += decoder.decode();
  if (buffer.trim()) consumeLine(buffer.trimEnd());
}


function messageAttachments(metadata: Record<string, unknown> | undefined): MessageAttachment[] {
  const raw = metadata?.attachments;
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((item) => {
    if (!item || typeof item !== 'object') return [];
    const value = item as Record<string, unknown>;
    const fileId = typeof value.file_id === 'string' ? value.file_id : '';
    const workspaceId = typeof value.workspace_id === 'string' ? value.workspace_id : '';
    const path = typeof value.path === 'string' ? value.path : '';
    if (!fileId || !workspaceId || !path) return [];
    return [{
      file_id: fileId,
      workspace_id: workspaceId,
      path,
      name: typeof value.name === 'string' && value.name ? value.name : (path.split('/').pop() || path),
    }];
  });
}

function messageFileRefs(metadata: Record<string, unknown> | undefined): MessageFileRef[] {
  const raw = metadata?.file_refs_v1;
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((item) => {
    if (!item || typeof item !== 'object') return [];
    const value = item as Record<string, unknown>;
    const fileId = typeof value.file_id === 'string' ? value.file_id : '';
    const scope = value.scope === 'task' ? 'task' : value.scope === 'turn' ? 'turn' : null;
    if (!fileId || !scope) return [];
    return [{
      file_id: fileId,
      scope,
      version_id: typeof value.version_id === 'string' ? value.version_id : undefined,
      follow_latest: typeof value.follow_latest === 'boolean' ? value.follow_latest : undefined,
      workspace_id: typeof value.workspace_id === 'string' ? value.workspace_id : undefined,
      workspace_name: typeof value.workspace_name === 'string' ? value.workspace_name : undefined,
      workspace_slug: typeof value.workspace_slug === 'string' ? value.workspace_slug : undefined,
      path: typeof value.path === 'string' ? value.path : undefined,
      canonical_path: typeof value.canonical_path === 'string' ? value.canonical_path : undefined,
      current_version_no: typeof value.current_version_no === 'number' ? value.current_version_no : undefined,
    }];
  });
}

export function messageFileRefLabel(ref: MessageFileRef): string {
  const path = ref.canonical_path || ref.path;
  if (!path) return `文件 ${ref.file_id.slice(0, 8)}…`;
  if (/^[^/]+:\//.test(path)) return path;
  const workspaceName = ref.workspace_name || ref.workspace_slug;
  return workspaceName ? `${workspaceName}:/${path.replace(/^\/+/, '')}` : path;
}


export function messageArtifacts(metadata: Record<string, unknown> | undefined): ArtifactOutput[] {
  const raw = metadata?.artifacts;
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((item) => {
    if (!item || typeof item !== 'object') return [];
    const value = item as Record<string, unknown>;
    const source = value.source && typeof value.source === 'object' ? value.source as Record<string, unknown> : {};
    const fileId = typeof value.file_id === 'string' ? value.file_id : '';
    const path = typeof value.workspace_path === 'string' ? value.workspace_path : '';
    if (!fileId && !path) return [];
    return [{
      fileId,
      versionId: typeof value.version_id === 'string' ? value.version_id : undefined,
      path,
      name: typeof value.display_name === 'string' ? value.display_name : '生成文件',
      mimeType: typeof value.mime_type === 'string' ? value.mime_type : '',
      size: typeof value.size === 'number' ? value.size : undefined,
      parseStatus: typeof value.parse_status === 'string' ? value.parse_status : undefined,
      sourceLabel: source.kind === 'skill' ? '历史平台产物' : '平台工具生成',
    }];
  });
}

/** Only consume structured server artifact events, never model text or tool prose. */
export function applyArtifactEvent(chat: ChatMsg[], event: Record<string, unknown>): ChatMsg[] {
  if (event.type !== 'artifact' && event.type !== 'final') return chat;
  const incoming = messageArtifacts({ artifacts: event.type === 'artifact' ? [event.artifact] : event.artifacts })
    .filter((artifact) => artifact.fileId && artifact.versionId);
  if (!incoming.length || chat[chat.length - 1]?.role !== 'assistant') return chat;
  const last = chat[chat.length - 1];
  const merged = new Map((last.artifacts || []).map((a) => [`${a.fileId}:${a.versionId || ''}`, a]));
  for (const artifact of incoming) merged.set(`${artifact.fileId}:${artifact.versionId}`, artifact);
  return [...chat.slice(0, -1), { ...last, artifacts: [...merged.values()] }];
}


/** 把后端持久化的 traces 数组还原为执行过程 blocks（历史回放用）。 */
function tracesToBlocks(traces: Record<string, unknown>[]): Block[] {
  const blocks: Block[] = [];
  for (const t of traces) {
    const category = t.category as TraceCategory;
    const title = (t.title as string) || category;
    // 所有真实工具轨迹都携带 name，并统一还原为工具调用卡片。
    if (t.name as string) {
      blocks.push({
        kind: 'tool_call',
        id: (t.id as string) || '',
        name: (t.name as string) || '',
        arguments: (t.arguments as string) || '',
        running: false,
        result: { content: (t.result as string) || '', ok: t.ok !== false },
      });
    } else {
      // detail 保留除 category/title 外的全部字段，供 TraceChip 展开查看
      const { category: _c, title: _t, ...rest } = t;
      blocks.push({ kind: 'trace', category, title, detail: rest });
    }
  }
  return blocks;
}

/** 把后端持久化的 TaskMessage 列表还原为前端 ChatMsg 数组（user 携带 id，assistant 重建 blocks）。
 *  抽出来供「选中任务回放」与「按轮删除后局部刷新」共用，避免逻辑重复。 */
export function restoreChat(messages: TerminalTaskMessage[]): ChatMsg[] {
  return messages
    .filter((m) => m.role === 'user' || m.role === 'assistant')
    .map((m) => {
      if (m.role !== 'assistant') {
        return {
          role: 'user', content: m.content, id: m.id,
          createdAt: m.created_at,
          attachments: messageAttachments(m.metadata),
          fileRefs: messageFileRefs(m.metadata),
        };
      }
      const traces = (m.metadata?.traces as Record<string, unknown>[] | undefined) ?? [];
      const blocks = traces.length ? tracesToBlocks(traces) : undefined;
      if (blocks && m.content) blocks.push({ kind: 'text', content: m.content });
      return {
        role: 'assistant' as const, content: m.content, blocks,
        createdAt: m.updated_at || m.created_at,
        executionVerification: m.execution_verification, artifacts: messageArtifacts(m.metadata),
      };
    });
}

/** 按 user 消息 id 删除一整轮对话（user 消息 + 紧随其后的 assistant 消息）的本地视图更新。
 *  与后端 soft_delete_task_turn 同步：只删除一对消息，已交付文件保持不变。 */
export function dropTurnFromChat(chat: ChatMsg[], userMsgId: string): ChatMsg[] {
  const idx = chat.findIndex((m) => m.role === 'user' && m.id === userMsgId);
  if (idx < 0) return chat;
  const next = chat.slice();
  // user 消息 + 其后紧跟的 assistant 消息；若该轮没有 assistant 回复（取消/失败），
  // 只删 user 消息，避免误删下一轮的 user 消息。
  next.splice(idx, next[idx + 1]?.role === 'assistant' ? 2 : 1);
  return next;
}

/** policy 类 trace 无 title 时按 action 给中文标题。 */
export const POLICY_TRACE_TITLE: Record<string, string> = {
  approval_requested: '高风险工具等待用户审批',
  approval_decided: '审批已有结果',
};
