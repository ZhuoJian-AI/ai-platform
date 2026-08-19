import {
  useCallback, useEffect, useRef, useState, forwardRef, useImperativeHandle, useMemo,
  type ChangeEvent, type CSSProperties, type DragEvent as ReactDragEvent,
  type Dispatch, type FormEvent, type KeyboardEvent, type ReactNode, type SetStateAction,
} from 'react';
import { useParams } from 'react-router-dom';
import {
  ConfigProvider, Button, Typography, Input, Tag, Drawer, Dropdown, Tabs, Empty, Spin,
  message, Tree, Avatar, Popover, Tooltip,
} from 'antd';
import {
  PlusOutlined, SendOutlined, RobotOutlined, SettingOutlined, FileTextOutlined,
  LogoutOutlined, DatabaseOutlined, PartitionOutlined,
  UnorderedListOutlined, BookOutlined, ApiOutlined,
  FolderOpenOutlined, MoreOutlined, ThunderboltOutlined,
  AppstoreOutlined, CheckCircleOutlined,
  RightOutlined, DownOutlined,
  LoadingOutlined, CloseOutlined, DeleteOutlined,
  SearchOutlined, UploadOutlined, EditOutlined, DownloadOutlined,
} from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  terminal, type TaskConfig, type TerminalTask, type TerminalTaskMessage,
  type TerminalResources, type TerminalMemoryItem, type TerminalModels, type TerminalAgent, type WorkspaceFileListItem,
  type TerminalTaskWithMessages,
  type SkillFolderSummary, type WorkspaceFileSummary,
} from '../../api/client';
import { useUserAuth } from '../../context/UserAuthContext';
import TaskConfigDrawer from './TaskConfigDrawer';
import BrowserDrawer, { classifyFile, classifyUrl, type Source } from './BrowserDrawer';
import WorkspaceManagerView from './WorkspaceManagerView';
import KnowledgeBaseView from './KnowledgeBaseView';
import SkillManagerView from './SkillManagerView';
import AgentManagerView from './AgentManagerView';
import DataInterfaceView from './DataInterfaceView';
import OntologyView from './OntologyView';
import ConfirmModal from '../../components/finder/ConfirmModal';

/** WorkBuddy 配色（参考 HTML 的 tailwind theme）。 */
const WB = {
  primary: '#6366F1',
  primaryHover: '#818CF8',
  sidebar: '#F8F9FC',
  hover: '#EEF0F7',
  border: '#E5E7EB',
  userMsg: '#F0F1F5',
  botMsg: '#FFFFFF',
};

/** 统一字体栈：含中文回退字体，供 ConfigProvider token 与根容器共用，
 *  让「任务资源配置」抽屉与任务输入框的字体类型/大小/颜色保持一致。 */
const WB_FONT = '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif';

const DEFAULT_CONFIG: TaskConfig = {
  workspace_id: null,
  model_alias: null,
  exec_mode: 'craft',
};

// ── 执行过程时间线 block 模型 ──────────────────────────────────────────
type TraceCategory = 'rag' | 'ontology' | 'memory' | 'data_interface' | 'skill' | 'file';
type Block =
  | { kind: 'phase'; index: number }
  | { kind: 'tool_call'; id: string; name: string; arguments: string;
      running: boolean; result?: { content: string; ok: boolean } }
  | { kind: 'text'; content: string }
  | { kind: 'trace'; category: TraceCategory; title: string; detail?: unknown }
  | { kind: 'meta'; subtype: 'memory' | 'judge'; data: unknown };

interface ChatMsg {
  role: 'user' | 'assistant';
  content: string;       // 终答文本（历史回放用；实时渲染走 blocks）
  blocks?: Block[];      // 实时执行过程（仅本轮 live 会有）
  id?: string;           // user 消息 ID（DB 回放后携带；用于按轮删除对话）
  // 该轮用户消息发送时选中的智能体名（逐次覆盖，不落库；仅本轮 live 气泡展示，历史回放无）。
  agentName?: string | null;
  attachments?: MessageAttachment[];
}

interface MessageAttachment {
  file_id: string;
  workspace_id: string;
  path: string;
  name: string;
}

type ComposerAttachmentStatus = 'uploading' | 'parsing' | 'ready' | 'failed';

interface ComposerAttachment extends MessageAttachment {
  client_id: string;
  file: File;
  file_id: string;
  status: ComposerAttachmentStatus;
  progress: number;
  error?: string;
}

const MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024;
const MAX_ATTACHMENTS = 10;
const MAX_UPLOAD_CONCURRENCY = 3;

function safeAttachmentName(name: string): string {
  const cleaned = name.replace(/[\\/:*?"<>|\u0000-\u001f]/g, '_').trim() || '未命名文件';
  return cleaned.length <= 180 ? cleaned : cleaned.slice(cleaned.length - 180);
}

function attachmentPath(scopeKey: string, name: string): string {
  const stamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d{3}Z$/, 'Z');
  return `会话附件/${scopeKey}/${stamp}-${crypto.randomUUID().slice(0, 8)}-${safeAttachmentName(name)}`;
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

/** 把后端持久化的 traces 数组还原为执行过程 blocks（历史回放用）。
 *  skill → tool_call block（复用 ToolCard 展示）；其余四类 → trace block（TraceChip 展示）。
 *  仅还原资源调用痕迹；终答正文由调用方末尾补一条 text block（见上方回放 map）。 */
function tracesToBlocks(traces: Record<string, unknown>[]): Block[] {
  const blocks: Block[] = [];
  for (const t of traces) {
    const category = t.category as TraceCategory;
    const title = (t.title as string) || category;
    if (category === 'skill' && (t.name as string)) {
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
function restoreChat(messages: TerminalTaskMessage[]): ChatMsg[] {
  return messages
    .filter((m) => m.role === 'user' || m.role === 'assistant')
    .map((m) => {
      if (m.role !== 'assistant') {
        return { role: 'user', content: m.content, id: m.id, attachments: messageAttachments(m.metadata) };
      }
      const traces = (m.metadata?.traces as Record<string, unknown>[] | undefined) ?? [];
      const blocks = traces.length ? tracesToBlocks(traces) : undefined;
      if (blocks && m.content) blocks.push({ kind: 'text', content: m.content });
      return { role: 'assistant' as const, content: m.content, blocks };
    });
}

/** 按 user 消息 id 删除一整轮对话（user 消息 + 紧随其后的 assistant 消息）的本地视图更新。
 *  与后端 soft_delete_task_turn 同步：删除一对消息，工作空间文件由后端负责清理。 */
function dropTurnFromChat(chat: ChatMsg[], userMsgId: string): ChatMsg[] {
  const idx = chat.findIndex((m) => m.role === 'user' && m.id === userMsgId);
  if (idx < 0) return chat;
  const next = chat.slice();
  next.splice(idx, 2); // user 消息 + 其后紧跟的 assistant 消息
  return next;
}

const COMPOSER_PLACEHOLDER = '描述你要完成的任务…通用智能体将调用技能、读写工作空间文件、参考知识库与记忆来执行。';

/** 执行模式：Craft 自主执行 / Ask 只读问答 / Plan 出方案不执行。 */
const EXEC_MODES: { key: TaskConfig['exec_mode']; label: string; desc: string }[] = [
  { key: 'craft', label: 'Craft 动手', desc: '自主多步执行：读写工作空间、调用技能' },
  { key: 'ask', label: 'Ask 问答', desc: '只读单轮问答，不调用工具、不改文件' },
  { key: 'plan', label: 'Plan 规划', desc: '产出分步计划，不执行' },
];
const EXEC_LABEL: Record<TaskConfig['exec_mode'], string> = { craft: 'Craft', ask: 'Ask', plan: 'Plan' };

/** WorkBuddy 风格两栏：窗口标题栏 / 左侧栏（新建+任务列表+用户）/ 右侧主区（首页欢迎 or 聊天）。 */
export default function Terminal() {
  const { slug = '' } = useParams<{ slug: string }>();
  const { user, logout } = useUserAuth();
  const qc = useQueryClient();

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  // 删除确认弹窗：界面正中模态框（统一用共享 ConfirmModal）。
  const [delConfirm, setDelConfirm] = useState<{ id: string; title: string } | null>(null);
  // 删除单轮对话确认弹窗：删一整轮 user+assistant，并清理本轮产出文件。
  const [turnDelConfirm, setTurnDelConfirm] = useState<{ taskId: string; messageId: string } | null>(null);
  // 任务重命名：内联编辑，Enter 保存、Esc 取消、失焦保存
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState('');
  const [chat, setChat] = useState<ChatMsg[]>([]);
  const [traceLog, setTraceLog] = useState<Record<string, unknown>[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [activeTab, setActiveTab] = useState('resources');
  const abortRef = useRef<AbortController | null>(null);
  // 标记「本次选中是刚创建并立即 live 执行的任务」——此时 chat 由 runStream 实时维护，
  // 不应从 DB 回放（任务在执行结束前还没有 TaskMessage，回放会用空消息清掉实时轨迹）。
  const skipRestoreRef = useRef(false);
  // 重连去重：记录正在 resume 的 task id，避免 useEffect 重入重复调 GET /stream。
  const reconnRef = useRef<string | null>(null);

  // 新建任务作曲器
  const [composerOpen, setComposerOpen] = useState(true);
  const [input, setInput] = useState('');
  const [inputAttachments, setInputAttachments] = useState<ComposerAttachment[]>([]);
  const [draftAttachmentKey, setDraftAttachmentKey] = useState(() => crypto.randomUUID());
  const [config, setConfig] = useState<TaskConfig>(DEFAULT_CONFIG);
  const [cfgOpen, setCfgOpen] = useState(false);
  // 终端「选智能体」逐次覆盖（不落库）：选中后随 /run 发送；null=通用智能体。
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);

  // 左侧功能菜单视图：助理（任务对话）/ 工作空间 / 知识库 / 数据接口
  const [view, setView] = useState<'assistant' | 'workspaces' | 'agents' | 'knowledge' | 'skills' | 'ontology' | 'data_interface'>('assistant');

  // 跟随输入（选中任务后的对话）
  const [followUp, setFollowUp] = useState('');
  const [followUpAttachments, setFollowUpAttachments] = useState<ComposerAttachment[]>([]);

  // 浏览器抽屉：点击对话内容中的文件/链接时弹出，内嵌浏览器可预览网页与文档
  const [browserOpen, setBrowserOpen] = useState(false);
  const [browserHref, setBrowserHref] = useState<string | null>(null);
  // 每次打开自增，作为抽屉 key 强制重置内部历史栈（兼容连续点击同一链接）
  const [browserSeq, setBrowserSeq] = useState(0);

  const { data: resources } = useQuery<TerminalResources>({
    queryKey: ['terminal-resources'], queryFn: () => terminal.resources(),
  });
  const { data: modelData } = useQuery<TerminalModels>({
    queryKey: ['terminal-models'], queryFn: () => terminal.models(),
  });
  const { data: agentsList = [] } = useQuery<TerminalAgent[]>({
    queryKey: ['terminal-task-agent-options'],
    queryFn: async () => (await terminal.agents()).agents,
  });
  // 智能体 chip 文案：选中显示名称，未选=通用智能体。
  const agentLabel = selectedAgentId
    ? (agentsList.find((a) => a.id === selectedAgentId)?.name ?? '已选')
    : '通用';
  const { data: memoryList } = useQuery<TerminalMemoryItem[]>({
    queryKey: ['terminal-memory'], queryFn: () => terminal.memory(),
  });
  const { data: tasks } = useQuery<TerminalTask[]>({
    queryKey: ['terminal-tasks'], queryFn: () => terminal.listTasks(),
  });
  const { data: selectedTask } = useQuery<TerminalTaskWithMessages>({
    queryKey: ['terminal-task', selectedId],
    queryFn: () => terminal.getTask(selectedId!),
    enabled: !!selectedId,
  });

  useEffect(() => {
    if (!selectedTask) return;
    // 刚创建并立即 live 执行的任务：chat 由 runStream 实时维护，跳过 DB 回放，仅切到聊天视图。
    if (skipRestoreRef.current) {
      skipRestoreRef.current = false;
      setComposerOpen(false);
      return;
    }
    setChat(restoreChat(selectedTask.messages));
    setTraceLog([]);
    setComposerOpen(false);
    // 该任务有运行中的 run（后台 detach 执行）→ 自动重连：回放已产出事件 + 续接到 final。
    // 刷新页面/切走再回来不丢进度。reconnRef 防止 useEffect 重入重复发起 GET /stream。
    if (
      selectedTask.run_status === 'running' &&
      reconnRef.current !== selectedTask.id &&
      !abortRef.current
    ) {
      reconnRef.current = selectedTask.id;
      // reconnectStream 内部 finally 会清 abortRef；reconnRef 在此去重即可（同 id 不会重入）
      void reconnectStream(selectedTask.id).finally(() => {
        if (reconnRef.current === selectedTask.id) reconnRef.current = null;
      });
    }
  }, [selectedTask?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // 切换到已存在任务时，按 task.config.template_agent_id 预填「选智能体」（不落库，仅 UI 默认）。
  // 刚创建并 live 执行的任务跳过：保留作曲器里用户选的智能体，不被新任务空 config 重置为通用。
  useEffect(() => {
    if (skipRestoreRef.current) return;
    setSelectedAgentId(selectedTask?.config?.template_agent_id ?? null);
  }, [selectedTask?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // 每次打开「任务资源配置」抽屉时，强制刷新工作空间/技能/RAG/本体 与模型清单，
  // 避免使用 react-query 缓存中的旧数据。
  useEffect(() => {
    if (cfgOpen) {
      qc.invalidateQueries({ queryKey: ['terminal-resources'] });
      qc.invalidateQueries({ queryKey: ['terminal-models'] });
      qc.invalidateQueries({ queryKey: ['terminal-task-agent-options'] });
    }
  }, [cfgOpen, qc]);

  // 组件卸载：显式中断 SSE 读端（SPA 导航也干净）。后台 detach run 不受影响，可经 resume 重连。
  useEffect(() => () => { abortRef.current?.abort(); }, []);

  // 终端门户 tab 图标用 terminal-icon.png，离开时还原为管理端 admin-icon.png
  useEffect(() => {
    const link = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
    if (!link) return;
    const prev = link.href;
    link.href = '/terminal-icon.png';
    return () => { link.href = prev; };
  }, []);

  // 作曲器打开后，按后端 /resources.defaults 预填默认装配：默认工作空间=个人工作空间，
  // 默认模型=最近一次使用的模型。每次进入作曲器仅填一次，用户清空后不重填。
  const wsDefaultedRef = useRef(false);
  useEffect(() => {
    if (!composerOpen) { wsDefaultedRef.current = false; return; }
    if (resources && !wsDefaultedRef.current) {
      const dft = resources.defaults;
      setConfig((c) => ({
        ...c,
        workspace_id: c.workspace_id ?? (dft?.workspace_id ?? null),
        model_alias: c.model_alias ?? (dft?.model_alias ?? null),
      }));
      wsDefaultedRef.current = true;
    }
  }, [composerOpen, resources]); // eslint-disable-line react-hooks/exhaustive-deps

  // 更新当前 assistant 回合的 blocks（不可变）
  const updateTurn = useCallback((fn: (blocks: Block[]) => Block[]) => {
    setChat((c) => {
      const next = [...c];
      const last = next[next.length - 1];
      if (last && last.role === 'assistant') {
        next[next.length - 1] = { ...last, blocks: fn(last.blocks ?? []) };
      }
      return next;
    });
  }, []);

  // 单事件派发：POST /run 与 GET /stream（resume）共用，确保刷新重连后渲染一致。
  const dispatchEvent = useCallback((evt: Record<string, unknown>) => {
    setTraceLog((t) => [...t, evt]);
    switch (evt.type) {
      case 'phase': {
        const idx = (evt.index as number) ?? 0;
        updateTurn((bs) => {
          // 末块若已是同 index 的 phase（乐观占位或重复下发），替换而非追加，避免两个「第 N 步」。
          const last = bs[bs.length - 1];
          if (last && last.kind === 'phase' && last.index === idx) {
            return [...bs.slice(0, -1), { kind: 'phase', index: idx }];
          }
          return [...bs, { kind: 'phase', index: idx }];
        });
        break;
      }
      case 'text': {
        const delta: string = (evt.delta as string) ?? '';
        updateTurn((bs) => {
          const next = [...bs];
          const last = next[next.length - 1];
          if (last && last.kind === 'text') {
            next[next.length - 1] = { ...last, content: last.content + delta };
          } else {
            next.push({ kind: 'text', content: delta });
          }
          return next;
        });
        break;
      }
      case 'tool_call':
        updateTurn((bs) => [...bs, {
          kind: 'tool_call', id: (evt.id as string) ?? '', name: (evt.name as string) ?? '',
          arguments: (evt.arguments as string) ?? '', running: true,
        }]);
        break;
      case 'tool_result':
        updateTurn((bs) => {
          const next = [...bs];
          for (let j = next.length - 1; j >= 0; j--) {
            const b = next[j];
            if (b.kind === 'tool_call' && b.id === evt.id && b.running) {
              next[j] = { ...b, running: false,
                result: { content: (evt.content as string) ?? '', ok: evt.ok !== false } };
              break;
            }
          }
          return next;
        });
        break;
      case 'trace': {
        // 五类资源调用痕迹（rag/ontology/memory/data_interface）；技能走 tool_call 不走此分支
        const { category: _c, title: _t, ...rest } = evt as Record<string, unknown>;
        updateTurn((bs) => [...bs, {
          kind: 'trace',
          category: (evt.category as TraceCategory) ?? 'rag',
          title: (evt.title as string) ?? (evt.category as string) ?? '',
          detail: rest,
        }]);
        break;
      }
      case 'judge':
        updateTurn((bs) => [...bs, { kind: 'meta', subtype: 'judge', data: evt }]);
        break;
      case 'error':
        message.error(evt.message as string);
        updateTurn((bs) => [...bs, { kind: 'text', content: `⚠️ ${evt.message}` }]);
        break;
      // 'done' / 'final' / 'step' (legacy) — 无需特殊渲染
      default:
        break;
    }
  }, [updateTurn]);

  // SSE 读取循环：解析 `data: {...}` 行并派发。POST /run 与 GET /stream 共用。
  const consumeSSE = useCallback(async (resp: Response) => {
    const reader = resp.body!.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop() || '';
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try {
          const evt = JSON.parse(line.slice(6));
          dispatchEvent(evt);
        } catch { /* 半行/非 JSON：忽略，下轮补全 */ }
      }
    }
  }, [dispatchEvent]);

  const runStream = useCallback(async (taskId: string, msg: string, attachments: MessageAttachment[] = []) => {
    // 乐观载入：立即显示用户消息 + 一个「思考中」回合，第一时间给反馈
    // 该轮若选了智能体，把智能体名挂到用户消息上，气泡内按技能 chip 同款展示（逐次覆盖、不落库）。
    const turnAgentName = selectedAgentId ? agentLabel : null;
    setChat((c) => [
      ...c,
      { role: 'user', content: msg, agentName: turnAgentName, attachments },
      { role: 'assistant', content: '', blocks: [{ kind: 'phase', index: 0 }] },
    ]);
    setTraceLog([]);
    setStreaming(true);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const resp = await terminal.runTaskStream(
        taskId, msg, controller.signal, selectedAgentId, attachments.map((item) => item.file_id),
      );
      if (!resp.ok || !resp.body) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${resp.status}`);
      }
      await consumeSSE(resp);
      qc.invalidateQueries({ queryKey: ['terminal-tasks'] });
      qc.invalidateQueries({ queryKey: ['terminal-task', taskId] });
      qc.invalidateQueries({ queryKey: ['terminal-memory'] });
      // 刷新工作空间文件清单：让本轮新生成的文件在对话正文里变为可点击
      qc.invalidateQueries({ queryKey: ['terminal-ws-files'] });
      // 流式结束后从 DB 回填 user 消息 id 到 live chat，让该轮对话的删除按钮立即可用。
      // 不替换 blocks——保留实时执行过程展示；仅补 id。
      try {
        const fresh = await terminal.getTask(taskId);
        const dbUsers = fresh.messages.filter((m) => m.role === 'user');
        let idx = 0;
        setChat((c) => c.map((m) => {
          if (m.role !== 'user') return m;
          const dbm = dbUsers[idx++];
          return dbm ? { ...m, id: dbm.id } : m;
        }));
      } catch { /* 回填失败不影响展示 */ }
    } catch (e) {
      if ((e as Error).name !== 'AbortError') {
        message.error((e as Error).message);
        updateTurn((bs) => [...bs, { kind: 'text', content: `⚠️ ${(e as Error).message}` }]);
      }
    } finally {
      setStreaming(false);
      // 仅当仍持本读端时清空，避免误清掉切换后新接入的 SSE 读端（切走/切回竞态）。
      if (abortRef.current === controller) abortRef.current = null;
    }
  }, [qc, updateTurn, consumeSSE, selectedAgentId, agentLabel]);

  // resume：后台 detach 执行，刷新/切走再回来时重连——回放已产出事件 + 续接到 final。
  // chat 已由 useEffect 从 DB 回放（运行中那轮尚无 assistant 消息），这里追加一个 assistant 占位让事件填充。
  const reconnectStream = useCallback(async (taskId: string) => {
    setChat((c) => {
      // 已有运行中 assistant 占位则不重复追加（防 useEffect 重入）
      const last = c[c.length - 1];
      if (last && last.role === 'assistant') return c;
      return [...c, { role: 'assistant', content: '', blocks: [{ kind: 'phase', index: 0 }] }];
    });
    setTraceLog([]);
    setStreaming(true);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const resp = await terminal.streamTask(taskId, controller.signal);
      if (!resp.ok || !resp.body) {
        // 404/无 run：静默（可能 run 已结束、resume 端点查无记录）
        return;
      }
      await consumeSSE(resp);
      qc.invalidateQueries({ queryKey: ['terminal-tasks'] });
      qc.invalidateQueries({ queryKey: ['terminal-task', taskId] });
    } catch (e) {
      if ((e as Error).name !== 'AbortError') {
        // resume 失败不弹错（避免刷新后无 run 的任务报扰），仅留 DB 回放
      }
    } finally {
      setStreaming(false);
      // 仅当仍持本读端时清空，避免误清掉切换后新接入的 SSE 读端（切走/切回竞态）。
      if (abortRef.current === controller) abortRef.current = null;
    }
  }, [qc, consumeSSE]);

  // 断开当前 SSE 读端（仅断前端读，后台 detach run 不受影响，可经 resume GET /stream 回放续接）。
  // 切换任务/新建任务时必须调用：不 abort 则 abortRef 一直被旧读端占用，切回运行中任务时
  // useEffect 里的 reconnect 会被 `!abortRef.current` 跳过，实时执行过程丢失。
  const abortActiveStream = useCallback(() => {
    const c = abortRef.current;
    if (c) {
      c.abort();
      abortRef.current = null;
    }
    setStreaming(false);
  }, []);

  // 统一任务选择入口：切到不同任务前先断开当前 SSE 读端，保证切回运行中任务时可重连回放。
  const selectTask = useCallback(async (id: string | null) => {
    if (id !== selectedId) abortActiveStream();
    if (id !== selectedId) setFollowUpAttachments([]);
    if (id) {
      // 强制抓最新任务数据再切换，避免用 react-query 旧缓存回放：
      // 任务首次选中（createTask+runStream 起步瞬间）抓到的缓存里 run_status 尚非 running、
      // 也无 user 消息；切走再切回时 useEffect 只依赖 selectedTask.id（不变→不重跑），
      // 就会拿这份陈旧缓存 restoreChat→空、且不触发重连，导致看不到提示词与执行过程。
      // fetchQuery(staleTime:0) 强制刷新该 key 缓存，使下方 setSelectedId 后 effect 首次触发即拿到 fresh。
      try {
        await qc.fetchQuery({
          queryKey: ['terminal-task', id],
          queryFn: () => terminal.getTask(id),
          staleTime: 0,
        });
      } catch { /* 抓取失败交给 useQuery 兜底，不影响切换 */ }
    }
    setSelectedId(id);
  }, [selectedId, abortActiveStream, qc]);

  const stopStream = () => {
    abortRef.current?.abort();
    setStreaming(false);
    // 真停后台 detach 任务（非仅断读端），避免 run 继续耗 LLM 配额
    if (selectedId) terminal.cancelTask(selectedId).catch(() => { /* 静默 */ });
  };

  const exportSkillsPack = async () => {
    const hide = message.loading('正在即时生成 skills 包…', 0);
    try {
      await terminal.exportSkillsPack();
      message.success('skills 包已下载（鉴权已内嵌，解压即可给第三方智能体终端使用）');
    } catch (e) {
      message.error(`导出失败：${(e as Error).message}`);
    } finally {
      hide();
    }
  };

  const startTask = async () => {
    const readyAttachments = inputAttachments.filter((item) => item.status === 'ready' && item.file_id);
    if ((!input.trim() && !readyAttachments.length) || streaming) return;
    if (!config.model_alias) {
      message.warning('请先选择模型后再执行');
      setCfgContext('composer'); setCfgOpen(true);
      return;
    }
    const msg = input.trim() || `请分析附件：${readyAttachments.map((item) => item.name).join('、')}`;
    const attachmentSnapshots: MessageAttachment[] = readyAttachments.map(({ file_id, workspace_id, path, name }) => ({
      file_id, workspace_id, path, name,
    }));
    try {
      const task = await terminal.createTask({ title: msg.slice(0, 60), message: msg, config });
      // 新建后立即让左栏任务列表可见（不再等流结束才 invalidate）——根治「执行期间左栏看不到任务」诱因。
      qc.invalidateQueries({ queryKey: ['terminal-tasks'] });
      // 标记本次选中是「新建并立即 live 执行」，阻止 selectedTask 回放清掉实时轨迹；
      // 同时立即切到聊天视图，让用户第一时间看到执行过程。
      skipRestoreRef.current = true;
      setComposerOpen(false);
      setSelectedId(task.id);
      setInput('');
      setInputAttachments([]);
      await runStream(task.id, msg, attachmentSnapshots);
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  const sendFollowUp = async () => {
    const readyAttachments = followUpAttachments.filter((item) => item.status === 'ready' && item.file_id);
    if (!selectedId || (!followUp.trim() && !readyAttachments.length) || streaming) return;
    if (!taskConfig.model_alias) {
      message.warning('请先选择模型后再执行');
      setCfgContext('chat'); setCfgOpen(true);
      return;
    }
    const msg = followUp.trim() || `请分析附件：${readyAttachments.map((item) => item.name).join('、')}`;
    const attachmentSnapshots: MessageAttachment[] = readyAttachments.map(({ file_id, workspace_id, path, name }) => ({
      file_id, workspace_id, path, name,
    }));
    setFollowUp('');
    setFollowUpAttachments([]);
    await runStream(selectedId, msg, attachmentSnapshots);
  };

  const newTask = () => {
    // 断开当前 SSE 读端，否则切回运行中任务时 reconnect 被 !abortRef.current 跳过，执行过程消失。
    abortActiveStream();
    skipRestoreRef.current = false;
    setSelectedId(null);
    setChat([]);
    setTraceLog([]);
    setComposerOpen(true);
    setInput('');
    setInputAttachments([]);
    setFollowUpAttachments([]);
    setDraftAttachmentKey(crypto.randomUUID());
    setConfig(DEFAULT_CONFIG);
    setView('assistant');
  };

  const deleteTask = async (id: string) => {
    try {
      await terminal.deleteTask(id);
      qc.invalidateQueries({ queryKey: ['terminal-tasks'] });
      if (selectedId === id) newTask();
      message.success('已删除任务及其工作空间输出文件');
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  const deleteTurn = async (taskId: string, messageId: string) => {
    try {
      await terminal.deleteTaskMessage(taskId, messageId);
      // 乐观更新本地 chat：立即移除该轮对话，避免等回放闪烁
      setChat((c) => dropTurnFromChat(c, messageId));
      // 刷新工作空间文件清单（本轮产出文件已被后端软删除）与任务列表
      const wsId = (selectedTask?.config ?? config).workspace_id;
      qc.invalidateQueries({ queryKey: ['terminal-task', taskId] });
      if (wsId) qc.invalidateQueries({ queryKey: ['terminal-ws-files', wsId] });
      message.success('已删除该轮对话及本轮产出文件');
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  const startRename = (t: TerminalTask) => {
    setEditingId(t.id);
    setEditingTitle(t.title || '');
  };

  const cancelRename = () => {
    setEditingId(null);
    setEditingTitle('');
  };

  const commitRename = async (taskId: string) => {
    const newTitle = editingTitle.trim();
    if (!editingId) return;
    if (!newTitle || newTitle === (tasks?.find((t) => t.id === taskId)?.title ?? '')) {
      cancelRename();
      return;
    }
    try {
      await terminal.updateTask(taskId, { title: newTitle.slice(0, 255) });
      qc.invalidateQueries({ queryKey: ['terminal-tasks'] });
      if (selectedId === taskId) qc.invalidateQueries({ queryKey: ['terminal-task', taskId] });
      message.success('已重命名');
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      cancelRename();
    }
  };

  const taskConfig = selectedTask?.config ?? config;
  // 当前任务工作空间的文件清单：用于把对话正文中提到的裸文件名自动链成可点击链接
  const { data: wsFiles } = useQuery<WorkspaceFileListItem[]>({
    queryKey: ['terminal-ws-files', taskConfig.workspace_id],
    queryFn: () => terminal.listWsFiles(taskConfig.workspace_id!),
    enabled: !!taskConfig.workspace_id,
  });
  // 文件名 → 路径映射，供 linkifyFiles 在消息正文里识别裸文件名
  const fileLinks = (wsFiles ?? []).map((f) => ({
    path: f.path,
    name: f.path.split('/').pop() || f.path,
  }));
  // 跨工作空间文件清单（与 @ 选择器同源），供用户消息气泡把 @fileId 还原为文件路径
  const { data: allWsFiles } = useQuery<WorkspaceFileSummary[]>({
    queryKey: ['terminal-all-ws-files'],
    queryFn: () => terminal.listAllWsFiles(),
  });
  const fileRefMap = useMemo(() => {
    const m = new Map<string, string>();
    (allWsFiles ?? []).forEach((f) => m.set(f.id, f.path));
    return m;
  }, [allWsFiles]);
  const userName = user?.display_name || user?.username || '用户';
  const userInitial = userName.slice(0, 1);

  // 资源配置抽屉的编辑上下文：作曲器（新任务）or 聊天（已存在任务，PATCH 落库）
  const [cfgContext, setCfgContext] = useState<'composer' | 'chat'>('composer');
  const patchTaskConfig = useCallback(async (c: TaskConfig) => {
    if (!selectedId) return;
    // 智能体为逐次运行覆盖、不落库：PATCH 前剥掉 template_agent_id，避免回写进 task.config。
    const { template_agent_id: _tpl, ...cfgRest } = c;
    void _tpl;
    try {
      await terminal.updateTask(selectedId, { config: cfgRest });
    } catch (e) {
      message.error((e as Error).message);
      return;
    }
    qc.invalidateQueries({ queryKey: ['terminal-task', selectedId] });
  }, [selectedId, qc]);

  // 把对话中的链接 href 解析为浏览器抽屉可渲染的 Source。
  // http(s) → 网页/PDF/Word（按扩展名）；其余视为工作空间文件路径，按当前任务工作空间解析内容。
  const resolveHref = useCallback(async (rawHref: string): Promise<Source> => {
    if (/^https?:\/\//i.test(rawHref)) return classifyUrl(rawHref);
    // react-markdown 会把含非 ASCII 的链接目标 percent-encode（如中文文件名），
    // 工空间路径匹配前需先解码回原始中文路径。
    let href = rawHref;
    try { href = decodeURIComponent(rawHref); } catch { /* 非法转义，保留原值 */ }
    const wsId = taskConfig.workspace_id;
    if (!wsId) return { kind: 'unsupported', href, note: '该任务未绑定工作空间，无法解析文件路径' };
    let files: WorkspaceFileListItem[];
    try { files = await terminal.listWsFiles(wsId); }
    catch { return { kind: 'unsupported', href, note: '工作空间文件读取失败' }; }
    const f = files.find((x) => x.path === href || x.path.endsWith('/' + href) || href.endsWith(x.path));
    if (!f) return { kind: 'unsupported', href, note: `工作空间中未找到该文件：${href}` };
    try { return classifyFile(await terminal.getWsFile(f.id)); }
    catch { return { kind: 'unsupported', href, note: '文件详情读取失败' }; }
  }, [taskConfig.workspace_id]);

  const openLink = useCallback((href: string) => {
    setBrowserHref(href);
    setBrowserSeq((n) => n + 1);
    setBrowserOpen(true);
  }, []);

  return (
    <ConfigProvider
      theme={{
        token: {
          colorPrimary: WB.primary, colorPrimaryHover: WB.primaryHover, borderRadius: 10, colorBorder: WB.border,
          fontFamily: WB_FONT, fontSize: 14, colorText: 'rgba(0, 0, 0, 0.88)',
        },
      }}
    >
      <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', background: '#f5f5f5', fontFamily: WB_FONT }}>
        {/* 主内容区 */}
        <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
          {/* 左侧栏 */}
          <aside style={{ width: 224, background: WB.sidebar, borderRight: `1px solid ${WB.border}`, display: 'flex', flexDirection: 'column', flex: '0 0 auto' }}>
            <div style={{ padding: 12 }}>
              <Button type="primary" icon={<PlusOutlined />} block onClick={newTask}>新建任务</Button>
            </div>

            <nav style={{ padding: '4px 8px' }}>
              <div onClick={() => setView('workspaces')} style={navItemStyle(view === 'workspaces')}>
                <FolderOpenOutlined style={{ fontSize: 16 }} />
                <span>工作空间</span>
              </div>
              <div onClick={() => setView('agents')} style={navItemStyle(view === 'agents')}>
                <RobotOutlined style={{ fontSize: 16 }} />
                <span>智能体</span>
              </div>
              <div onClick={() => setView('knowledge')} style={navItemStyle(view === 'knowledge')}>
                <BookOutlined style={{ fontSize: 16 }} />
                <span>知识库</span>
              </div>
              <div onClick={() => setView('skills')} style={navItemStyle(view === 'skills')}>
                <ThunderboltOutlined style={{ fontSize: 16 }} />
                <span>技能</span>
              </div>
              <div onClick={() => setView('ontology')} style={navItemStyle(view === 'ontology')}>
                <PartitionOutlined style={{ fontSize: 16 }} />
                <span>本体</span>
              </div>
              <div onClick={() => setView('data_interface')} style={navItemStyle(view === 'data_interface')}>
                <ApiOutlined style={{ fontSize: 16 }} />
                <span>数据接口</span>
              </div>
            </nav>

            {/* 任务列表 */}
            <div style={{ padding: '8px 16px', marginTop: 4 }}>
              <div style={{ fontSize: 12, color: '#6b7280', fontWeight: 500, marginBottom: 8 }}>
                任务 ({tasks?.length ?? 0})
              </div>
            </div>
            <div style={{ flex: 1, overflowY: 'auto', padding: '0 8px' }} className="wb-scroll-hide">
              {(tasks ?? []).length === 0 && (
                <div style={{ padding: '8px 12px', color: '#9ca3af', fontSize: 12 }}>暂无任务</div>
              )}
              {(tasks ?? []).map((t) => {
                const active = selectedId === t.id && !composerOpen;
                const showActions = hoveredId === t.id || active;
                const editing = editingId === t.id;
                return (
                  <div
                    key={t.id}
                    onClick={() => { if (!editing) { selectTask(t.id); setView('assistant'); } }}
                    onMouseEnter={() => { setHoveredId(t.id); }}
                    onMouseLeave={() => { setHoveredId(null); }}
                    style={{
                      display: 'flex', alignItems: 'flex-start', gap: 8, padding: '6px 12px', borderRadius: 6, cursor: 'pointer', fontSize: 12,
                      background: active ? `${WB.primary}1A` : (hoveredId === t.id ? WB.hover : undefined),
                      color: active ? WB.primary : '#6b7280',
                    }}
                  >
                    <FileTextOutlined style={{ marginTop: 2, color: active ? WB.primary : '#cbd5e1' }} />
                    {editing ? (
                      <Input
                        size="small"
                        autoFocus
                        value={editingTitle}
                        onChange={(e) => setEditingTitle(e.target.value)}
                        onClick={(e) => e.stopPropagation()}
                        onPointerDown={(e) => e.stopPropagation()}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') { e.preventDefault(); commitRename(t.id); }
                          else if (e.key === 'Escape') { e.preventDefault(); cancelRename(); }
                        }}
                        onBlur={() => commitRename(t.id)}
                        maxLength={255}
                        style={{ fontSize: 12, padding: '0 6px', height: 24 }}
                      />
                    ) : (
                      <span style={{ flex: 1, lineHeight: 1.4, overflow: 'hidden', textOverflow: 'ellipsis', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>
                        {t.title || '(未命名)'}
                      </span>
                    )}
                    <span style={{ display: 'flex', alignItems: 'center', gap: 4, flexShrink: 0, marginTop: 2 }}>
                      <span style={{ color: active ? `${WB.primary}B3` : '#cbd5e1', fontSize: 10, visibility: showActions ? 'hidden' : 'visible' }}>
                        {t.updated_at.slice(5, 10)}
                      </span>
                      {showActions && !editing && (
                        <EditOutlined
                          onClick={(e) => {
                            e.stopPropagation();
                            startRename(t);
                          }}
                          style={{ color: '#9ca3af', fontSize: 13, cursor: 'pointer' }}
                        />
                      )}
                      {showActions && !editing && (
                        <DeleteOutlined
                          onClick={(e) => {
                            e.stopPropagation();
                            setDelConfirm({ id: t.id, title: t.title || '(未命名)' });
                          }}
                          style={{ color: '#9ca3af', fontSize: 13, cursor: 'pointer' }}
                        />
                      )}
                    </span>
                  </div>
                );
              })}
            </div>

            {/* 底部用户 */}
            <div style={{ padding: 12, borderTop: `1px solid ${WB.border}`, flex: '0 0 auto' }}>
              <Popover
                trigger="click"
                placement="topLeft"
                content={
                  <div style={{ minWidth: 160 }}>
                    <div style={{ marginBottom: 8, fontSize: 12, color: '#9ca3af' }}>
                      {user?.organization_name || slug}
                    </div>
                    <Button block icon={<DownloadOutlined />} onClick={exportSkillsPack} style={{ marginBottom: 8 }}>
                      导出 Skills
                    </Button>
                    <Button danger block icon={<LogoutOutlined />} onClick={logout}>退出登录</Button>
                  </div>
                }
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
                  <Avatar size={28} style={{ background: 'linear-gradient(135deg, #34d399 0%, #14b8a6 100%)', flex: '0 0 auto' }}>{userInitial}</Avatar>
                  <span style={{ fontSize: 13, color: '#374151', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{userName}</span>
                  <MoreOutlined style={{ color: '#9ca3af' }} />
                </div>
              </Popover>
            </div>
          </aside>

          {/* 右侧主区 */}
          <main style={{ flex: 1, display: 'flex', flexDirection: 'column', background: '#fff', minWidth: 0 }}>
            {view === 'workspaces' ? (
              <WorkspaceManagerView resources={resources} />
            ) : view === 'agents' ? (
              <AgentManagerView />
            ) : view === 'knowledge' ? (
              <KnowledgeBaseView />
            ) : view === 'skills' ? (
              <SkillManagerView />
            ) : view === 'ontology' ? (
              <OntologyView />
            ) : view === 'data_interface' ? (
              <DataInterfaceView />
            ) : composerOpen ? (
              <HomeView
                input={input} setInput={setInput}
                attachments={inputAttachments} setAttachments={setInputAttachments}
                attachmentScopeKey={`草稿-${draftAttachmentKey}`}
                placeholder={COMPOSER_PLACEHOLDER}
                config={config}
                resources={resources}
                onSetExecMode={(m) => setConfig((c) => ({ ...c, exec_mode: m }))}
                onOpenConfig={() => { setCfgContext('composer'); setCfgOpen(true); }}
                onImportSkill={() => setView('skills')}
                onStart={startTask}
                streaming={streaming}
                agentLabel={agentLabel}
              />
            ) : (
              <ChatView
                taskTitle={selectedTask?.title || '任务对话'}
                chat={chat} streaming={streaming}
                followUp={followUp} setFollowUp={setFollowUp}
                attachments={followUpAttachments} setAttachments={setFollowUpAttachments}
                onSend={sendFollowUp} onStop={stopStream}
                onTogglePanel={() => setDrawerOpen(true)}
                onNew={newTask}
                config={taskConfig} resources={resources}
                onSetExecMode={(m) => patchTaskConfig({ ...taskConfig, exec_mode: m })}
                onOpenConfig={() => { setCfgContext('chat'); setCfgOpen(true); }}
                onImportSkill={() => setView('skills')}
                selectedId={selectedId}
                onLink={openLink}
                fileLinks={fileLinks}
                fileRefMap={fileRefMap}
                fileRefsLoaded={allWsFiles !== undefined}
                onDeleteTurn={(messageId) => {
                  if (!selectedId) return;
                  setTurnDelConfirm({ taskId: selectedId, messageId });
                }}
                agentLabel={agentLabel}
              />
            )}
          </main>
        </div>

        {/* 右侧抽屉：资源·文件·记忆·轨迹（默认收起，按需展开） */}
        <Drawer
          placement="right" open={drawerOpen} width={460}
          onClose={() => setDrawerOpen(false)}
          styles={{ body: { padding: '12px 16px', background: '#fafafa' } }}
          title={<span><UnorderedListOutlined /> 资源 · 文件 · 记忆 · 轨迹</span>}
        >
          <Tabs
            activeKey={activeTab} onChange={setActiveTab} size="small"
            items={[
              {
                key: 'resources',
                label: <span><SettingOutlined /> 资源</span>,
                children: <ResourcePanel taskConfig={taskConfig} resources={resources} />,
              },
              {
                key: 'files',
                label: <span><FileTextOutlined /> 文件</span>,
                children: <FilePanel workspaceId={taskConfig.workspace_id} />,
              },
              {
                key: 'memory',
                label: <span><DatabaseOutlined /> 记忆</span>,
                children: <MemoryPanel items={memoryList ?? []} />,
              },
              {
                key: 'trace',
                label: <span><UnorderedListOutlined /> 轨迹</span>,
                children: (
                  <div>
                    <Empty description="执行后显示原始事件轨迹" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ display: traceLog.length ? 'none' : 'block' }} />
                    {traceLog.map((s, i) => (
                      <div key={i} style={{ padding: '8px 0', borderBottom: `1px solid ${WB.border}` }}>
                        <Tag color="purple">{(s as Record<string, string>).type}</Tag>
                        <Typography.Text style={{ fontSize: 11, wordBreak: 'break-all' }}>{JSON.stringify(s)}</Typography.Text>
                      </div>
                    ))}
                  </div>
                ),
              },
            ]}
          />
        </Drawer>
      </div>

      <TaskConfigDrawer
        open={cfgOpen} onClose={() => setCfgOpen(false)}
        onApply={(c) => {
          if (cfgContext === 'chat') patchTaskConfig(c);
          else setConfig(c);
          setCfgOpen(false);
        }}
        resources={resources} config={cfgContext === 'chat' ? taskConfig : config}
        models={modelData?.models ?? []}
        agents={agentsList}
        agentId={selectedAgentId}
        onAgentChange={setSelectedAgentId}
      />

      <BrowserDrawer
        key={browserSeq}
        open={browserOpen}
        initialHref={browserHref}
        onClose={() => setBrowserOpen(false)}
        resolveHref={resolveHref}
        loadOriginalPreview={terminal.getWsFileOriginalPreview}
        loadOriginalFile={terminal.downloadWsFile}
      />

      {/* 删除任务确认：界面正中模态框 */}
      <ConfirmModal
        open={!!delConfirm}
        title="删除该任务？"
        desc="将同时清理该任务在工作空间中产出的文件"
        onCancel={() => setDelConfirm(null)}
        onOk={() => { if (delConfirm) { deleteTask(delConfirm.id); setDelConfirm(null); } }}
      />

      {/* 删除单轮对话确认：删该轮 user+assistant，并清理仅本轮产出文件 */}
      <ConfirmModal
        open={!!turnDelConfirm}
        title="删除该轮对话？"
        desc="将同时清理该轮在工作空间中产出、且未被后续轮次覆盖的文件"
        onCancel={() => setTurnDelConfirm(null)}
        onOk={() => {
          if (turnDelConfirm) {
            deleteTurn(turnDelConfirm.taskId, turnDelConfirm.messageId);
            setTurnDelConfirm(null);
          }
        }}
      />
    </ConfigProvider>
  );
}

// ── 技能引用 chip 编辑器（contentEditable：/slug 引用为不可分割高亮整体，退格整体删除）──

export interface ComposerInputHandle {
  /** 插入一个技能引用 chip：有 pending / 则替换之，否则插在光标处 */
  insertSkillChip: (slug: string, name: string) => void;
  /** 插入一个工作空间文件引用 chip：有 pending @ 则替换之，否则插在光标处 */
  insertFileChip: (fileId: string, label: string) => void;
  /** / 或 @ 触发后未选中即关闭：剥离那个孤立的触发符 */
  clearPendingMention: () => void;
  focus: () => void;
}

type PendingMention = { node: Text; offset: number; ch: '/' | '@' };

const MentionInput = forwardRef<ComposerInputHandle, {
  value: string; onChange: (v: string) => void; placeholder: string;
  onSlashTrigger: () => void; onAtTrigger: () => void; onSubmit: () => void; canSend: boolean;
}>(function MentionInput(props, ref) {
  const { value, placeholder } = props;
  const editorRef = useRef<HTMLDivElement>(null);
  const pendingRef = useRef<PendingMention | null>(null);
  // 最新 props via ref，避免 useImperativeHandle 闭包陈旧
  const latest = useRef(props);
  latest.current = props;

  const isChip = (el: Node | null): el is HTMLElement =>
    !!el && el.nodeType === Node.ELEMENT_NODE &&
    ((el as HTMLElement).hasAttribute('data-skill-slug') || (el as HTMLElement).hasAttribute('data-file-id'));

  const serialize = (el: HTMLElement): string => {
    let out = '';
    el.childNodes.forEach((n) => {
      if (n.nodeType === Node.TEXT_NODE) {
        out += n.textContent ?? '';
      } else if (n.nodeType === Node.ELEMENT_NODE) {
        const e = n as HTMLElement;
        if (e.hasAttribute('data-skill-slug')) out += `/${e.getAttribute('data-skill-slug')}`;
        else if (e.hasAttribute('data-file-id')) out += `@${e.getAttribute('data-file-id')}`;
        else out += e.textContent ?? '';
      }
    });
    return out;
  };

  const syncToState = () => {
    const el = editorRef.current;
    if (!el) return;
    const text = serialize(el);
    // 清掉空编辑器里的孤立 <br>，让 :empty 占位符生效
    if (text === '' && el.childNodes.length === 1 && el.firstChild?.nodeName === 'BR') {
      el.textContent = '';
    }
    latest.current.onChange(text);
  };

  // 外部 value 变化（如发送后清空）→ 重建 DOM
  useEffect(() => {
    const el = editorRef.current;
    if (!el) return;
    if (serialize(el) !== value) el.textContent = value;
  }, [value]);

  // 共用插入：chip 为已建好的 span；triggerCh 为对应触发符（替换 pending 或插在光标）
  const placeChip = (chip: HTMLSpanElement, triggerCh: '/' | '@') => {
    const el = editorRef.current;
    if (!el) return;
    el.focus();
    const sel = window.getSelection();
    const place = (range: Range) => {
      range.deleteContents();
      range.insertNode(chip);
      const sp = document.createTextNode(' ');
      chip.parentNode?.insertBefore(sp, chip.nextSibling);
      const r = document.createRange();
      r.setStartAfter(sp);
      r.collapse(true);
      sel?.removeAllRanges();
      sel?.addRange(r);
    };
    const p = pendingRef.current;
    pendingRef.current = null;
    if (p && p.node.parentNode && (p.node.textContent ?? '')[p.offset] === triggerCh) {
      const r = document.createRange();
      r.setStart(p.node, p.offset);
      r.setEnd(p.node, p.offset + 1);
      place(r);
    } else if (sel && sel.rangeCount) {
      place(sel.getRangeAt(0));
    }
    el.normalize();
    syncToState();
  };

  useImperativeHandle(ref, () => ({
    focus: () => editorRef.current?.focus(),
    clearPendingMention: () => {
      const el = editorRef.current;
      const p = pendingRef.current;
      pendingRef.current = null;
      if (!el || !p || !p.node.parentNode) return;
      const t = p.node.textContent ?? '';
      if (t[p.offset] !== p.ch) return;
      p.node.textContent = t.slice(0, p.offset) + t.slice(p.offset + 1);
      el.normalize();
      syncToState();
    },
    insertSkillChip: (slug, name) => {
      const chip = document.createElement('span');
      chip.setAttribute('contenteditable', 'false');
      chip.setAttribute('data-skill-slug', slug);
      chip.className = 'skill-ref-chip';
      chip.textContent = name;
      chip.title = `技能：${name} (/${slug})`;
      placeChip(chip, '/');
    },
    insertFileChip: (fileId, label) => {
      const chip = document.createElement('span');
      chip.setAttribute('contenteditable', 'false');
      chip.setAttribute('data-file-id', fileId);
      chip.className = 'file-ref-chip';
      chip.textContent = label;
      chip.title = `工作空间文件：${label}`;
      placeChip(chip, '@');
    },
  }), []);

  // 词首键入触发符 / 或 @ → 记录 pending 并唤出对应下拉
  const detectTrigger = (ch: '/' | '@') => {
    const sel = window.getSelection();
    if (!sel || !sel.isCollapsed || !sel.rangeCount) return;
    const range = sel.getRangeAt(0);
    const node = range.startContainer;
    const offset = range.startOffset;
    if (node.nodeType !== Node.TEXT_NODE) return;
    const txt = node.textContent ?? '';
    const i = offset - 1;
    if (txt[i] !== ch) return;
    const prev = txt[i - 1] ?? '';
    if (prev !== '' && !/\s/.test(prev)) return;
    pendingRef.current = { node: node as Text, offset: i, ch };
    if (ch === '/') latest.current.onSlashTrigger();
    else latest.current.onAtTrigger();
  };

  const handleInput = (e: FormEvent<HTMLDivElement>) => {
    const ev = e.nativeEvent as InputEvent;
    if (ev.inputType === 'insertText') {
      if (ev.data === '/') detectTrigger('/');
      else if (ev.data === '@') detectTrigger('@');
    }
    syncToState();
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Backspace') {
      // 光标紧贴 chip 之前时，整体删除该 chip（跨浏览器确定性，技能/文件皆然）
      const sel = window.getSelection();
      if (sel && sel.isCollapsed && sel.rangeCount) {
        const range = sel.getRangeAt(0);
        const node = range.startContainer;
        const offset = range.startOffset;
        let prev: Node | null = null;
        if (node.nodeType === Node.TEXT_NODE) {
          if (offset === 0) prev = node.previousSibling;
        } else {
          prev = (node as HTMLElement).childNodes[offset - 1] ?? null;
        }
        if (isChip(prev)) {
          e.preventDefault();
          prev.remove();
          syncToState();
        }
      }
      return;
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (latest.current.canSend) latest.current.onSubmit();
    }
  };

  return (
    <div
      ref={editorRef}
      className="skill-composer"
      contentEditable
      suppressContentEditableWarning
      data-placeholder={placeholder}
      onInput={handleInput}
      onKeyDown={handleKeyDown}
      onFocus={() => {
        const el = editorRef.current;
        if (el && el.childNodes.length === 1 && el.firstChild?.nodeName === 'BR') el.textContent = '';
      }}
      style={{ padding: '14px 16px 8px', fontSize: 14, lineHeight: 1.6, minHeight: 72, maxHeight: 320, overflowY: 'auto', wordBreak: 'break-word' }}
    />
  );
});

// ── 任务输入框（作曲器与聊天执行页共用，无边框） ──────────────────────────

function TaskInputBox(props: {
  value: string; setValue: (v: string) => void;
  attachments: ComposerAttachment[];
  setAttachments: Dispatch<SetStateAction<ComposerAttachment[]>>;
  attachmentScopeKey: string;
  onSend: () => void; onStop?: () => void; streaming: boolean;
  placeholder: string;
  config: TaskConfig; resources: TerminalResources | undefined;
  onSetExecMode: (m: TaskConfig['exec_mode']) => void;
  onOpenConfig: () => void;
  onImportSkill: () => void;
  /** 当前选中智能体显示名（null=通用），点 chip 打开同一抽屉在模型下方切换。 */
  agentLabel: string;
  maxWidth?: number; sendLabel?: string;
}) {
  const {
    value, setValue, attachments, setAttachments, attachmentScopeKey,
    onSend, onStop, streaming, placeholder, config, resources,
    onSetExecMode, onOpenConfig, onImportSkill, agentLabel, maxWidth = 800, sendLabel = '开始执行',
  } = props;
  const effectiveWorkspaceId = config.workspace_id ?? resources?.defaults?.workspace_id ?? null;
  const wsName = (effectiveWorkspaceId && resources?.workspaces.find((w) => w.id === effectiveWorkspaceId)?.name) || null;
  const hasReadyAttachment = attachments.some((item) => item.status === 'ready');
  const attachmentsReady = attachments.every((item) => item.status === 'ready');
  const canSend = (!!value.trim() || hasReadyAttachment) && attachmentsReady && !streaming;

  // ── 引用下拉（向上）：技能（/ 或 chip）/ 工作空间文件（@）共用一个 Popover ──
  const inputRef = useRef<ComposerInputHandle>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const attachmentsRef = useRef(attachments);
  const uploadControllersRef = useRef(new Map<string, AbortController>());
  const activeUploadsRef = useRef(0);
  const uploadWaitersRef = useRef<Array<() => void>>([]);
  const previousWorkspaceRef = useRef<string | null>(effectiveWorkspaceId);
  const searchRef = useRef<{ focus: (opts?: unknown) => void } | null>(null);
  const qc = useQueryClient();
  const [dragActive, setDragActive] = useState(false);

  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerMode, setPickerMode] = useState<'skill' | 'file'>('skill');
  const [query, setQuery] = useState('');

  const { data: wsFiles } = useQuery<WorkspaceFileSummary[]>({
    queryKey: ['terminal-ws-files'], queryFn: () => terminal.listAllWsFiles(),
  });

  useEffect(() => { if (pickerOpen) searchRef.current?.focus({ cursor: 'end' }); }, [pickerOpen]);
  // 打开文件模式时刷新文件清单，避免用 react-query 旧缓存
  useEffect(() => {
    if (pickerOpen && pickerMode === 'file') qc.invalidateQueries({ queryKey: ['terminal-ws-files'] });
  }, [pickerOpen, pickerMode, qc]);

  const openPicker = (mode: 'skill' | 'file') => {
    setPickerMode(mode); setQuery(''); setPickerOpen(true);
  };

  const skills = resources?.skills ?? [];
  const files = wsFiles ?? [];
  const qstr = query.trim().toLowerCase();
  const filteredSkills = qstr
    ? skills.filter((s) => s.name.toLowerCase().includes(qstr) || s.slug.toLowerCase().includes(qstr))
    : skills;
  const filteredFiles = qstr
    ? files.filter((f) => f.path.toLowerCase().includes(qstr) || f.workspace_name.toLowerCase().includes(qstr))
    : files;

  const closePicker = useCallback((picked: boolean) => {
    if (!picked) inputRef.current?.clearPendingMention();
    setQuery('');
    setPickerOpen(false);
  }, []);

  // trigger={[]} 下 Ant Popover 不会因 trigger wrapper 内部的点击而关闭；
  // 这里补上全局 Escape 与点击外部关闭，并让点击同一按钮 toggle。
  const triggerWrapRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!pickerOpen) return;
    const onDocKeyDown = (e: DocumentEventMap['keydown']) => {
      if (e.key === 'Escape') { e.preventDefault(); closePicker(false); }
    };
    const onDocMouseDown = (e: DocumentEventMap['mousedown']) => {
      const target = e.target as HTMLElement | null;
      if (!target) return;
      // 点击落在弹出层（技能/文件选择器、执行模式 Dropdown、Tooltip 等）内部 → 交给其自身处理
      if (target.closest?.('.ant-popover, .ant-dropdown, .ant-tooltip, .ant-select-dropdown')) return;
      const wrap = triggerWrapRef.current;
      if (wrap && wrap.contains(target)) {
        // 点击技能/文件按钮：交给 onClick 做 toggle，不在此处关闭
        if (target.closest?.('[data-picker-trigger]')) return;
        // 点击 composer / 其它区域 → 关闭
        closePicker(false);
        return;
      }
      // 完全在外部 → 关闭
      closePicker(false);
    };
    document.addEventListener('keydown', onDocKeyDown, true);
    document.addEventListener('mousedown', onDocMouseDown, true);
    return () => {
      document.removeEventListener('keydown', onDocKeyDown, true);
      document.removeEventListener('mousedown', onDocMouseDown, true);
    };
  }, [pickerOpen, closePicker]);

  const onPick = (s: SkillFolderSummary) => {
    setQuery(''); setPickerOpen(false);
    inputRef.current?.insertSkillChip(s.slug, s.name);
  };
  const onPickFile = (f: WorkspaceFileSummary) => {
    setQuery(''); setPickerOpen(false);
    inputRef.current?.insertFileChip(f.id, f.path);
  };

  const updateAttachment = useCallback((clientId: string, patch: Partial<ComposerAttachment>) => {
    setAttachments((current) => current.map((item) => (
      item.client_id === clientId ? { ...item, ...patch } : item
    )));
  }, [setAttachments]);

  useEffect(() => { attachmentsRef.current = attachments; }, [attachments]);

  const refreshWorkspaceFiles = useCallback((workspaceId: string) => {
    qc.invalidateQueries({ queryKey: ['terminal-ws-files'] });
    qc.invalidateQueries({ queryKey: ['terminal-all-ws-files'] });
    qc.invalidateQueries({ queryKey: ['terminal-ws-files', workspaceId] });
    qc.invalidateQueries({ queryKey: ['ws-mgr-files'] });
  }, [qc]);

  const uploadOne = useCallback(async (draft: ComposerAttachment, workspaceId: string) => {
    const controller = new AbortController();
    uploadControllersRef.current.set(draft.client_id, controller);
    if (activeUploadsRef.current >= MAX_UPLOAD_CONCURRENCY) {
      await new Promise<void>((resolve) => uploadWaitersRef.current.push(resolve));
    }
    if (controller.signal.aborted) {
      uploadControllersRef.current.delete(draft.client_id);
      uploadWaitersRef.current.shift()?.();
      return;
    }
    activeUploadsRef.current += 1;
    updateAttachment(draft.client_id, { status: 'uploading', progress: 0, error: undefined });
    try {
      const uploaded = await terminal.uploadWsFile(workspaceId, draft.file, draft.path, {
        signal: controller.signal,
        onProgress: (progress) => updateAttachment(draft.client_id, { progress }),
        onUploadComplete: () => updateAttachment(draft.client_id, { status: 'parsing', progress: 100 }),
      });
      const nextStatus: ComposerAttachmentStatus = uploaded.parse_status === 'ready' ? 'ready' : 'failed';
      updateAttachment(draft.client_id, {
        file_id: uploaded.id,
        workspace_id: uploaded.workspace_id,
        path: uploaded.path,
        status: nextStatus,
        progress: 100,
        error: nextStatus === 'failed'
          ? (uploaded.parse_error || (uploaded.parse_status === 'unsupported' ? '暂不支持该文件格式' : '文件解析失败'))
          : undefined,
      });
      refreshWorkspaceFiles(workspaceId);
    } catch (error) {
      if ((error as Error).name !== 'AbortError') {
        updateAttachment(draft.client_id, {
          status: 'failed',
          error: (error as Error).message || '上传失败',
        });
      }
    } finally {
      activeUploadsRef.current = Math.max(0, activeUploadsRef.current - 1);
      uploadControllersRef.current.delete(draft.client_id);
      uploadWaitersRef.current.shift()?.();
    }
  }, [refreshWorkspaceFiles, updateAttachment]);

  const queueFiles = useCallback(async (fileList: FileList | File[]) => {
    const workspaceId = effectiveWorkspaceId;
    if (!workspaceId) {
      message.warning('请先选择工作空间，再上传聊天附件');
      onOpenConfig();
      return;
    }
    const available = Math.max(0, MAX_ATTACHMENTS - attachmentsRef.current.length);
    const selected = Array.from(fileList).slice(0, available);
    if (!available) {
      message.warning(`每条消息最多添加 ${MAX_ATTACHMENTS} 个附件`);
      return;
    }
    if (fileList.length > available) {
      message.warning(`每条消息最多添加 ${MAX_ATTACHMENTS} 个附件，已保留前 ${available} 个`);
    }
    const drafts: ComposerAttachment[] = selected.map((file) => ({
      client_id: crypto.randomUUID(),
      file,
      file_id: '',
      workspace_id: workspaceId,
      path: attachmentPath(attachmentScopeKey, file.name),
      name: file.name,
      status: file.size > MAX_ATTACHMENT_BYTES ? 'failed' : 'uploading',
      progress: 0,
      error: file.size > MAX_ATTACHMENT_BYTES ? '文件超过 5MB 上限' : undefined,
    }));
    attachmentsRef.current = [...attachmentsRef.current, ...drafts];
    setAttachments((current) => [...current, ...drafts]);
    const pending = drafts.filter((item) => item.status !== 'failed');
    let cursor = 0;
    const worker = async () => {
      while (cursor < pending.length) {
        const item = pending[cursor++];
        await uploadOne(item, workspaceId);
      }
    };
    await Promise.all(Array.from(
      { length: Math.min(MAX_UPLOAD_CONCURRENCY, pending.length) },
      () => worker(),
    ));
  }, [attachmentScopeKey, effectiveWorkspaceId, onOpenConfig, setAttachments, uploadOne]);

  const retryAttachment = useCallback(async (item: ComposerAttachment) => {
    if (item.file.size > MAX_ATTACHMENT_BYTES) {
      message.warning('该文件超过 5MB，请压缩或拆分后重新选择');
      return;
    }
    if (item.file_id) {
      updateAttachment(item.client_id, { status: 'parsing', error: undefined, progress: 100 });
      try {
        const reparsed = await terminal.reparseWsFile(item.file_id);
        updateAttachment(item.client_id, {
          status: reparsed.parse_status === 'ready' ? 'ready' : 'failed',
          error: reparsed.parse_status === 'ready'
            ? undefined
            : (reparsed.parse_error || '文件解析失败'),
        });
        refreshWorkspaceFiles(item.workspace_id);
      } catch (error) {
        updateAttachment(item.client_id, { status: 'failed', error: (error as Error).message || '重新解析失败' });
      }
      return;
    }
    await uploadOne(item, item.workspace_id);
  }, [refreshWorkspaceFiles, updateAttachment, uploadOne]);

  const removeAttachment = useCallback((item: ComposerAttachment) => {
    uploadControllersRef.current.get(item.client_id)?.abort();
    uploadControllersRef.current.delete(item.client_id);
    attachmentsRef.current = attachmentsRef.current.filter((candidate) => candidate.client_id !== item.client_id);
    setAttachments((current) => current.filter((candidate) => candidate.client_id !== item.client_id));
    if (item.file_id) message.info('已从消息移除，但文件仍保存在工作空间');
  }, [setAttachments]);

  useEffect(() => {
    const previous = previousWorkspaceRef.current;
    if (previous && effectiveWorkspaceId !== previous && attachments.length) {
      uploadControllersRef.current.forEach((controller) => controller.abort());
      uploadControllersRef.current.clear();
      attachmentsRef.current = [];
      setAttachments([]);
      message.warning('工作空间已切换，待发送附件已从消息移除；已上传文件仍保留在原工作空间');
    }
    previousWorkspaceRef.current = effectiveWorkspaceId;
  }, [attachments.length, effectiveWorkspaceId, setAttachments]);

  useEffect(() => () => {
    uploadControllersRef.current.forEach((controller) => controller.abort());
    uploadControllersRef.current.clear();
  }, []);

  const statusLabel: Record<ComposerAttachmentStatus, string> = {
    uploading: '上传中', parsing: '解析中', ready: '可以发送', failed: '处理失败',
  };

  const pickerContent = (
    <div style={{ width: 300, maxHeight: 360, display: 'flex', flexDirection: 'column' }}>
      <Input
        ref={searchRef as never}
        size="small" allowClear
        placeholder={pickerMode === 'skill' ? '搜索技能（名称 / slug）' : '搜索工作空间文件（路径 / 工作空间）'}
        // antd Input ref 形状与 searchRef 不完全一致，as never 规避类型摩擦
        prefix={<SearchOutlined style={{ color: '#9ca3af' }} />}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            if (pickerMode === 'skill') { const f = filteredSkills[0]; if (f) onPick(f); }
            else { const f = filteredFiles[0]; if (f) onPickFile(f); }
          } else if (e.key === 'Escape') { e.preventDefault(); closePicker(false); }
        }}
      />
      <div style={{ flex: 1, overflowY: 'auto', marginTop: 6, minHeight: 60 }} className="wb-scroll-hide">
        {pickerMode === 'skill' ? (
          filteredSkills.length ? filteredSkills.map((s) => (
            <div
              key={s.id} onClick={() => onPick(s)}
              style={{ padding: '6px 8px', cursor: 'pointer', borderRadius: 6, fontSize: 13 }}
              onMouseEnter={(e) => { e.currentTarget.style.background = WB.hover; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
            >
              <div style={{ fontWeight: 500 }}>{s.name}</div>
              <div style={{ fontSize: 11, color: '#9ca3af' }}>/{s.slug}</div>
            </div>
          )) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={query ? '无匹配技能' : '暂无可访问技能'}
              style={{ margin: '12px 0' }} />
          )
        ) : (
          filteredFiles.length ? filteredFiles.map((f) => (
            <div
              key={f.id} onClick={() => onPickFile(f)}
              style={{ padding: '6px 8px', cursor: 'pointer', borderRadius: 6, fontSize: 13 }}
              onMouseEnter={(e) => { e.currentTarget.style.background = WB.hover; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
            >
              <div style={{ fontWeight: 500, display: 'flex', alignItems: 'center', gap: 6 }}>
                <FileTextOutlined style={{ color: WB.primary }} />
                {f.path}{f.is_binary && <Tag color="default" style={{ marginLeft: 6, fontSize: 10 }}>二进制</Tag>}
              </div>
              <div style={{ fontSize: 11, color: '#9ca3af' }}>{f.workspace_name}</div>
            </div>
          )) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={query ? '无匹配文件' : '暂无可访问工作空间文件'}
              style={{ margin: '12px 0' }} />
          )
        )}
      </div>
      {pickerMode === 'skill' && (
        <div style={{ borderTop: `1px solid ${WB.border}`, marginTop: 6, paddingTop: 6 }}>
          <Button size="small" block icon={<UploadOutlined />}
            onClick={() => { closePicker(false); onImportSkill(); }}>
            导入技能
          </Button>
        </div>
      )}
    </div>
  );

  return (
    <div style={{ width: '100%', maxWidth }}>
      <Popover
        open={pickerOpen}
        trigger={[]}
        placement="topLeft"
        content={pickerContent}
        onOpenChange={(open) => { if (!open) closePicker(false); }}
      >
      <div
        ref={triggerWrapRef}
        onDragEnter={(event) => { event.preventDefault(); event.stopPropagation(); setDragActive(true); }}
        onDragOver={(event) => { event.preventDefault(); event.stopPropagation(); event.dataTransfer.dropEffect = 'copy'; }}
        onDragLeave={(event) => {
          event.preventDefault();
          if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragActive(false);
        }}
        onDrop={(event: ReactDragEvent<HTMLDivElement>) => {
          event.preventDefault(); event.stopPropagation(); setDragActive(false);
          if (event.dataTransfer.files.length) void queueFiles(event.dataTransfer.files);
        }}
        style={{ position: 'relative', border: `1px solid ${dragActive ? WB.primary : WB.border}`, borderRadius: 12, boxShadow: dragActive ? '0 0 0 3px rgba(99,102,241,0.12)' : '0 1px 2px rgba(0,0,0,0.04)', background: '#fff', transition: 'border-color .15s, box-shadow .15s' }}
      >
        <input
          ref={fileInputRef}
          type="file"
          multiple
          hidden
          onChange={(event: ChangeEvent<HTMLInputElement>) => {
            if (event.target.files?.length) void queueFiles(event.target.files);
            event.target.value = '';
          }}
        />
        {dragActive && (
          <div style={{ position: 'absolute', inset: 0, zIndex: 5, borderRadius: 11, background: 'rgba(238,240,247,0.94)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: WB.primary, fontSize: 14, fontWeight: 600, pointerEvents: 'none' }}>
            <UploadOutlined style={{ marginRight: 8 }} />松开上传到当前工作空间
          </div>
        )}
        {!!attachments.length && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 8, padding: '10px 12px 0' }}>
            {attachments.map((item) => (
              <div key={item.client_id} style={{ border: `1px solid ${item.status === 'failed' ? '#fecaca' : WB.border}`, background: item.status === 'failed' ? '#fff7f7' : '#f9fafb', borderRadius: 9, padding: '8px 10px', minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <FileTextOutlined style={{ color: item.status === 'failed' ? '#dc2626' : WB.primary, flexShrink: 0 }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div title={item.name} style={{ fontSize: 12, fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.name}</div>
                    <div style={{ fontSize: 11, color: item.status === 'failed' ? '#dc2626' : '#6b7280', marginTop: 2 }}>
                      {statusLabel[item.status]}{item.status === 'uploading' ? ` ${item.progress}%` : ''}
                    </div>
                  </div>
                  {(item.status === 'uploading' || item.status === 'parsing') && <Spin size="small" />}
                  {item.status === 'ready' && <CheckCircleOutlined style={{ color: '#16a34a' }} />}
                  {item.status === 'failed' && item.file.size <= MAX_ATTACHMENT_BYTES && (
                    <Button type="link" size="small" onClick={() => void retryAttachment(item)} style={{ padding: 0, fontSize: 11 }}>重试</Button>
                  )}
                  <Tooltip title={item.file_id ? '从消息移除（不删除工作空间文件）' : '移除'}>
                    <CloseOutlined onClick={() => removeAttachment(item)} style={{ color: '#9ca3af', cursor: 'pointer', fontSize: 12 }} />
                  </Tooltip>
                </div>
                {item.error && <div title={item.error} style={{ fontSize: 11, color: '#dc2626', marginTop: 5, lineHeight: 1.35 }}>{item.error}</div>}
                {item.status === 'uploading' && (
                  <div style={{ height: 2, background: '#e5e7eb', borderRadius: 999, marginTop: 6, overflow: 'hidden' }}>
                    <div style={{ height: '100%', width: `${item.progress}%`, background: WB.primary, transition: 'width .15s' }} />
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
        <MentionInput
          ref={inputRef}
          value={value} onChange={setValue}
          placeholder={placeholder}
          onSlashTrigger={() => openPicker('skill')}
          onAtTrigger={() => openPicker('file')}
          onSubmit={onSend} canSend={canSend}
        />
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 12px', borderTop: `1px solid ${WB.border}` }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <Dropdown
              trigger={['click']}
              menu={{
                selectable: true,
                selectedKeys: [config.exec_mode],
                onClick: ({ key }) => onSetExecMode(key as TaskConfig['exec_mode']),
                items: EXEC_MODES.map((m) => ({
                  key: m.key,
                  label: (
                    <div style={{ lineHeight: 1.35 }}>
                      <div style={{ fontWeight: 500 }}>{m.label}</div>
                      <div style={{ fontSize: 11, color: '#9ca3af' }}>{m.desc}</div>
                    </div>
                  ),
                })),
              }}
            >
              <button style={chipBtnStyle} title="执行模式">
                <ThunderboltOutlined /> {EXEC_LABEL[config.exec_mode]} <DownOutlined style={{ fontSize: 10 }} />
              </button>
            </Dropdown>
            <span style={{ width: 1, height: 14, background: WB.border }} />
            <span data-picker-trigger="skill" style={chipBtnStyle}
              onClick={() => { if (pickerOpen && pickerMode === 'skill') closePicker(false); else openPicker('skill'); }}
              title="引用技能（输入 / 也可唤出，再次点击关闭）">
              <AppstoreOutlined /> 技能
            </span>
            <span data-picker-trigger="file" style={chipBtnStyle}
              onClick={() => { if (pickerOpen && pickerMode === 'file') closePicker(false); else openPicker('file'); }}
              title="引用工作空间文件（输入 @ 也可唤出，再次点击关闭）">
              <FileTextOutlined /> 文件
            </span>
            <span style={chipBtnStyle}
              onClick={() => fileInputRef.current?.click()}
              title="上传附件到当前工作空间（可多选）">
              <UploadOutlined /> 上传附件
            </span>
            <span
              onClick={onOpenConfig}
              title="任务资源配置"
              className="wb-cfg-trigger"
              style={{ display: 'inline-flex', alignItems: 'center', gap: 10, cursor: 'pointer', padding: '2px 6px', borderRadius: 6 }}
            >
              <span style={chipBtnStyle}><RobotOutlined /> 智能体 {agentLabel}</span>
              <span style={chipBtnStyle}>模型{config.model_alias ? ` ${config.model_alias}` : '·默认'}</span>
              <span style={chipBtnStyle}><FolderOpenOutlined /> 工作空间 {wsName ?? '未选择'}</span>
            </span>
          </div>
          {streaming && onStop ? (
            <Tooltip title="停止生成">
              <button
                onClick={onStop}
                style={{ width: 32, height: 32, borderRadius: 8, border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#fee2e2', color: '#dc2626' }}
              ><CloseOutlined /></button>
            </Tooltip>
          ) : (
            <Tooltip title={!attachmentsReady ? '附件处理完成后才能发送' : sendLabel}>
              <button
                onClick={onSend} disabled={!canSend}
                style={{
                  width: 32, height: 32, borderRadius: 8, border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
                  background: canSend ? WB.primary : '#e5e7eb', color: '#fff',
                }}
              >
                {streaming ? <Spin size="small" /> : <SendOutlined />}
              </button>
            </Tooltip>
          )}
        </div>
      </div>
      </Popover>
    </div>
  );
}

// ── 首页欢迎视图（作曲器） ───────────────────────────────────────────────

function HomeView(props: {
  input: string; setInput: (v: string) => void; placeholder: string;
  attachments: ComposerAttachment[];
  setAttachments: Dispatch<SetStateAction<ComposerAttachment[]>>;
  attachmentScopeKey: string;
  config: TaskConfig;
  resources: TerminalResources | undefined;
  onSetExecMode: (m: TaskConfig['exec_mode']) => void;
  onOpenConfig: () => void; onImportSkill: () => void; onStart: () => void; streaming: boolean;
  agentLabel: string;
}) {
  const {
    input, setInput, attachments, setAttachments, attachmentScopeKey, placeholder,
    config, resources, onSetExecMode, onOpenConfig, onImportSkill, onStart, streaming, agentLabel,
  } = props;
  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
      {/* 顶部状态条 */}
      <div style={{ height: 44, display: 'flex', alignItems: 'center', justifyContent: 'flex-end', padding: '0 16px', borderBottom: `1px solid ${WB.border}`, flex: '0 0 auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: '#6b7280' }}>
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#22c55e', display: 'inline-block' }} />
          <span>就绪 · 智能体在线</span>
        </div>
      </div>

      {/* 欢迎内容 */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '0 32px', overflowY: 'auto' }}>
        {/* 品牌图标 */}
        <div style={{ position: 'relative', marginBottom: 24 }}>
          <img src="/terminal-icon.png" alt="AgileBuddy" style={{ width: 72, height: 72, objectFit: 'contain', display: 'block' }} />
        </div>

        <h1 style={{ fontSize: 30, fontWeight: 700, color: '#111827', marginBottom: 4 }}>AgileBuddy</h1>
        <p style={{ fontSize: 22, fontWeight: 600, color: '#1f2937', marginBottom: 32 }}>你的职场超能力</p>

        {/* 输入框 */}
        <TaskInputBox
          value={input} setValue={setInput}
          attachments={attachments} setAttachments={setAttachments}
          attachmentScopeKey={attachmentScopeKey}
          onSend={onStart} streaming={streaming}
          placeholder={placeholder}
          config={config} resources={resources}
          onSetExecMode={onSetExecMode}
          onOpenConfig={onOpenConfig}
          onImportSkill={onImportSkill}
          agentLabel={agentLabel}
          maxWidth={800} sendLabel="开始执行"
        />
      </div>
    </div>
  );
}

// ── 聊天视图 ─────────────────────────────────────────────────────────────

// 把用户消息正文里的 /slug、@fileId 引用还原为技能名 / 文件路径 chip；同时把正文里出现的
// 技能「名称」也识别成 chip（picker 序列化或手敲名字都能显示为 chip，不再以纯文本末尾呈现）。
// 仅当 slug/id/名称能在映射中解析到时才渲染为 chip，未命中的原样保留为纯文本。
// agentName 非空时，在该轮用户消息正文最前补一个智能体 chip（与技能 chip 同款展示）。
function renderUserContent(
  content: string,
  skillMap: Map<string, string>,
  fileMap: Map<string, string>,
  agentName?: string | null,
): ReactNode[] {
  // 文本片段里出现的技能名 → chip（长名优先，避免短名误命中）
  const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const skillNames = [...skillMap.values()].filter((n) => !!n && n.length >= 2)
    .sort((a, b) => b.length - a.length);
  const nameRe = skillNames.length ? new RegExp(skillNames.map(escapeRe).join('|'), 'g') : null;
  const chipNames = (text: string, keyBase: string): ReactNode[] => {
    if (!nameRe || !text) return [text];
    const out: ReactNode[] = [];
    let last = 0; let k = 0; let m: RegExpExecArray | null;
    nameRe.lastIndex = 0;
    while ((m = nameRe.exec(text))) {
      if (m.index > last) out.push(text.slice(last, m.index));
      out.push(<span key={`${keyBase}n${k++}`} className="skill-ref-chip" title={`技能：${m[0]}`}>{m[0]}</span>);
      last = m.index + m[0].length;
    }
    if (last < text.length) out.push(text.slice(last));
    return out;
  };

  const out: ReactNode[] = [];
  if (agentName) {
    out.push(<span key="agent" className="agent-ref-chip" title="智能体">{agentName}</span>);
  }
  if (!content) return out;
  const re = /(^|\s)([/@])([A-Za-z0-9][A-Za-z0-9_-]*)/g;
  let last = 0;
  let key = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(content))) {
    const full = m[0];
    const pre = m[1];
    const ch = m[2];
    const token = m[3];
    const idx = m.index + pre.length; // chip 起始（不含前导空白）
    if (idx > last) out.push(...chipNames(content.slice(last, idx), `t${key++}`));
    const resolved = ch === '/' ? skillMap.get(token) : fileMap.get(token);
    if (resolved) {
      out.push(
        ch === '/'
          ? <span key={`s${key++}`} className="skill-ref-chip" title={`技能：${resolved} (/${token})`}>{resolved}</span>
          : <span key={`f${key++}`} className="file-ref-chip" title={`工作空间文件：${resolved}`}>{resolved}</span>,
      );
    } else {
      out.push(ch + token);
    }
    last = m.index + full.length;
  }
  if (last < content.length) out.push(...chipNames(content.slice(last), `t${key++}`));
  return out;
}

function ChatView(props: {
  taskTitle: string;
  chat: ChatMsg[]; streaming: boolean;
  followUp: string; setFollowUp: (v: string) => void;
  attachments: ComposerAttachment[];
  setAttachments: Dispatch<SetStateAction<ComposerAttachment[]>>;
  onSend: () => void; onStop: () => void;
  onTogglePanel: () => void; onNew: () => void;
  config: TaskConfig; resources: TerminalResources | undefined;
  onSetExecMode: (m: TaskConfig['exec_mode']) => void;
  onOpenConfig: () => void;
  onImportSkill: () => void;
  selectedId: string | null;
  onLink: (href: string) => void;
  fileLinks: { path: string; name: string }[];
  fileRefMap: Map<string, string>;
  fileRefsLoaded: boolean;
  onDeleteTurn: (messageId: string) => void;
  agentLabel: string;
}) {
  const {
    taskTitle, chat, streaming, followUp, setFollowUp, attachments, setAttachments,
    onSend, onStop, onNew, config, resources, onSetExecMode, onOpenConfig,
    onImportSkill, selectedId, onLink, fileLinks, fileRefMap, fileRefsLoaded, onDeleteTurn, agentLabel,
  } = props;
  // slug → 技能名称，供用户消息气泡把 /slug 还原为技能名 chip（样式与输入框一致）
  const skillRefMap = useMemo(() => {
    const m = new Map<string, string>();
    (resources?.skills ?? []).forEach((s) => m.set(s.slug, s.name));
    return m;
  }, [resources]);
  const scrollRef = useRef<HTMLDivElement>(null);
  // 每轮 hover 才显示删除按钮：避免常驻图标干扰阅读，且只在 user 气泡上触发（删除一整轮）
  const [hoveredTurn, setHoveredTurn] = useState<number | null>(null);
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [chat, streaming]);

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      {/* 聊天标题栏 */}
      <div style={{ height: 44, display: 'flex', alignItems: 'center', padding: '0 16px', borderBottom: `1px solid ${WB.border}`, flex: '0 0 auto', gap: 8 }}>
        <Button size="small" type="text" icon={<PlusOutlined />} onClick={onNew} />
        <span style={{ fontSize: 13, fontWeight: 500, color: '#1f2937', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{taskTitle}</span>
        <div style={{ flex: 1 }} />
      </div>

      {/* 聊天内容区 */}
      <div ref={scrollRef} style={{ flex: 1, overflowY: 'auto', padding: '24px 24px', background: '#fafafa' }} className="wb-scroll-hide">
        <div style={{ maxWidth: 820, margin: '0 auto' }}>
          {chat.length === 0 && (
            <div style={{ textAlign: 'center', color: '#9ca3af', fontSize: 13, marginTop: 40 }}>发送消息开始对话。</div>
          )}
          {chat.map((m, i) => {
            const isUser = m.role === 'user';
            const isLast = i === chat.length - 1;
            // 仅 user 消息且非流式进行中、且携带 DB id（历史回放或流式结束后回填）的轮次可删
            const canDelete = isUser && !!m.id && !streaming;
            const showDel = canDelete && hoveredTurn === i;
            return (
              <div
                key={i}
                onMouseEnter={() => { if (canDelete) setHoveredTurn(i); }}
                onMouseLeave={() => { if (hoveredTurn === i) setHoveredTurn(null); }}
                style={{ display: 'flex', justifyContent: isUser ? 'flex-end' : 'flex-start', marginBottom: 18, alignItems: 'flex-start', gap: 8 }}
              >
                {isUser ? (
                  <>
                    {showDel && (
                      <Tooltip title="删除该轮对话及本轮产出文件">
                        <DeleteOutlined
                          onClick={() => onDeleteTurn(m.id!)}
                          style={{ color: '#9ca3af', fontSize: 14, cursor: 'pointer', marginTop: 14, flexShrink: 0 }}
                        />
                      </Tooltip>
                    )}
                    <div style={{ maxWidth: '80%', background: WB.userMsg, borderRadius: '16px 16px 4px 16px', padding: '12px 16px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                        <Avatar size={20} style={{ background: '#ede9fe', color: '#7c3aed', fontSize: 10 }}>{'我'}</Avatar>
                        <span style={{ fontSize: 12, color: '#6b7280' }}>我</span>
                      </div>
                      {!!m.attachments?.length && (
                        <div style={{ display: 'grid', gap: 6, marginBottom: m.content ? 8 : 0 }}>
                          {m.attachments.map((attachment) => {
                            const availablePath = fileRefMap.get(attachment.file_id);
                            const unavailable = fileRefsLoaded && !availablePath;
                            return (
                              <button
                                key={attachment.file_id}
                                type="button"
                                disabled={unavailable}
                                onClick={() => onLink(availablePath || attachment.path)}
                                title={unavailable ? '文件已不存在或不可访问' : attachment.path}
                                style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%', border: `1px solid ${unavailable ? '#e5e7eb' : '#d8dcf4'}`, background: unavailable ? '#f3f4f6' : '#fff', borderRadius: 8, padding: '7px 9px', cursor: unavailable ? 'not-allowed' : 'pointer', color: unavailable ? '#9ca3af' : '#374151', textAlign: 'left' }}
                              >
                                <FileTextOutlined style={{ color: unavailable ? '#9ca3af' : WB.primary }} />
                                <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 12 }}>{attachment.name}</span>
                                <span style={{ fontSize: 10, flexShrink: 0 }}>{unavailable ? '不可访问' : '已引用'}</span>
                              </button>
                            );
                          })}
                        </div>
                      )}
                      <div style={{ fontSize: 14, color: '#1f2937', lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>{renderUserContent(m.content, skillRefMap, fileRefMap, m.agentName)}</div>
                    </div>
                  </>
                ) : (
                  <AssistantBubble msg={m} streaming={streaming && isLast} onLink={onLink} fileLinks={fileLinks} />
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* 底部输入区（与作曲器同一输入框组件；与消息区同背景、无分界线） */}
      <div style={{ padding: '12px 16px 16px', background: '#fafafa', flex: '0 0 auto' }}>
        <div style={{ maxWidth: 820, margin: '0 auto' }}>
          <TaskInputBox
            value={followUp} setValue={setFollowUp}
            attachments={attachments} setAttachments={setAttachments}
            attachmentScopeKey={selectedId || '任务未选择'}
            onSend={onSend} onStop={onStop} streaming={streaming}
            placeholder="追加消息（Enter 发送，Shift+Enter 换行）"
            config={config} resources={resources}
            onSetExecMode={onSetExecMode}
            onOpenConfig={onOpenConfig}
            onImportSkill={onImportSkill}
            agentLabel={agentLabel}
            maxWidth={820} sendLabel="发送"
          />
          <div style={{ textAlign: 'center', marginTop: 6, fontSize: 10, color: '#9ca3af' }}>
            内容由 AI 生成，请核实重要信息
          </div>
        </div>
      </div>
    </div>
  );
}

// ── 助手气泡：Claude Code 风格执行过程时间线 ──────────────────────────────

function AssistantBubble({ msg, streaming, onLink, fileLinks }: { msg: ChatMsg; streaming: boolean; onLink: (href: string) => void; fileLinks: { path: string; name: string }[] }) {
  const blocks = msg.blocks;
  const hasLiveBlocks = blocks && blocks.length > 0;
  // 兜底：无 blocks（历史回放）直接渲染 content markdown
  if (!hasLiveBlocks) {
    return (
      <div style={{ maxWidth: '92%' }}>
        <AvatarHeader />
        <div style={{ background: WB.botMsg, border: `1px solid ${WB.border}`, borderRadius: '16px 16px 16px 4px', boxShadow: '0 1px 2px rgba(0,0,0,0.04)', padding: 16 }}>
          <div className="wb-md"><Md onLink={onLink} files={fileLinks}>{msg.content || '(无内容)'}</Md></div>
        </div>
      </div>
    );
  }

  const lastBlock = blocks![blocks!.length - 1];
  const thinking = streaming && (lastBlock.kind === 'phase' || (lastBlock.kind === 'tool_call' && lastBlock.running));

  return (
    <div style={{ maxWidth: '92%' }}>
      <AvatarHeader streaming={streaming} />
      <div style={{ background: WB.botMsg, border: `1px solid ${WB.border}`, borderRadius: '16px 16px 16px 4px', boxShadow: '0 1px 2px rgba(0,0,0,0.04)', padding: 16 }}>
        {/* 状态条 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, marginBottom: 8, color: streaming ? WB.primary : '#22c55e' }}>
          {streaming ? <><LoadingOutlined /> 执行中…</> : <><CheckCircleOutlined /> 已完成</>}
        </div>

        {/* 时间线 blocks */}
        {blocks!.map((b, i) => {
          if (b.kind === 'phase') {
            const isCurrent = streaming && i === blocks!.length - 1;
            return (
              <div key={i} className="wb-phase">
                {isCurrent ? <LoadingOutlined /> : <RightOutlined style={{ fontSize: 10 }} />}
                <span>{isCurrent ? '思考中…' : `第 ${b.index + 1} 步`}</span>
              </div>
            );
          }
          if (b.kind === 'tool_call') {
            return <ToolCard key={i} b={b} />;
          }
          if (b.kind === 'trace') {
            return <TraceChip key={i} b={b} />;
          }
          if (b.kind === 'text') {
            const isLast = i === blocks!.length - 1;
            const showCursor = streaming && isLast;
            return (
              <div key={i} className="wb-md" style={{ marginTop: 4 }}>
                <Md onLink={onLink} files={fileLinks}>{b.content}</Md>
                {showCursor && <span className="wb-cursor" />}
              </div>
            );
          }
          // meta（记忆沉淀 / 判官）
          if (b.kind === 'meta') {
            const data = b.data as Record<string, unknown>;
            const label = b.subtype === 'memory'
              ? `记忆沉淀 · ${(data?.extracted as number) ?? 0} 条`
              : `判官评分`;
            return (
              <div key={i} className="wb-meta">
                <DatabaseOutlined /> {label}
              </div>
            );
          }
          return null;
        })}
        {thinking && (
          <div className="wb-phase" style={{ color: WB.primary }}>
            <LoadingOutlined /> 智能体工作中…
          </div>
        )}
        <ChangesBox files={extractFileChanges(blocks)} onLink={onLink} />
      </div>
    </div>
  );
}

// ── 本轮文件变更汇总 ──────────────────────────────────────────────────────
// 从 blocks 里筛出 workspace_write_file / generate_docx 两类已成功完成的 tool_call，
// 解析 arguments 取路径/文件名，作为本轮「新生成与修改」的文件清单。
// 实时走 tool_call 事件、历史回放由 tracesToBlocks 还原成同样的 tool_call block，两条路径在此统一。
const FILE_WRITE_TOOLS = new Set(['workspace_write_file', 'generate_docx']);

function extractFileChanges(blocks?: Block[]): { path: string; generated: boolean }[] {
  if (!blocks) return [];
  const ordered: { path: string; generated: boolean }[] = [];
  for (const b of blocks) {
    if (b.kind !== 'tool_call') continue;
    if (b.running || b.result?.ok === false) continue;
    if (!FILE_WRITE_TOOLS.has(b.name)) continue;
    let path = '';
    try {
      const p = JSON.parse(b.arguments || '{}');
      path = b.name === 'generate_docx' ? String(p.filename ?? '') : String(p.path ?? '');
    } catch { /* keep empty */ }
    if (!path) continue;
    ordered.push({ path, generated: b.name === 'generate_docx' });
  }
  // 同一路径多次写入只保留最后一次（去重，保持出现顺序）
  const seen = new Set<string>();
  const dedup: { path: string; generated: boolean }[] = [];
  for (let i = ordered.length - 1; i >= 0; i--) {
    if (seen.has(ordered[i].path)) continue;
    seen.add(ordered[i].path);
    dedup.unshift(ordered[i]);
  }
  return dedup;
}

function ChangesBox({ files, onLink }: { files: { path: string; generated: boolean }[]; onLink: (href: string) => void }) {
  const [open, setOpen] = useState(false);
  if (!files.length) return null;
  return (
    <div style={{ border: `1px solid ${WB.border}`, borderRadius: 8, background: '#FAFBFC', marginTop: 10 }}>
      <div
        onClick={() => setOpen((o) => !o)}
        style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 10px', cursor: 'pointer', fontSize: 12 }}
      >
        <FileTextOutlined style={{ color: WB.primary }} />
        <span style={{ fontWeight: 500, color: '#1f2937' }}>查看所有变更</span>
        <Tag color="blue" style={{ marginInlineStart: 0, fontSize: 11, padding: '0 6px' }}>{files.length}</Tag>
        <span style={{ marginLeft: 'auto', color: '#9ca3af' }}>
          {open ? '收起' : '展开'} <DownOutlined style={{ fontSize: 9, transform: open ? 'rotate(180deg)' : 'none' }} />
        </span>
      </div>
      {open && (
        <div style={{ padding: '4px 10px 10px', borderTop: `1px solid ${WB.border}` }}>
          {files.map((f, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 0', fontSize: 12 }}>
              {f.generated
                ? <FileTextOutlined style={{ color: '#0ea5e9' }} />
                : <CheckCircleOutlined style={{ color: '#22c55e' }} />}
              <a
                onClick={(e) => { e.preventDefault(); onLink(f.path); }}
                style={{ color: WB.primary, cursor: 'pointer', wordBreak: 'break-all' }}
              >{f.path}</a>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function AvatarHeader({ streaming }: { streaming?: boolean }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
      <img src="/terminal-icon.png" alt="AgileBuddy" style={{ width: 28, height: 28, objectFit: 'contain', display: 'block' }} />
      <span style={{ fontSize: 14, fontWeight: 500, color: '#1f2937' }}>AgileBuddy</span>
      {streaming && <Tag color="processing" style={{ marginInlineStart: 4, fontSize: 11 }}>live</Tag>}
    </div>
  );
}

// ── 工具调用卡片 ─────────────────────────────────────────────────────────

function ToolCard({ b }: { b: Extract<Block, { kind: 'tool_call' }> }) {
  const [open, setOpen] = useState(false);
  let prettyArgs = b.arguments;
  try {
    if (b.arguments && b.arguments.trim()) {
      prettyArgs = JSON.stringify(JSON.parse(b.arguments), null, 2);
    }
  } catch { /* keep raw */ }

  const ok = b.result?.ok;
  const statusColor = b.running ? WB.primary : (ok === false ? '#ef4444' : '#22c55e');
  const statusText = b.running ? '调用中…' : (ok === false ? '失败' : '完成');

  return (
    <div style={{ border: `1px solid ${WB.border}`, borderRadius: 8, background: '#FAFBFC', marginBottom: 8 }}>
      <div
        onClick={() => setOpen((o) => !o)}
        style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 10px', cursor: 'pointer', fontSize: 12 }}
      >
        {b.running
          ? <LoadingOutlined style={{ color: statusColor }} />
          : (ok === false
              ? <CloseOutlined style={{ color: statusColor }} />
              : <CheckCircleOutlined style={{ color: statusColor }} />)}
        <ThunderboltOutlined style={{ color: WB.primary }} />
        <span style={{ fontWeight: 500, color: '#1f2937' }}>{b.name || '(工具)'}</span>
        <span style={{ color: statusColor }}>{statusText}</span>
        <span style={{ marginLeft: 'auto', color: '#9ca3af' }}>
          {open ? '收起' : '详情'} <DownOutlined style={{ fontSize: 9, transform: open ? 'rotate(180deg)' : 'none' }} />
        </span>
      </div>
      {open && (
        <div style={{ padding: '0 10px 10px', borderTop: `1px solid ${WB.border}` }}>
          {prettyArgs && (
            <>
              <div style={{ color: '#6b7280', marginTop: 8, marginBottom: 2 }}>参数</div>
              <pre className="wb-pre">{prettyArgs}</pre>
            </>
          )}
          {b.result && (
            <>
              <div style={{ color: '#6b7280', marginTop: 8, marginBottom: 2 }}>
                结果{ok === false && <span style={{ color: '#ef4444' }}>（失败）</span>}
              </div>
              <pre className="wb-pre" style={{ color: ok === false ? '#fca5a5' : undefined }}>{b.result.content || '(空)'}</pre>
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ── 资源调用痕迹 chip（技能之外的五类：rag/ontology/memory/data_interface）───
// 与正文(text)和技能(ToolCard)都做区分：轻量单行 + 左侧主色竖条 + 类别图标，可展开看明细。

const TRACE_META: Record<TraceCategory, { icon: ReactNode; color: string; label: string }> = {
  rag: { icon: <BookOutlined />, color: '#0ea5e9', label: '知识库' },
  ontology: { icon: <PartitionOutlined />, color: '#8b5cf6', label: '本体' },
  memory: { icon: <DatabaseOutlined />, color: '#f59e0b', label: '记忆' },
  data_interface: { icon: <ApiOutlined />, color: '#10b981', label: '数据接口' },
  file: { icon: <FileTextOutlined />, color: '#0ea5e9', label: '文件' },
  skill: { icon: <ThunderboltOutlined />, color: WB.primary, label: '技能' },
};

function TraceChip({ b }: { b: Extract<Block, { kind: 'trace' }> }) {
  const [open, setOpen] = useState(false);
  const meta = TRACE_META[b.category] ?? TRACE_META.rag;
  // 把 detail 里的数值字段拼成一行摘要（如 命中 3 条 / 注入 2 个），无则只显标题
  const d = (b.detail ?? {}) as Record<string, unknown>;
  const summaryBits: string[] = [];
  const pushNum = (key: string, label: string) => {
    if (typeof d[key] === 'number') summaryBits.push(`${label} ${d[key]}`);
  };
  pushNum('hits', '命中');
  pushNum('collections', '库');
  pushNum('facts', '条');
  pushNum('history', '历史');
  pushNum('files', '文件');
  pushNum('systems', '系统');
  pushNum('interfaces', '接口');
  if (Array.isArray(d.names) && d.names.length) summaryBits.push(`${(d.names as unknown[]).length} 个`);
  if (Array.isArray(d.paths) && d.paths.length) summaryBits.push(`${(d.paths as unknown[]).length} 个`);
  const summary = summaryBits.join(' · ');
  const hasDetail = Object.keys(d).length > 0;
  return (
    <div className="wb-trace" style={{ borderLeftColor: meta.color }}>
      <div
        onClick={() => hasDetail && setOpen((o) => !o)}
        style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '5px 10px', cursor: hasDetail ? 'pointer' : 'default', fontSize: 12 }}
      >
        <span style={{ color: meta.color, display: 'inline-flex' }}>{meta.icon}</span>
        <span style={{ color: meta.color, fontWeight: 500, fontSize: 11 }}>{meta.label}</span>
        <span style={{ color: '#374151' }}>{b.title}</span>
        {summary && <span style={{ color: '#9ca3af' }}>· {summary}</span>}
        {hasDetail && (
          <span style={{ marginLeft: 'auto', color: '#9ca3af' }}>
            {open ? '收起' : '明细'} <DownOutlined style={{ fontSize: 9, transform: open ? 'rotate(180deg)' : 'none' }} />
          </span>
        )}
      </div>
      {open && hasDetail && (
        <div style={{ padding: '0 10px 8px', borderTop: `1px solid ${WB.border}` }}>
          <pre className="wb-pre" style={{ marginTop: 6 }}>{JSON.stringify(d, null, 2)}</pre>
        </div>
      )}
    </div>
  );
}

// ── Markdown 渲染 ────────────────────────────────────────────────────────

function Md({ children, onLink, files }: { children: string; onLink: (href: string) => void; files: { path: string; name: string }[] }) {
  // 先把正文里裸出现的「工作空间文件名」自动包成 markdown 链接，再交给 ReactMarkdown 渲染
  const src = linkifyFiles(children, files);
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        // 对话内容中的链接点击后不再新标签跳转，而是弹出右侧浏览器抽屉预览
        a: ({ node: _n, href, ...props }) => (
          <a
            {...props}
            href={href}
            onClick={(e) => { if (href) { e.preventDefault(); onLink(href); } }}
            style={{ color: WB.primary, cursor: 'pointer' }}
          />
        ),
      }}
    >
      {src}
    </ReactMarkdown>
  );
}

/** 把 markdown 正文中裸出现的工作空间文件名包成 [name](<path>) 链接。
 *  跳过代码块/行内代码/已有链接，避免破坏原有结构；用前后非 \w 边界降低误匹配。 */
function linkifyFiles(md: string, files: { path: string; name: string }[]): string {
  if (!files.length) return md;
  const byName = new Map<string, string>();
  for (const f of files) {
    if (f.name && f.name.length >= 2 && !byName.has(f.name)) byName.set(f.name, f.path);
  }
  const names = [...byName.keys()].sort((a, b) => b.length - a.length);
  if (!names.length) return md;
  const nameAlt = names.map(escapeRegExp).join('|');
  // 先按 代码围栏 / 行内代码 / 已有链接 分段，只在纯文本段里做文件名替换
  const tokenRe = /(`{3,}[\s\S]*?`{3,})|(`[^`\n]+`)|(\[[^\]]*\]\([^)]*\))/g;
  const linkifyPlain = (text: string) =>
    text.replace(new RegExp(`(?<![\\w/])(${nameAlt})(?![\\w])`, 'g'), (m) => {
      const p = byName.get(m);
      return p ? `[${m}](<${p}>)` : m;
    });
  let out = '';
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = tokenRe.exec(md))) {
    out += linkifyPlain(md.slice(last, m.index));
    out += m[0];
    last = m.index + m[0].length;
  }
  out += linkifyPlain(md.slice(last));
  return out;
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// ── 右栏子面板 ──────────────────────────────────────────────────────────

function ResourcePanel({ taskConfig, resources }: { taskConfig: TaskConfig; resources?: TerminalResources }) {
  const ws = resources?.workspaces.find((w) => w.id === taskConfig.workspace_id);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div>
        <Typography.Text type="secondary">工作空间</Typography.Text>
        <div><Tag color={ws ? 'blue' : 'default'}>{ws ? ws.name : '未选择'}</Tag></div>
      </div>
      <div>
        <Typography.Text type="secondary">技能</Typography.Text>
        <div><Tag color="blue">由所选智能体显式绑定（可选库 {resources?.skills.length ?? 0}）</Tag></div>
      </div>
      <div>
        <Typography.Text type="secondary">本体</Typography.Text>
        <div><Tag color="blue">按权限自动注入 {resources?.ontologies.length ?? 0}</Tag></div>
      </div>
      <div>
        <Typography.Text type="secondary">知识库</Typography.Text>
        <div><Tag color="blue">由所选智能体显式绑定（可选库 {resources?.rags.length ?? 0}）</Tag></div>
      </div>
      <div>
        <Typography.Text type="secondary">长期记忆</Typography.Text>
        <div><Tag color="blue">按权限自动载入 4 级</Tag></div>
      </div>
    </div>
  );
}

function FilePanel({ workspaceId }: { workspaceId: string | null }) {
  const [files, setFiles] = useState<WorkspaceFileListItem[]>([]);
  // 复用 BrowserDrawer 预览（与「工作空间管理」页同一组件，消除两处功能差异）
  const [browserOpen, setBrowserOpen] = useState(false);
  const [browserHref, setBrowserHref] = useState<string | null>(null);
  const [browserSeq, setBrowserSeq] = useState(0);

  const load = useCallback(async () => {
    if (!workspaceId) { setFiles([]); return; }
    try { setFiles(await terminal.listWsFiles(workspaceId)); } catch { setFiles([]); }
  }, [workspaceId]);

  useEffect(() => { load(); }, [load]);

  // 解析文件路径为可渲染 Source（http 链接按扩展名，工作空间文件统一走 classifyFile）
  const resolveHref = useCallback(async (rawHref: string): Promise<Source> => {
    if (/^https?:\/\//i.test(rawHref)) return classifyUrl(rawHref);
    let href = rawHref;
    try { href = decodeURIComponent(rawHref); } catch { /* 非法转义，保留原值 */ }
    if (!workspaceId) return { kind: 'unsupported', href, note: '该任务未绑定工作空间' };
    let list: WorkspaceFileListItem[];
    try { list = await terminal.listWsFiles(workspaceId); }
    catch { return { kind: 'unsupported', href, note: '工作空间文件读取失败' }; }
    const f = list.find((x) => x.path === href || x.path.endsWith('/' + href) || href.endsWith(x.path));
    if (!f) return { kind: 'unsupported', href, note: `未找到该文件：${href}` };
    try { return classifyFile(await terminal.getWsFile(f.id)); }
    catch { return { kind: 'unsupported', href, note: '文件详情读取失败' }; }
  }, [workspaceId]);

  if (!workspaceId) return <Empty description="该任务未绑定工作空间" image={Empty.PRESENTED_IMAGE_SIMPLE} />;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <Typography.Text type="secondary">工作空间文件（点击预览，智能体可读写）</Typography.Text>
      <Tree
        treeData={files.map((f) => ({ key: f.path, title: f.path, icon: <FileTextOutlined /> }))}
        height={200}
        onSelect={(keys) => {
          const p = keys[0] as string | undefined;
          if (!p) return;
          setBrowserHref(p);
          setBrowserSeq((n) => n + 1);
          setBrowserOpen(true);
        }}
      />
      <BrowserDrawer
        key={browserSeq}
        open={browserOpen}
        initialHref={browserHref}
        onClose={() => setBrowserOpen(false)}
        resolveHref={resolveHref}
        loadOriginalPreview={terminal.getWsFileOriginalPreview}
        loadOriginalFile={terminal.downloadWsFile}
      />
    </div>
  );
}

function MemoryPanel({ items }: { items: TerminalMemoryItem[] }) {
  const scopeColor: Record<string, string> = { organization: 'blue', department: 'cyan', team: 'green', user: 'purple' };
  if (items.length === 0) return <Empty description="暂无记忆" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  return (
    <div>
      {items.map((m, i) => (
        <div key={i} style={{ padding: '8px 0', borderBottom: `1px solid ${WB.border}` }}>
          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 4 }}>
            <Tag color={scopeColor[m.scope_type] || 'default'}>{m.scope_type}</Tag>
            <Tag>{m.category}</Tag>
            {m.source === 'auto' && <Tag color="purple">智能体沉淀</Tag>}
          </div>
          <Typography.Text style={{ fontSize: 12 }}>{m.content}</Typography.Text>
        </div>
      ))}
    </div>
  );
}

// ── 共享样式 ─────────────────────────────────────────────────────────────

/** 左侧功能菜单项样式：active 态用主色高亮，否则中性灰。 */
function navItemStyle(active: boolean): CSSProperties {
  return {
    display: 'flex', alignItems: 'center', gap: 12, padding: '8px 12px', borderRadius: 8,
    cursor: 'pointer', fontSize: 13,
    color: active ? WB.primary : '#4b5563',
    background: active ? `${WB.primary}1A` : undefined,
  };
}

const chipBtnStyle: CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, color: '#4b5563',
  background: 'transparent', border: 'none', cursor: 'pointer', padding: 0,
};
