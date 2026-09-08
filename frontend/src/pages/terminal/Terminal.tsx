import {
  useCallback, useDeferredValue, useEffect, useRef, useState, forwardRef, useImperativeHandle, useMemo,
  type ChangeEvent, type ClipboardEvent as ReactClipboardEvent, type CSSProperties, type DragEvent as ReactDragEvent,
  type Dispatch, type FormEvent, type KeyboardEvent, type ReactNode, type SetStateAction,
} from 'react';
import {
  ConfigProvider, Button, Typography, Input, Tag, Drawer, Dropdown, Tabs, Empty, Spin,
  message, Avatar, Popover, Tooltip,
} from 'antd';
import {
  PlusOutlined, SendOutlined, RobotOutlined, SettingOutlined, FileTextOutlined,
  LogoutOutlined, DatabaseOutlined, PartitionOutlined,
  UnorderedListOutlined, BookOutlined,
  FolderOpenOutlined, MoreOutlined, ThunderboltOutlined,
  AppstoreOutlined, CheckCircleOutlined,
  DownOutlined,
  CloseOutlined, DeleteOutlined,
  SearchOutlined, UploadOutlined, EditOutlined,
  MenuUnfoldOutlined, MenuFoldOutlined, HistoryOutlined,
  PushpinOutlined, PushpinFilled,
  AudioOutlined, PauseOutlined, CaretRightOutlined, StopOutlined,
} from '@ant-design/icons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import {
  terminal, multimodal, type TaskConfig, type TerminalTask,
  type TerminalResources, type TerminalMemoryItem, type TerminalModels, type TerminalAgent, type WorkspaceFileListItem,
  type TerminalTaskWithMessages,
  type SkillFolderSummary, type WorkspaceFileSummary, type TerminalEnterpriseApplication,
  type WorkspaceFileEvent, type WorkspaceFileRefV1,
  type TerminalApprovalOutcome, type TerminalApprovalDecidedBy,
  WORKSPACE_MAX_FILE_BYTES,
} from '../../api/client';
import { useUserAuth } from '../../context/UserAuthContext';
import TaskConfigDrawer from './TaskConfigDrawer';
import BrowserDrawer, { classifyFile, classifyUrl, type Source } from './BrowserDrawer';
import WorkspaceManagerView from './WorkspaceManagerView';
import KnowledgeBaseView from './KnowledgeBaseView';
import SkillManagerView from './SkillManagerView';
import AgentManagerView from './AgentManagerView';
import EnterpriseApplicationView, {
  businessArtifactsFromMessage, type BusinessAssistantTurnResult,
} from './EnterpriseApplicationView';
import { useMobileBackDismiss, useResponsiveLayout } from '../../hooks/useResponsiveLayout';
import ConfirmModal from '../../components/finder/ConfirmModal';
import BrandLogoSlot, { BRAND_LOGO_SLOTS, applyBrandFavicon } from '../../branding/BrandLogoSlot';
import { BRAND_TITLES, useBrandTitle } from '../../branding/brand';
import './TerminalApplicationShell.css';
import { removeAttachmentReferenceTokens, workspaceDisplayName } from '../../utils/workspacePresentation';
import { parseWorkspaceInternalUrl, workspaceFileLabel, workspaceInternalPath } from '../../utils/workspaceFileLinks';
import { useWorkspaceFileEvents } from '../../hooks/useWorkspaceFileEvents';
import { resolveBusinessConversationId } from '../../utils/businessConversation';
import { AssistantBubble, MessageTimestamp } from './TerminalAssistantMessage';
import { FilePanel, MemoryPanel, ResourcePanel } from './TerminalPanels';
import {
  consumeTerminalEventStream, dropTurnFromChat, messageFileRefLabel, POLICY_TRACE_TITLE, restoreChat,
} from './terminalConversationModel';
import type {
  Block, ChatFileLink, ChatMsg, InvokedSkill, MessageAttachment, TraceCategory,
} from './terminalConversationTypes';

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

type TerminalView = 'assistant' | 'workspaces' | 'agents' | 'knowledge' | 'skills' | 'application';

function viewFromQuery(search: string): TerminalView {
  const value = new URLSearchParams(search).get('view');
  if (value === 'workspace') return 'workspaces';
  if (value === 'agents' || value === 'knowledge' || value === 'skills' || value === 'application') return value;
  return 'assistant';
}

const APPLICATION_NAV_PIN_KEY_PREFIX = 'zhuojian_terminal_application_nav_pinned';

function applicationNavPinKey(userId?: string | null): string | null {
  return userId ? `${APPLICATION_NAV_PIN_KEY_PREFIX}:${userId}` : null;
}

function readApplicationNavPinPreference(userId?: string | null): boolean {
  const key = applicationNavPinKey(userId);
  if (!key) return false;
  try {
    return window.localStorage.getItem(key) === 'true';
  } catch {
    return false;
  }
}

type RuntimeUiStatus = {
  status: 'queued' | 'running' | 'cancelled' | 'timeout' | 'runner_busy';
  position?: number;
};

type ComposerAttachmentStatus = 'uploading' | 'validating' | 'parsing' | 'ready' | 'failed';

interface ComposerAttachment extends MessageAttachment {
  client_id: string;
  file: File;
  file_id: string;
  status: ComposerAttachmentStatus;
  progress: number;
  error?: string;
  raw_tool?: 'image_tool' | 'archive_tool' | 'audio_tool';
}

const MAX_ATTACHMENT_BYTES = WORKSPACE_MAX_FILE_BYTES;
const MAX_ATTACHMENTS = 5;
const MAX_UPLOAD_CONCURRENCY = 2;
const MAX_ATTACHMENT_LABEL = WORKSPACE_MAX_FILE_BYTES >= 1024 ** 3
  ? `${Math.round(WORKSPACE_MAX_FILE_BYTES / 1024 ** 3)}GB`
  : `${Math.round(WORKSPACE_MAX_FILE_BYTES / 1024 ** 2)}MB`;

function rawAttachmentTool(name: string): ComposerAttachment['raw_tool'] {
  const lower = name.trim().toLowerCase();
  if (/\.(?:png|jpe?g|webp|tiff?|bmp|pdf)$/.test(lower)) return 'image_tool';
  if (/\.(?:zip|tar|tgz|tar\.gz)$/.test(lower)) return 'archive_tool';
  if (/\.(?:mp3|wav|m4a|webm|opus)$/.test(lower)) return 'audio_tool';
  return undefined;
}

function safeAttachmentName(name: string): string {
  const cleaned = name.replace(/[\\/:*?"<>|\u0000-\u001f]/g, '_').trim() || '未命名文件';
  return cleaned.length <= 180 ? cleaned : cleaned.slice(cleaned.length - 180);
}

function attachmentPath(scopeKey: string, name: string): string {
  const stamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d{3}Z$/, 'Z');
  return `会话附件/${scopeKey}/${stamp}-${crypto.randomUUID().slice(0, 8)}-${safeAttachmentName(name)}`;
}

interface BrowserFileHandle {
  getFile: () => Promise<File>;
}

type BrowserWindowWithFilePicker = Window & typeof globalThis & {
  showOpenFilePicker?: (options?: { multiple?: boolean }) => Promise<BrowserFileHandle[]>;
};

const COMPOSER_PLACEHOLDER = '描述你要完成的任务…通用智能体可按需调用技能、处理工作空间文件并使用记忆；RAG仅随专业智能体固定加载。';

/** 执行模式：Craft 自主执行 / Ask 只读问答 / Plan 出方案不执行。 */
const EXEC_MODES: { key: TaskConfig['exec_mode']; label: string; desc: string }[] = [
  { key: 'craft', label: 'Craft 动手', desc: '自主多步执行：读写工作空间、调用技能' },
  { key: 'ask', label: 'Ask 问答', desc: '只读单轮问答，不调用工具、不改文件' },
  { key: 'plan', label: 'Plan 规划', desc: '产出分步计划，不执行' },
];
const EXEC_LABEL: Record<TaskConfig['exec_mode'], string> = { craft: 'Craft', ask: 'Ask', plan: 'Plan' };

/** WorkBuddy 风格两栏：窗口标题栏 / 左侧栏（新建+任务列表+用户）/ 右侧主区（首页欢迎 or 聊天）。 */
export default function Terminal() {
  useBrandTitle(BRAND_TITLES.terminal);

  const { user, logout } = useUserAuth();
  const qc = useQueryClient();
  const location = useLocation();
  const navigate = useNavigate();
  const { slug, taskId } = useParams<{ slug?: string; taskId?: string }>();
  const terminalBasePath = slug ? `/${slug}/terminal` : '/terminal';

  const [selectedId, setSelectedId] = useState<string | null>(() => taskId || null);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  // 删除确认弹窗：界面正中模态框（统一用共享 ConfirmModal）。
  const [delConfirm, setDelConfirm] = useState<{ id: string; title: string } | null>(null);
  // 删除单轮对话确认弹窗：只删一整轮 user+assistant，不删除工作空间文件。
  const [turnDelConfirm, setTurnDelConfirm] = useState<{ taskId: string; messageId: string } | null>(null);
  // 任务重命名：内联编辑，Enter 保存、Esc 取消、失焦保存
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState('');
  const [taskSearch, setTaskSearch] = useState('');
  const [chat, setChat] = useState<ChatMsg[]>([]);
  const [traceLog, setTraceLog] = useState<Record<string, unknown>[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [runtimeStatus, setRuntimeStatus] = useState<RuntimeUiStatus | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [activeTab, setActiveTab] = useState('resources');
  const abortRef = useRef<AbortController | null>(null);
  // 标记「本次选中是刚创建并立即 live 执行的任务」——此时 chat 由 runStream 实时维护，
  // 不应从 DB 回放（任务在执行结束前还没有 TaskMessage，回放会用空消息清掉实时轨迹）。
  const skipRestoreRef = useRef(false);
  // 重连去重：记录正在 resume 的 task id，避免 useEffect 重入重复调 GET /stream。
  const reconnRef = useRef<string | null>(null);

  // 新建任务作曲器
  const [composerOpen, setComposerOpen] = useState(() => !taskId);
  const [input, setInput] = useState('');
  const [inputSkills, setInputSkills] = useState<InvokedSkill[]>([]);
  const [inputFileRefs, setInputFileRefs] = useState<WorkspaceFileRefV1[]>([]);
  const [inputAttachments, setInputAttachments] = useState<ComposerAttachment[]>([]);
  const [draftAttachmentKey, setDraftAttachmentKey] = useState(() => crypto.randomUUID());
  const [config, setConfig] = useState<TaskConfig>(DEFAULT_CONFIG);
  const [pageContext, setPageContext] = useState<Record<string, unknown>>({});
  const [cfgOpen, setCfgOpen] = useState(false);
  // 终端「选智能体」逐次覆盖（不落库）：选中后随 /run 发送；null=通用智能体。
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);

  // 左侧功能菜单视图：平台核心能力 + 按授权动态加载的企业应用。
  const [view, setView] = useState<TerminalView>(() => viewFromQuery(location.search));
  const [selectedApplicationId, setSelectedApplicationId] = useState<string | null>(() => new URLSearchParams(location.search).get('app'));
  const [selectedApplicationModuleKey, setSelectedApplicationModuleKey] = useState<string | null>(() => new URLSearchParams(location.search).get('module'));
  const [applicationNavOpen, setApplicationNavOpen] = useState(false);
  const [applicationNavPinned, setApplicationNavPinned] = useState(() => readApplicationNavPinPreference(user?.id));
  const [applicationImmersive, setApplicationImmersive] = useState(false);
  const [terminalNavOpen, setTerminalNavOpen] = useState(false);
  const terminalNavRef = useRef<HTMLElement>(null);
  const terminalNavTriggerRef = useRef<HTMLButtonElement>(null);
  const terminalMainRef = useRef<HTMLElement>(null);
  const { isMobile, isCompact } = useResponsiveLayout();
  const closeTerminalNav = useMobileBackDismiss(terminalNavOpen, isMobile, setTerminalNavOpen, 'terminal-navigation');
  const closeApplicationNav = useMobileBackDismiss(applicationNavOpen, isMobile, setApplicationNavOpen, 'application-navigation');
  const [businessTaskSelection, setBusinessTaskSelection] = useState<Record<string, string | null>>(() => {
    const params = new URLSearchParams(location.search);
    const applicationId = params.get('app');
    const conversationId = params.get('conversation');
    return applicationId && conversationId ? { [applicationId]: conversationId } : {};
  });
  const [businessWorkspaceSelection, setBusinessWorkspaceSelection] = useState<Record<string, string>>({});

  const updateApplicationNavPinned = useCallback((pinned: boolean) => {
    setApplicationNavPinned(pinned);
    setApplicationNavOpen(false);
    const key = applicationNavPinKey(user?.id);
    if (!key) return;
    try {
      window.localStorage.setItem(key, String(pinned));
    } catch {
      // 浏览器禁用持久化时仍保留本次会话状态。
    }
  }, [user?.id]);

  useEffect(() => {
    setApplicationNavPinned(readApplicationNavPinPreference(user?.id));
  }, [user?.id]);

  // 跟随输入（选中任务后的对话）
  const [followUp, setFollowUp] = useState('');
  const [followUpSkills, setFollowUpSkills] = useState<InvokedSkill[]>([]);
  const [followUpFileRefs, setFollowUpFileRefs] = useState<WorkspaceFileRefV1[]>([]);
  const [followUpAttachments, setFollowUpAttachments] = useState<ComposerAttachment[]>([]);

  // 浏览器抽屉：点击对话内容中的文件/链接时弹出，内嵌浏览器可预览网页与文档
  const [browserOpen, setBrowserOpen] = useState(false);
  const [browserHref, setBrowserHref] = useState<string | null>(null);
  const [browserFileId, setBrowserFileId] = useState<string | null>(null);
  const [browserVersionId, setBrowserVersionId] = useState<string | null>(null);
  const [fileEventsById, setFileEventsById] = useState<Record<string, WorkspaceFileEvent>>({});

  const refreshWorkspaceFileSnapshots = useCallback(() => {
    void qc.invalidateQueries({ queryKey: ['terminal-all-ws-files'] });
    void qc.invalidateQueries({ queryKey: ['terminal-ws-files'] });
    void qc.invalidateQueries({ queryKey: ['ws-mgr-files'] });
  }, [qc]);

  useWorkspaceFileEvents(!!user, useCallback((event) => {
    setFileEventsById((current) => ({ ...current, [event.file_id]: event }));
    // 文件事件只负责失效缓存；正文和权限始终重新走当前用户鉴权接口。
    refreshWorkspaceFileSnapshots();
  }, [refreshWorkspaceFileSnapshots]), refreshWorkspaceFileSnapshots);

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
  const { data: terminalApplications = [] } = useQuery<TerminalEnterpriseApplication[]>({
    queryKey: ['terminal-applications'], queryFn: () => terminal.applications(),
  });
  const selectedApplication = terminalApplications.find((item) => item.id === selectedApplicationId) ?? null;
  const applicationShellActive = view === 'application' && selectedApplication !== null;
  const effectiveApplicationNavPinned = applicationNavPinned && !isCompact;

  useEffect(() => {
    setApplicationNavOpen(false);
    setApplicationImmersive(false);
  }, [selectedApplicationId]);

  useEffect(() => {
    if (!selectedApplication) return;
    const modules = selectedApplication.modules ?? [];
    if (selectedApplicationModuleKey && modules.some((item) => item.module_key === selectedApplicationModuleKey)) return;
    setSelectedApplicationModuleKey(modules[0]?.module_key ?? null);
  }, [selectedApplication, selectedApplicationModuleKey]);

  useEffect(() => {
    if (view !== 'application') {
      setApplicationNavOpen(false);
      setApplicationImmersive(false);
    }
    setTerminalNavOpen(false);
  }, [view]);

  useEffect(() => {
    if (!isMobile) setTerminalNavOpen(false);
  }, [isMobile]);

  useEffect(() => {
    if (!isMobile || !terminalNavOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const focusable = () => Array.from(terminalNavRef.current?.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    ) ?? []).filter((item) => !item.hasAttribute('disabled'));
    const focusFrame = window.requestAnimationFrame(() => terminalNavRef.current?.focus());
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        closeTerminalNav();
        return;
      }
      if (event.key !== 'Tab') return;
      const items = focusable();
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.cancelAnimationFrame(focusFrame);
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', onKeyDown);
      if (terminalNavRef.current?.contains(document.activeElement)) {
        window.requestAnimationFrame(() => terminalNavTriggerRef.current?.focus());
      }
    };
  }, [closeTerminalNav, isMobile, terminalNavOpen]);

  useEffect(() => {
    const main = terminalMainRef.current;
    if (!main) return undefined;
    if (isMobile && terminalNavOpen) {
      main.setAttribute('inert', '');
      main.setAttribute('aria-hidden', 'true');
    } else {
      main.removeAttribute('inert');
      main.removeAttribute('aria-hidden');
    }
    return () => {
      main.removeAttribute('inert');
      main.removeAttribute('aria-hidden');
    };
  }, [isMobile, terminalNavOpen]);
  // 智能体 chip 文案：业务应用助手优先显示实际应用名，不再退化成“通用”。
  const composerApplication = terminalApplications.find((item) => item.id === config.application_id);
  const agentLabel = selectedAgentId
    ? (agentsList.find((a) => a.id === selectedAgentId)?.name ?? '已选')
    : (composerApplication ? `${composerApplication.name}助手` : '通用');
  const { data: memoryList } = useQuery<TerminalMemoryItem[]>({
    queryKey: ['terminal-memory'], queryFn: () => terminal.memory(),
  });
  const deferredTaskSearch = useDeferredValue(taskSearch.trim());
  const { data: tasks } = useQuery<TerminalTask[]>({
    queryKey: ['terminal-tasks', deferredTaskSearch], queryFn: () => terminal.listTasks(deferredTaskSearch),
  });
  const { data: businessTasks } = useQuery<TerminalTask[]>({
    queryKey: ['terminal-business-tasks', selectedApplication?.id],
    queryFn: () => terminal.listTasks({ applicationId: selectedApplication!.id, limit: 100 }),
    enabled: Boolean(selectedApplication),
  });
  const selectedBusinessTaskId = resolveBusinessConversationId(
    selectedApplicationId,
    Boolean(selectedApplication),
    businessTaskSelection,
    businessTasks ?? [],
  );
  const selectedBusinessWorkspaceId = selectedApplication ? (
    businessWorkspaceSelection[selectedApplication.id]
      ?? resources?.defaults?.workspace_id
      ?? null
  ) : null;
  const businessWorkspaceOptions = (resources?.workspaces ?? [])
    .filter((workspace) => workspace.capabilities?.create)
    .map((workspace) => ({ value: workspace.id, label: workspace.name }));
  const taskGroups = useMemo(() => {
    const filtered = tasks ?? [];
    const startToday = new Date();
    startToday.setHours(0, 0, 0, 0);
    const startYesterday = new Date(startToday); startYesterday.setDate(startYesterday.getDate() - 1);
    const startWeek = new Date(startToday); startWeek.setDate(startWeek.getDate() - 7);
    const buckets: Record<string, TerminalTask[]> = { 今天: [], 昨天: [], '最近 7 天': [], 更早: [] };
    for (const task of filtered) {
      const updated = new Date(task.updated_at);
      const label = updated >= startToday ? '今天' : updated >= startYesterday ? '昨天' : updated >= startWeek ? '最近 7 天' : '更早';
      buckets[label].push(task);
    }
    return Object.entries(buckets).filter(([, items]) => items.length);
  }, [tasks]);
  const { data: selectedTask } = useQuery<TerminalTaskWithMessages>({
    queryKey: ['terminal-task', selectedId],
    queryFn: () => terminal.getTask(selectedId!),
    enabled: !!selectedId,
  });

  useEffect(() => {
    const routeId = taskId || null;
    setSelectedId(routeId);
    if (routeId) {
      setComposerOpen(false);
      setView('assistant');
    } else if (location.pathname === terminalBasePath) {
      setComposerOpen(true);
    }
  }, [taskId]);

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    if (params.get('view') !== 'application') return;
    const applicationId = params.get('app');
    const moduleKey = params.get('module');
    const conversationId = params.get('conversation');
    if (applicationId) {
      setView('application');
      setSelectedApplicationId(applicationId);
      if (moduleKey) setSelectedApplicationModuleKey(moduleKey);
      setBusinessTaskSelection((current) => (
        current[applicationId] === conversationId
          ? current
          : { ...current, [applicationId]: conversationId }
      ));
    }
  }, [location.search]);

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    if (view === 'assistant') params.delete('view');
    else params.set('view', view === 'workspaces' ? 'workspace' : view);
    if (view === 'application' && selectedApplicationId) params.set('app', selectedApplicationId);
    else params.delete('app');
    if (view === 'application' && selectedApplicationModuleKey) params.set('module', selectedApplicationModuleKey);
    else params.delete('module');
    if (view === 'application' && selectedApplicationId && selectedBusinessTaskId) {
      params.set('conversation', selectedBusinessTaskId);
    } else {
      params.delete('conversation');
    }
    if (view !== 'workspaces') {
      params.delete('workspace');
      params.delete('path');
      params.delete('scope');
    }
    const desiredPath = view === 'assistant' && selectedId && !composerOpen
      ? `${terminalBasePath}/tasks/${selectedId}`
      : terminalBasePath;
    const query = params.toString();
    const desired = `${desiredPath}${query ? `?${query}` : ''}`;
    const current = `${location.pathname}${location.search}`;
    const routeTaskId = taskId || null;
    if (routeTaskId !== selectedId && (location.pathname === terminalBasePath || location.pathname.startsWith(`${terminalBasePath}/tasks/`))) return;
    if (desired !== current) navigate(desired, { replace: true });
  }, [composerOpen, location.pathname, location.search, navigate, selectedApplicationId, selectedApplicationModuleKey, selectedBusinessTaskId, selectedId, taskId, terminalBasePath, view]);

  useEffect(() => {
    if (!selectedTask) return;
    const restoredStatus = selectedTask.run_status;
    setRuntimeStatus(restoredStatus === 'queued' || restoredStatus === 'running'
      ? { status: restoredStatus }
      : restoredStatus === 'cancelled'
        ? { status: 'cancelled' }
        : restoredStatus === 'timeout'
          ? { status: 'timeout' }
          : restoredStatus === 'busy'
            ? { status: 'runner_busy' }
            : null);
    // 刚创建并立即 live 执行的任务：chat 由 runStream 实时维护，跳过 DB 回放，仅切到聊天视图。
    if (skipRestoreRef.current) {
      skipRestoreRef.current = false;
      setComposerOpen(false);
      return;
    }
    const restoredChat = restoreChat(selectedTask.messages);
    setChat(restoredChat);
    const persistedRefs = restoredChat
      .flatMap((item) => item.role === 'user' ? (item.fileRefs ?? []) : [])
      .filter((item) => item.scope === 'task');
    setFollowUpFileRefs(Array.from(new Map(persistedRefs.map((item) => [item.file_id, item])).values()));
    setTraceLog([]);
    setComposerOpen(false);
    // 该任务有运行中的 run（后台 detach 执行）→ 自动重连：回放已产出事件 + 续接到 final。
    // 刷新页面/切走再回来不丢进度。reconnRef 防止 useEffect 重入重复发起 GET /stream。
    if (
      ['queued', 'running'].includes(selectedTask.run_status ?? '') &&
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

  // 每次打开「任务资源配置」抽屉时，强制刷新工作空间、技能、RAG 与模型清单，
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

  // BRAND_LOGO_SLOT: 用户端浏览器标签图标，离开时恢复管理端位点。
  useEffect(() => {
    return applyBrandFavicon(BRAND_LOGO_SLOTS.terminalFavicon);
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
      case 'text_retract': {
        updateTurn((bs) => {
          let remaining = Math.max(0, Number(evt.chars) || 0);
          const next = [...bs];
          for (let j = next.length - 1; j >= 0 && remaining > 0; j--) {
            const block = next[j];
            if (block.kind !== 'text') continue;
            if (block.content.length <= remaining) {
              remaining -= block.content.length;
              next.splice(j, 1);
            } else {
              next[j] = { ...block, content: block.content.slice(0, block.content.length - remaining) };
              remaining = 0;
            }
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
        if (evt.ok === false && /runner.*(busy|queue|繁忙|排队)/i.test(String(evt.content ?? ''))) {
          setRuntimeStatus({ status: 'runner_busy' });
        }
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
      case 'approval_request': {
        // 高风险工具审批请求：追加为当前回合的一块卡片。重连回放可能重复下发，按 approval_id 去重。
        const approvalId = String(evt.approval_id ?? '');
        if (!approvalId) break;
        const rawPreview = evt.arguments_preview;
        const argumentsPreview = typeof rawPreview === 'string'
          ? rawPreview
          : rawPreview == null ? '' : JSON.stringify(rawPreview, null, 2);
        updateTurn((bs) => {
          if (bs.some((b) => b.kind === 'approval' && b.approvalId === approvalId)) return bs;
          return [...bs, {
            kind: 'approval',
            approvalId,
            tool: String(evt.tool ?? ''),
            reason: String(evt.reason ?? ''),
            argumentsPreview,
            expiresAt: String(evt.expires_at ?? ''),
            runId: typeof evt.run_id === 'number' ? evt.run_id : undefined,
          }];
        });
        break;
      }
      case 'approval_decided': {
        // 只更新已知卡片；回放顺序错位（先 decided 后 request）时忽略即可，request 到达时已过期会自行显示为不可操作。
        const approvalId = String(evt.approval_id ?? '');
        if (!approvalId) break;
        updateTurn((bs) => {
          const j = bs.findIndex((b) => b.kind === 'approval' && b.approvalId === approvalId);
          if (j < 0) return bs;
          const cur = bs[j] as Extract<Block, { kind: 'approval' }>;
          const next = [...bs];
          next[j] = {
            ...cur,
            outcome: (evt.outcome as TerminalApprovalOutcome) ?? cur.outcome,
            decidedBy: (evt.decided_by as TerminalApprovalDecidedBy) ?? cur.decidedBy,
          };
          return next;
        });
        break;
      }
      case 'run_status': {
        const status = String(evt.status ?? '');
        if (status === 'queued') {
          setRuntimeStatus({ status: 'queued', position: Number(evt.position) || undefined });
        } else if (status === 'running') {
          setRuntimeStatus({ status: 'running' });
        }
        break;
      }
      case 'trace': {
        // 原生资源调用痕迹（RAG/记忆/文件）+ policy；Skill 走 tool_call。
        // policy 类 approval_requested/approval_decided 只作为轻量痕迹渲染，审批卡片本体由 approval_request 事件负责。
        const { category: _c, title: _t, ...rest } = evt as Record<string, unknown>;
        const category = (evt.category as TraceCategory) ?? 'rag';
        let title = (evt.title as string) ?? '';
        if (!title && category === 'policy') {
          title = POLICY_TRACE_TITLE[String(evt.action ?? '')] ?? String(evt.action ?? '策略');
        }
        updateTurn((bs) => [...bs, {
          kind: 'trace',
          category,
          title: title || (evt.category as string) || '',
          detail: rest,
        }]);
        break;
      }
      case 'vision_preprocess': {
        updateTurn((bs) => [...bs, {
          kind: 'trace', category: 'file', title: '视觉输入预处理', detail: evt,
        }]);
        if (evt.status === 'failed') message.error((evt.error as string) || '图片处理失败');
        break;
      }
      case 'error':
        if (/排队|queue.*(timeout|300)/i.test(String(evt.message ?? ''))) {
          setRuntimeStatus({ status: 'timeout' });
        } else if (/(runtime|runner).*(busy|queue.*full)|等待队列已满/i.test(String(evt.message ?? ''))) {
          setRuntimeStatus({ status: 'runner_busy' });
        }
        message.error(evt.message as string);
        updateTurn((bs) => [...bs, { kind: 'text', content: `⚠️ ${evt.message}` }]);
        break;
      case 'done':
        setRuntimeStatus(null);
        break;
      // 'final' / 'step' (legacy) — 无需特殊渲染
      default:
        break;
    }
  }, [updateTurn]);

  // SSE 读取循环：解析 `data: {...}` 行并派发。POST /run 与 GET /stream 共用。
  const consumeSSE = useCallback(async (resp: Response) => {
    await consumeTerminalEventStream(resp, dispatchEvent);
  }, [dispatchEvent]);

  const runStream = useCallback(async (
    taskId: string, msg: string, attachments: MessageAttachment[] = [], invokedSkills: InvokedSkill[] = [],
    applicationId?: string | null, currentPageContext: Record<string, unknown> = {},
    fileRefs: WorkspaceFileRefV1[] = [],
  ) => {
    // 乐观载入：立即显示用户消息 + 一个「思考中」回合，第一时间给反馈
    // 该轮若选了智能体，把智能体名挂到用户消息上，气泡内按技能 chip 同款展示（逐次覆盖、不落库）。
    const turnAgentName = selectedAgentId ? agentLabel : null;
    const optimisticCreatedAt = new Date().toISOString();
    setChat((c) => [
      ...c,
      { role: 'user', content: msg, createdAt: optimisticCreatedAt, agentName: turnAgentName, attachments, fileRefs, invokedSkills },
      { role: 'assistant', content: '', createdAt: optimisticCreatedAt, blocks: [{ kind: 'phase', index: 0 }] },
    ]);
    setTraceLog([]);
    setRuntimeStatus(null);
    setStreaming(true);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const requestRefs = Array.from(new Map([
        ...attachments.map((item) => ({ file_id: item.file_id, scope: 'turn' as const, follow_latest: true })),
        ...fileRefs,
      ].map((item) => [item.file_id, item])).values());
      const resp = await terminal.runTaskStream(
        taskId, msg, controller.signal, selectedAgentId, attachments.map((item) => item.file_id),
        invokedSkills.map((item) => item.id),
        applicationId, currentPageContext, requestRefs,
      );
      if (!resp.ok || !resp.body) {
        const err = await resp.json().catch(() => ({}));
        const detail = err.detail;
        const detailMessage = typeof detail === 'string'
          ? detail
          : Array.isArray(detail)
            ? detail.map((item) => (
              item && typeof item === 'object' && typeof item.msg === 'string'
                ? item.msg
                : JSON.stringify(item)
            )).join('；')
            : null;
        throw new Error(detailMessage || `HTTP ${resp.status}`);
      }
      await consumeSSE(resp);
      qc.invalidateQueries({ queryKey: ['terminal-tasks'] });
      qc.invalidateQueries({ queryKey: ['terminal-task', taskId] });
      qc.invalidateQueries({ queryKey: ['terminal-memory'] });
      // 刷新工作空间文件清单：让本轮新生成的文件在对话正文里变为可点击
      qc.invalidateQueries({ queryKey: ['terminal-ws-files'] });
      qc.invalidateQueries({ queryKey: ['terminal-all-ws-files'] });
      // 流式结束后从 DB 回填消息 id 和服务端时间。保留 live blocks，只同步持久化字段。
      try {
        const fresh = await terminal.getTask(taskId);
        const dbUsers = fresh.messages.filter((m) => m.role === 'user');
        const dbAssistants = fresh.messages.filter((m) => m.role === 'assistant');
        let userIdx = 0;
        let assistantIdx = 0;
        setChat((c) => c.map((m) => {
          if (m.role === 'user') {
            const dbm = dbUsers[userIdx++];
            return dbm ? { ...m, id: dbm.id, createdAt: dbm.created_at } : m;
          }
          const dbm = dbAssistants[assistantIdx++];
          return dbm ? { ...m, createdAt: dbm.updated_at || dbm.created_at } : m;
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
      return [...c, { role: 'assistant', content: '', createdAt: new Date().toISOString(), blocks: [{ kind: 'phase', index: 0 }] }];
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
    if (id !== selectedId) {
      setFollowUpAttachments([]);
      setFollowUpSkills([]);
      setFollowUpFileRefs([]);
    }
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
    navigate(id ? `${terminalBasePath}/tasks/${id}` : terminalBasePath);
  }, [selectedId, abortActiveStream, navigate, qc, terminalBasePath]);

  const openTaskFromHistory = useCallback((task: TerminalTask) => {
    const applicationId = task.config?.application_id;
    if (applicationId) {
      const application = terminalApplications.find((item) => item.id === applicationId);
      if (!application) {
        message.error('该业务对话所属应用当前不可用或已取消授权');
        return;
      }
      const pageContext = task.last_page_context ?? {};
      const moduleKey = typeof pageContext.module_key === 'string'
        ? pageContext.module_key
        : application.modules?.[0]?.module_key ?? null;
      setComposerOpen(false);
      setSelectedApplicationId(applicationId);
      setSelectedApplicationModuleKey(moduleKey);
      setBusinessTaskSelection((current) => ({ ...current, [applicationId]: task.id }));
      setView('application');
      setApplicationNavOpen(false);
      navigate(terminalBasePath);
      return;
    }
    void selectTask(task.id);
    setView('assistant');
    setApplicationNavOpen(false);
  }, [navigate, selectTask, terminalApplications, terminalBasePath]);

  const resumeBusinessTask = useCallback(async (
    taskId: string,
    applicationId: string,
    onProgress: (event: Record<string, unknown>) => void,
  ): Promise<BusinessAssistantTurnResult> => {
    const controller = new AbortController();
    let response = await terminal.streamTask(taskId, controller.signal);
    let streamedAnswer = '';
    let streamedError = '';
    let streamedRunId: number | null = null;
    let streamInterrupted = false;
    let refreshRequired = false;
    let completed = false;
    for (let attempt = 0; attempt < 3 && !completed; attempt += 1) {
      if (!response.ok || !response.body) {
        throw new Error(`业务小助手连接恢复失败（HTTP ${response.status}）`);
      }
      let sawFinal = false;
      if (attempt > 0) {
        streamedAnswer = '';
        streamedError = '';
      }
      try {
        await consumeTerminalEventStream(response, (event) => {
          onProgress({ ...event, task_id: taskId });
          if (event.type === 'text') streamedAnswer += String(event.delta ?? '');
          if (event.type === 'error') streamedError = String(event.message ?? '业务小助手执行失败');
          if (event.type === 'final') sawFinal = true;
          if (event.type === 'final' && event.interrupted === true) streamInterrupted = true;
          if (event.type === 'tool_result' && event.business_mutation_committed === true) {
            refreshRequired = true;
          }
          if (typeof event.run_id === 'number') streamedRunId = event.run_id;
        });
      } catch (streamError) {
        if ((streamError as Error).name === 'AbortError' || attempt === 2) throw streamError;
      }
      if (sawFinal) {
        completed = true;
        break;
      }
      response = await terminal.streamTask(taskId, controller.signal);
    }
    if (!completed) throw new Error('业务小助手连接恢复失败，请稍后重试');
    if (streamedError) throw new Error(streamedError);
    await qc.invalidateQueries({ queryKey: ['terminal-business-task', taskId] });
    await qc.invalidateQueries({ queryKey: ['terminal-business-tasks', applicationId] });
    const freshTask = await terminal.getTask(taskId, applicationId);
    const assistantMessage = [...freshTask.messages].reverse().find((item) => item.role === 'assistant');
    const userMessage = [...freshTask.messages].reverse().find((item) => item.role === 'user');
    return {
      taskId,
      runId: streamedRunId,
      userMessageId: userMessage?.id ?? null,
      assistantMessageId: assistantMessage?.id ?? null,
      status: streamInterrupted
        ? 'interrupted'
        : freshTask.run_status === 'cancelled'
        ? 'cancelled'
        : ['error', 'timeout', 'busy'].includes(freshTask.run_status ?? '') ? 'failed' : 'completed',
      content: assistantMessage?.content || streamedAnswer || '操作已完成。',
      artifacts: businessArtifactsFromMessage(assistantMessage),
      error: null,
      refreshRequired,
      intent: assistantMessage?.metadata?.business_turn_intent as Record<string, unknown> | undefined,
      pageContext: assistantMessage?.metadata?.page_context as Record<string, unknown> | undefined,
      toolExecutions: Array.isArray(assistantMessage?.metadata?.tool_executions)
        ? assistantMessage.metadata.tool_executions as Array<Record<string, unknown>>
        : [],
      navigationSuggestion: assistantMessage?.metadata?.navigation_suggestion as Record<string, unknown> | undefined,
    };
  }, [qc]);

  const stopStream = () => {
    abortRef.current?.abort();
    setStreaming(false);
    setRuntimeStatus({ status: 'cancelled' });
    // 真停后台 detach 任务（非仅断读端），避免 run 继续耗 LLM 配额
    if (selectedId) terminal.cancelTask(selectedId).catch(() => { /* 静默 */ });
  };

  const startTask = async () => {
    const readyAttachments = inputAttachments.filter((item) => item.status === 'ready' && item.file_id);
    if ((!input.trim() && !readyAttachments.length && !inputSkills.length && !inputFileRefs.length) || streaming) return;
    if (!config.model_alias) {
      message.warning('请先选择模型后再执行');
      setCfgContext('composer'); setCfgOpen(true);
      return;
    }
    const msg = input.trim() || (readyAttachments.length
      ? `请分析附件：${readyAttachments.map((item) => item.name).join('、')}`
      : inputSkills.length
        ? `请使用本轮选择的技能：${inputSkills.map((item) => item.name).join('、')}`
        : '请处理已引用的工作空间文件');
    const attachmentSnapshots: MessageAttachment[] = readyAttachments.map(({ file_id, workspace_id, path, name }) => ({
      file_id, workspace_id, path, name,
    }));
    try {
      const task = await terminal.createTask({ message: msg, config });
      // 新建后立即让左栏任务列表可见（不再等流结束才 invalidate）——根治「执行期间左栏看不到任务」诱因。
      qc.invalidateQueries({ queryKey: ['terminal-tasks'] });
      // 标记本次选中是「新建并立即 live 执行」，阻止 selectedTask 回放清掉实时轨迹；
      // 同时立即切到聊天视图，让用户第一时间看到执行过程。
      skipRestoreRef.current = true;
      setComposerOpen(false);
      setSelectedId(task.id);
      navigate(`${terminalBasePath}/tasks/${task.id}`);
      setInput('');
      const invokedSkills = [...inputSkills];
      const selectedFileRefs = [...inputFileRefs];
      setFollowUpFileRefs(selectedFileRefs.filter((item) => item.scope === 'task'));
      setInputSkills([]);
      setInputFileRefs([]);
      setInputAttachments([]);
      await runStream(task.id, msg, attachmentSnapshots, invokedSkills, config.application_id, pageContext, selectedFileRefs);
      setPageContext({});
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  const sendFollowUp = async () => {
    const readyAttachments = followUpAttachments.filter((item) => item.status === 'ready' && item.file_id);
    if (!selectedId || (!followUp.trim() && !readyAttachments.length && !followUpSkills.length && !followUpFileRefs.length) || streaming) return;
    if (!taskConfig.model_alias) {
      message.warning('请先选择模型后再执行');
      setCfgContext('chat'); setCfgOpen(true);
      return;
    }
    const msg = followUp.trim() || (readyAttachments.length
      ? `请分析附件：${readyAttachments.map((item) => item.name).join('、')}`
      : followUpSkills.length
        ? `请使用本轮选择的技能：${followUpSkills.map((item) => item.name).join('、')}`
        : '请继续处理任务中引用的工作空间文件');
    const attachmentSnapshots: MessageAttachment[] = readyAttachments.map(({ file_id, workspace_id, path, name }) => ({
      file_id, workspace_id, path, name,
    }));
    const invokedSkills = [...followUpSkills];
    setFollowUp('');
    setFollowUpSkills([]);
    setFollowUpAttachments([]);
    await runStream(selectedId, msg, attachmentSnapshots, invokedSkills, taskConfig.application_id, {}, followUpFileRefs);
  };

  const newTask = () => {
    // 断开当前 SSE 读端，否则切回运行中任务时 reconnect 被 !abortRef.current 跳过，执行过程消失。
    abortActiveStream();
    skipRestoreRef.current = false;
    setSelectedId(null);
    navigate(terminalBasePath);
    setChat([]);
    setTraceLog([]);
    setComposerOpen(true);
    setInput('');
    setInputSkills([]);
    setInputFileRefs([]);
    setInputAttachments([]);
    setFollowUpAttachments([]);
    setFollowUpSkills([]);
    setFollowUpFileRefs([]);
    setDraftAttachmentKey(crypto.randomUUID());
    setConfig(DEFAULT_CONFIG);
    setPageContext({});
    setSelectedApplicationId(null);
    setView('assistant');
  };

  const deleteTask = async (id: string) => {
    try {
      await terminal.deleteTask(id);
      qc.invalidateQueries({ queryKey: ['terminal-tasks'] });
      qc.invalidateQueries({ queryKey: ['terminal-business-tasks'] });
      if (selectedId === id) newTask();
      message.success('已删除对话，工作空间文件保持不变');
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  const deleteTurn = async (taskId: string, messageId: string) => {
    try {
      await terminal.deleteTaskMessage(taskId, messageId);
      // 乐观更新本地 chat：立即移除该轮对话，避免等回放闪烁
      setChat((c) => dropTurnFromChat(c, messageId));
      // 只刷新对话；工作空间文件拥有独立生命周期，不因删除消息而改变。
      const wsId = (selectedTask?.config ?? config).workspace_id;
      qc.invalidateQueries({ queryKey: ['terminal-task', taskId] });
      if (wsId) qc.invalidateQueries({ queryKey: ['terminal-ws-files', wsId] });
      message.success('已删除该轮对话，工作空间文件保持不变');
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
    id: f.id,
    path: f.path,
    name: workspaceDisplayName(f),
    originalName: workspaceDisplayName(f),
    size: f.size,
    mimeType: f.mime_type,
    parseStatus: f.parse_status,
    updatedAt: f.updated_at,
  }));
  // 跨工作空间文件清单（与 @ 选择器同源），供用户消息气泡把 @fileId 还原为文件路径
  const { data: allWsFiles } = useQuery<WorkspaceFileSummary[]>({
    queryKey: ['terminal-all-ws-files'],
    queryFn: () => terminal.listAllWsFiles(),
  });
  const fileRefMap = useMemo(() => {
    const m = new Map<string, WorkspaceFileSummary>();
    (allWsFiles ?? []).forEach((f) => m.set(f.id, f));
    return m;
  }, [allWsFiles]);
  const loadReferencedFile = useCallback(async (fileId: string) => {
    const file = await terminal.getWsFile(fileId);
    const summary = fileRefMap.get(fileId);
    const workspace = resources?.workspaces.find((item) => item.id === file.workspace_id);
    return {
      ...file,
      workspace_name: file.workspace_name || summary?.workspace_name || workspace?.name,
      workspace_slug: file.workspace_slug || summary?.workspace_slug || workspace?.slug,
      canonical_path: file.canonical_path || summary?.canonical_path,
      current_version_id: file.current_version_id || summary?.current_version_id,
      current_version_no: file.current_version_no ?? summary?.current_version_no,
      capabilities: file.capabilities || file.effective_capabilities || summary?.capabilities
        || summary?.effective_capabilities || workspace?.capabilities,
      internal_url: file.internal_url || summary?.internal_url,
    };
  }, [fileRefMap, resources?.workspaces]);
  const userName = user?.display_name || user?.username || '用户';
  const userInitial = userName.slice(0, 1);

  // 资源配置抽屉的编辑上下文：作曲器（新任务）or 聊天（已存在任务，PATCH 落库）
  const [cfgContext, setCfgContext] = useState<'composer' | 'chat'>('composer');
  const patchTaskConfig = useCallback(async (c: TaskConfig) => {
    if (!selectedId) return false;
    // 智能体为逐次运行覆盖、不落库：PATCH 前剥掉 template_agent_id，避免回写进 task.config。
    const { template_agent_id: _tpl, ...cfgRest } = c;
    void _tpl;
    try {
      await terminal.updateTask(selectedId, { config: cfgRest });
    } catch (e) {
      message.error((e as Error).message);
      return false;
    }
    qc.invalidateQueries({ queryKey: ['terminal-task', selectedId] });
    return true;
  }, [selectedId, qc]);

  // 把对话中的链接 href 解析为浏览器抽屉可渲染的 Source。
  // http(s) → 网页/PDF/Word（按扩展名）；其余视为工作空间文件路径，按当前任务工作空间解析内容。
  const resolveHref = useCallback(async (rawHref: string): Promise<Source> => {
    const internalRef = parseWorkspaceInternalUrl(rawHref);
    if (internalRef) {
      if (internalRef.versionId) return { kind: 'unsupported', href: rawHref, versionId: internalRef.versionId, note: '该历史版本暂不支持在线读取；未回退到当前版本' };
      try { return classifyFile(await loadReferencedFile(internalRef.fileId)); }
      catch { return { kind: 'unsupported', href: rawHref, note: '文件不存在或你没有查看权限' }; }
    }
    if (/^https?:\/\//i.test(rawHref)) return classifyUrl(rawHref);
    // react-markdown 会把含非 ASCII 的链接目标 percent-encode（如中文文件名），
    // 工空间路径匹配前需先解码回原始中文路径。
    let href = rawHref;
    try { href = decodeURIComponent(rawHref); } catch { /* 非法转义，保留原值 */ }
    const files = allWsFiles ?? [];
    const exactMatches = files.filter((file) => (
      file.path === href || file.canonical_path === href || workspaceFileLabel(file) === href
    ));
    const suffixMatches = exactMatches.length ? [] : files.filter((file) => (
      file.path.endsWith(`/${href}`) || href.endsWith(`/${file.path}`)
    ));
    const matches = exactMatches.length ? exactMatches : suffixMatches;
    if (matches.length > 1) {
      return { kind: 'unsupported', href, note: `存在多个同名文件，请使用完整工作空间路径或“复制文件地址”：${href}` };
    }
    const f = matches[0];
    if (!f) return { kind: 'unsupported', href, note: `已授权工作空间中未找到该文件：${href}` };
    try { return classifyFile(await loadReferencedFile(f.id)); }
    catch { return { kind: 'unsupported', href, note: '文件详情读取失败' }; }
  }, [allWsFiles, loadReferencedFile]);

  const openLink = useCallback((href: string) => {
    const internalRef = parseWorkspaceInternalUrl(href);
    setBrowserFileId(internalRef?.fileId ?? null);
    setBrowserVersionId(internalRef?.versionId ?? null);
    setBrowserHref(href);
    setBrowserOpen(true);
  }, []);

  const openWorkspaceFile = useCallback((fileId: string, versionId?: string) => {
    setBrowserFileId(fileId);
    setBrowserVersionId(versionId ?? null);
    setBrowserHref(null);
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
      <div className="terminal-shell" style={{ background: '#f5f5f5', fontFamily: WB_FONT }}>
        {/* 主内容区 */}
        <div className="terminal-shell__body" style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
          {!applicationShellActive && (
            <button
              ref={terminalNavTriggerRef}
              type="button"
              className="terminal-shell__mobile-trigger"
              aria-label={terminalNavOpen ? '关闭平台导航' : '打开平台导航'}
              aria-expanded={terminalNavOpen}
              onClick={() => setTerminalNavOpen((open) => !open)}
            >
              {terminalNavOpen ? <CloseOutlined /> : <MenuUnfoldOutlined />}
            </button>
          )}
          {terminalNavOpen && <button type="button" className="responsive-shell__scrim terminal-shell__scrim" aria-label="关闭平台导航" onClick={closeTerminalNav} />}
          {/* 企业应用使用极窄导航轨；平台其他页面继续使用完整侧栏。 */}
          {applicationShellActive && !applicationImmersive && !effectiveApplicationNavPinned ? (
            <aside className="terminal-app-rail" aria-label="平台快捷导航">
              <Tooltip title="展开平台导航" placement="right">
                <button type="button" className="terminal-app-rail__button terminal-app-rail__button--primary" aria-label="展开平台导航" onClick={() => setApplicationNavOpen(true)}>
                  <MenuUnfoldOutlined />
                </button>
              </Tooltip>
              <Tooltip title="企业应用" placement="right">
                <button type="button" className="terminal-app-rail__button terminal-app-rail__button--active" aria-label="企业应用" onClick={() => setApplicationNavOpen(true)}>
                  <AppstoreOutlined />
                </button>
              </Tooltip>
              <div className="terminal-app-rail__divider" />
              <Tooltip title="工作空间" placement="right">
                <button type="button" className="terminal-app-rail__button" aria-label="工作空间" onClick={() => setView('workspaces')}><FolderOpenOutlined /></button>
              </Tooltip>
              <Tooltip title="智能体" placement="right">
                <button type="button" className="terminal-app-rail__button" aria-label="智能体" onClick={() => setView('agents')}><RobotOutlined /></button>
              </Tooltip>
              <Tooltip title="知识库" placement="right">
                <button type="button" className="terminal-app-rail__button" aria-label="知识库" onClick={() => setView('knowledge')}><BookOutlined /></button>
              </Tooltip>
              <Tooltip title="技能" placement="right">
                <button type="button" className="terminal-app-rail__button" aria-label="技能" onClick={() => setView('skills')}><ThunderboltOutlined /></button>
              </Tooltip>
              <Tooltip title="任务与平台导航" placement="right">
                <button type="button" className="terminal-app-rail__button" aria-label="任务与平台导航" onClick={() => setApplicationNavOpen(true)}><HistoryOutlined /></button>
              </Tooltip>
              <div className="terminal-app-rail__spacer" />
              <Tooltip title={userName} placement="right">
                <button type="button" className="terminal-app-rail__button" aria-label="用户菜单" onClick={() => setApplicationNavOpen(true)}>
                  <Avatar size={28} style={{ background: 'linear-gradient(135deg, #34d399 0%, #14b8a6 100%)' }}>{userInitial}</Avatar>
                </button>
              </Tooltip>
            </aside>
          ) : !applicationShellActive ? (
          <aside
            ref={terminalNavRef}
            className={`terminal-shell__sidebar${terminalNavOpen ? ' terminal-shell__sidebar--open' : ''}`}
            role={isMobile ? 'dialog' : undefined}
            aria-modal={isMobile ? true : undefined}
            aria-label="员工平台导航"
            aria-hidden={isMobile && !terminalNavOpen}
            tabIndex={isMobile ? -1 : undefined}
            onTransitionEnd={() => {
              if (isMobile && terminalNavOpen) terminalNavRef.current?.focus();
            }}
            style={{ width: 224, background: WB.sidebar, borderRight: `1px solid ${WB.border}`, display: 'flex', flexDirection: 'column', flex: '0 0 auto' }}
          >
            <div style={{ padding: 12 }}>
              <Button type="primary" icon={<PlusOutlined />} block onClick={newTask}>新建任务</Button>
            </div>

            <nav style={{ padding: '4px 8px' }}>
              {terminalApplications.length > 0 && (
                <div style={{ padding: '6px 10px 4px', fontSize: 11, color: '#9ca3af', fontWeight: 600, letterSpacing: .4 }}>企业应用</div>
              )}
              {terminalApplications.map((application) => (
                <button
                  type="button"
                  key={application.id}
                  onClick={() => { setSelectedApplicationId(application.id); setView('application'); }}
                  style={navItemStyle(view === 'application' && selectedApplicationId === application.id)}
                >
                  {application.icon_url
                    ? <img src={application.icon_url} alt="" style={{ width: 17, height: 17, borderRadius: 5, objectFit: 'cover' }} />
                    : <AppstoreOutlined style={{ fontSize: 16 }} />}
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{application.name}</span>
                  {application.assistant_enabled && <Tag color="purple" bordered={false} style={{ margin: '0 0 0 auto', fontSize: 9, lineHeight: '17px' }}>AI</Tag>}
                </button>
              ))}
              {terminalApplications.length > 0 && <div style={{ height: 1, background: '#e5e7eb', margin: '8px 10px' }} />}
              <button type="button" onClick={() => setView('workspaces')} style={navItemStyle(view === 'workspaces')}>
                <FolderOpenOutlined style={{ fontSize: 16 }} />
                <span>工作空间</span>
              </button>
              <button type="button" onClick={() => setView('agents')} style={navItemStyle(view === 'agents')}>
                <RobotOutlined style={{ fontSize: 16 }} />
                <span>智能体</span>
              </button>
              <button type="button" onClick={() => setView('knowledge')} style={navItemStyle(view === 'knowledge')}>
                <BookOutlined style={{ fontSize: 16 }} />
                <span>知识库</span>
              </button>
              <button type="button" onClick={() => setView('skills')} style={navItemStyle(view === 'skills')}>
                <ThunderboltOutlined style={{ fontSize: 16 }} />
                <span>技能</span>
              </button>
            </nav>

            {/* 任务列表 */}
            <div style={{ padding: '8px 16px', marginTop: 4 }}>
              <div style={{ fontSize: 12, color: '#6b7280', fontWeight: 500, marginBottom: 8 }}>
                任务 ({tasks?.length ?? 0})
              </div>
              <Input
                allowClear
                size="small"
                prefix={<SearchOutlined />}
                placeholder="搜索任务"
                value={taskSearch}
                onChange={(event) => setTaskSearch(event.target.value)}
                style={{ fontSize: 12 }}
              />
            </div>
            <div style={{ flex: 1, overflowY: 'auto', padding: '0 8px' }} className="wb-scroll-hide">
              {taskGroups.length === 0 && (
                <div style={{ padding: '8px 12px', color: '#9ca3af', fontSize: 12 }}>{taskSearch ? '没有匹配任务' : '暂无任务'}</div>
              )}
              {taskGroups.map(([group, items]) => (
                <div key={group} style={{ marginBottom: 8 }}>
                  <div style={{ padding: '7px 10px 3px', color: '#9ca3af', fontSize: 10, fontWeight: 600 }}>{group}</div>
                  {items.map((t) => {
                    const active = selectedId === t.id && !composerOpen;
                    const editing = editingId === t.id;
                    return (
                      <div
                        key={t.id}
                        onClick={() => { if (!editing) openTaskFromHistory(t); }}
                        onMouseEnter={() => setHoveredId(t.id)}
                        onMouseLeave={() => setHoveredId(null)}
                        style={{
                          display: 'flex', alignItems: 'flex-start', gap: 8, padding: '6px 8px', borderRadius: 6, cursor: 'pointer', fontSize: 12,
                          background: active ? `${WB.primary}1A` : (hoveredId === t.id ? WB.hover : undefined), color: active ? WB.primary : '#6b7280',
                        }}
                      >
                        <FileTextOutlined style={{ marginTop: 2, color: active ? WB.primary : '#cbd5e1' }} />
                        {editing ? (
                          <Input
                            size="small" autoFocus value={editingTitle}
                            onChange={(e) => setEditingTitle(e.target.value)}
                            onClick={(e) => e.stopPropagation()} onPointerDown={(e) => e.stopPropagation()}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') { e.preventDefault(); commitRename(t.id); }
                              else if (e.key === 'Escape') { e.preventDefault(); cancelRename(); }
                            }}
                            onBlur={() => commitRename(t.id)} maxLength={255}
                            style={{ fontSize: 12, padding: '0 6px', height: 24 }}
                          />
                        ) : (
                          <Tooltip title={t.match_excerpt || t.title || '(未命名)'} placement="right">
                            <span style={{ flex: 1, minWidth: 0 }}>
                              <span style={{ display: 'block', lineHeight: 1.4, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t.title || '(未命名)'}</span>
                              {t.config?.application_id && (
                                <span style={{ display: 'block', marginTop: 2, color: '#818cf8', fontSize: 10, lineHeight: 1.35 }}>
                                  {terminalApplications.find((item) => item.id === t.config.application_id)?.name ?? '业务应用'}
                                </span>
                              )}
                              {!!t.match_excerpt && taskSearch && (
                                <span style={{ display: 'block', marginTop: 2, color: '#9ca3af', fontSize: 10, lineHeight: 1.35, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t.match_excerpt}</span>
                              )}
                            </span>
                          </Tooltip>
                        )}
                        {!editing && (
                          <Dropdown
                            trigger={['click']}
                            menu={{ items: [
                              { key: 'rename', label: '重命名', icon: <EditOutlined /> },
                              { key: 'delete', label: '删除', icon: <DeleteOutlined />, danger: true },
                            ], onClick: ({ key, domEvent }) => {
                              domEvent.stopPropagation();
                              if (key === 'rename') startRename(t);
                              else setDelConfirm({ id: t.id, title: t.title || '(未命名)' });
                            } }}
                          >
                            <button aria-label={`管理任务 ${t.title}`} onClick={(event) => event.stopPropagation()} style={{ border: 0, background: 'transparent', color: '#9ca3af', cursor: 'pointer', padding: 0 }}><MoreOutlined /></button>
                          </Dropdown>
                        )}
                      </div>
                    );
                  })}
                </div>
              ))}
            </div>

            {/* 底部用户 */}
            <div style={{ padding: 12, borderTop: `1px solid ${WB.border}`, flex: '0 0 auto' }}>
              <Popover
                trigger="click"
                placement="topLeft"
                content={
                  <div style={{ minWidth: 160 }}>
                    <div style={{ marginBottom: 8, fontSize: 12, color: '#9ca3af' }}>
                      {user?.organization_name || user?.organization_slug || '企业用户'}
                    </div>
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
          ) : null}

          {/* 右侧主区 */}
          <main
            ref={terminalMainRef}
            className="terminal-shell__main"
            style={{
              flex: 1,
              display: 'flex',
              flexDirection: 'column',
              background: '#fff',
              minWidth: 0,
              marginLeft: applicationShellActive && !applicationImmersive && effectiveApplicationNavPinned ? 248 : 0,
              transition: 'margin-left 180ms ease',
            }}
          >
            {view === 'assistant' && runtimeStatus && (
              <div style={{
                margin: '10px 18px 0', padding: '8px 12px', borderRadius: 8, fontSize: 13,
                color: runtimeStatus.status === 'timeout' || runtimeStatus.status === 'runner_busy' ? '#b45309' : '#4338ca',
                background: runtimeStatus.status === 'timeout' || runtimeStatus.status === 'runner_busy' ? '#fffbeb' : '#eef2ff',
                border: `1px solid ${runtimeStatus.status === 'timeout' || runtimeStatus.status === 'runner_busy' ? '#fde68a' : '#c7d2fe'}`,
              }}>
                {runtimeStatus.status === 'queued' && `排队中${runtimeStatus.position ? `（前方约 ${Math.max(0, runtimeStatus.position - 1)} 个任务）` : ''}，可安全离开后再回来查看`}
                {runtimeStatus.status === 'running' && '正在执行，系统已为本任务分配运行资源'}
                {runtimeStatus.status === 'cancelled' && '任务已取消，运行资源已释放'}
                {runtimeStatus.status === 'timeout' && '排队已超时，未消耗模型或脚本执行资源，请稍后重试'}
                {runtimeStatus.status === 'runner_busy' && 'Runner 当前繁忙，本轮脚本未执行或正在等待，请稍后重试'}
              </div>
            )}
            {view === 'workspaces' ? (
              <WorkspaceManagerView
                resources={resources}
                homeDepartmentId={user?.department_id}
                fileEventsById={fileEventsById}
              />
            ) : view === 'agents' ? (
              <AgentManagerView />
            ) : view === 'knowledge' ? (
              <KnowledgeBaseView />
            ) : view === 'skills' ? (
              <SkillManagerView />
            ) : view === 'application' && selectedApplication ? (
              <EnterpriseApplicationView
                application={selectedApplication}
                moduleKey={selectedApplicationModuleKey}
                onModuleChange={setSelectedApplicationModuleKey}
                models={modelData?.models ?? []}
                modelAlias={config.model_alias ?? modelData?.models?.[0] ?? null}
                onModelAliasChange={(modelAlias) => setConfig((current) => ({ ...current, model_alias: modelAlias }))}
                immersive={applicationImmersive}
                onOpenNavigation={() => setApplicationNavOpen(true)}
                onToggleImmersive={() => setApplicationImmersive((value) => !value)}
                businessTaskId={selectedBusinessTaskId}
                businessTasks={businessTasks ?? []}
                onSelectConversation={(taskId) => {
                  setBusinessTaskSelection((current) => ({
                    ...current, [selectedApplication.id]: taskId,
                  }));
                  const params = new URLSearchParams(location.search);
                  params.set('view', 'application');
                  params.set('app', selectedApplication.id);
                  if (selectedApplicationModuleKey) params.set('module', selectedApplicationModuleKey);
                  params.set('conversation', taskId);
                  navigate(`${location.pathname}?${params.toString()}`);
                }}
                onDeleteConversation={async (taskId) => {
                  await terminal.deleteTask(taskId);
                  const nextTask = taskId === selectedBusinessTaskId
                    ? (businessTasks ?? []).find((task) => task.id !== taskId)?.id ?? null
                    : selectedBusinessTaskId;
                  setBusinessTaskSelection((current) => ({
                    ...current, [selectedApplication.id]: nextTask,
                  }));
                  if (taskId === selectedBusinessTaskId) {
                    const params = new URLSearchParams(location.search);
                    if (nextTask) params.set('conversation', nextTask);
                    else params.delete('conversation');
                    navigate(`${location.pathname}${params.toString() ? `?${params.toString()}` : ''}`, { replace: true });
                  }
                  await qc.invalidateQueries({ queryKey: ['terminal-business-tasks', selectedApplication.id] });
                  await qc.invalidateQueries({ queryKey: ['terminal-tasks'] });
                }}
                onNewConversation={async () => {
                  setBusinessTaskSelection((current) => ({
                    ...current, [selectedApplication.id]: null,
                  }));
                  const params = new URLSearchParams(location.search);
                  params.delete('conversation');
                  navigate(`${location.pathname}${params.toString() ? `?${params.toString()}` : ''}`);
                }}
                targetWorkspaceId={selectedBusinessWorkspaceId}
                workspaceOptions={businessWorkspaceOptions}
                onTargetWorkspaceChange={(workspaceId) => setBusinessWorkspaceSelection((current) => ({
                  ...current, [selectedApplication.id]: workspaceId,
                }))}
                onOpenArtifact={(fileId, versionId) => openLink(
                  `${workspaceInternalPath(fileId)}${versionId ? `?version=${encodeURIComponent(versionId)}` : ''}`,
                )}
                onResumeAI={(taskId, onProgress) => resumeBusinessTask(
                  taskId,
                  selectedApplication.id,
                  onProgress,
                )}
                onAskAI={async (prompt, context, onProgress, fileRefs) => {
                  const modelAlias = config.model_alias ?? modelData?.models?.[0] ?? null;
                  if (!modelAlias) throw new Error('当前账号没有可用模型，请联系管理员配置模型权限');
                  const assistantConfig: TaskConfig = {
                    workspace_id: config.workspace_id,
                    model_alias: modelAlias,
                    exec_mode: 'craft',
                    template_agent_id: null,
                    application_id: selectedApplication.id,
                  };
                  let activeTaskId = selectedBusinessTaskId;
                  if (!activeTaskId) {
                    const created = await terminal.createTask({ message: prompt, config: assistantConfig });
                    activeTaskId = created.id;
                    setBusinessTaskSelection((current) => ({
                      ...current, [selectedApplication.id]: created.id,
                    }));
                    qc.invalidateQueries({ queryKey: ['terminal-tasks'] });
                    qc.invalidateQueries({ queryKey: ['terminal-business-tasks', selectedApplication.id] });
                  }
                  const controller = new AbortController();
                  const clientRequestId = crypto.randomUUID();
                  const response = await terminal.runTaskStream(
                    activeTaskId, prompt, controller.signal, null, [], [], selectedApplication.id,
                    context, fileRefs, selectedBusinessWorkspaceId, clientRequestId,
                  );
                  if (!response.ok || !response.body) {
                    const body = await response.json().catch(() => ({}));
                    const detail = body.detail;
                    const errorMessage = typeof detail === 'string'
                      ? detail
                      : Array.isArray(detail)
                        ? detail.map((item) => (
                          item && typeof item === 'object' && typeof item.msg === 'string'
                            ? item.msg
                            : JSON.stringify(item)
                        )).join('；')
                        : `任务执行失败（HTTP ${response.status}）`;
                    throw new Error(errorMessage);
                  }
                  let streamedAnswer = '';
                  let streamedError = '';
                  let streamedRunId: number | null = null;
                  let streamInterrupted = false;
                  let refreshRequired = false;
                  let streamResponse = response;
                  let streamCompleted = false;
                  for (let attempt = 0; attempt < 3 && !streamCompleted; attempt += 1) {
                    let sawFinal = false;
                    if (attempt > 0) {
                      // GET /stream 会完整回放同一 AgentRun；因此正文也从零重建，
                      // 避免断线重连把已收到的 token 重复拼接。
                      streamedAnswer = '';
                      streamedError = '';
                    }
                    try {
                      await consumeTerminalEventStream(streamResponse, (event) => {
                        onProgress({ ...event, task_id: activeTaskId });
                        if (event.type === 'text') streamedAnswer += String(event.delta ?? '');
                        if (event.type === 'error') streamedError = String(event.message ?? '业务小助手执行失败');
                        if (event.type === 'final') sawFinal = true;
                        if (event.type === 'final' && event.interrupted === true) streamInterrupted = true;
                        if (event.type === 'tool_result' && event.business_mutation_committed === true) {
                          refreshRequired = true;
                        }
                        if (typeof event.run_id === 'number') streamedRunId = event.run_id;
                      });
                    } catch (streamError) {
                      if ((streamError as Error).name === 'AbortError' || attempt === 2) throw streamError;
                    }
                    if (sawFinal) {
                      streamCompleted = true;
                      break;
                    }
                    streamResponse = await terminal.streamTask(activeTaskId, controller.signal);
                    if (!streamResponse.ok || !streamResponse.body) {
                      throw new Error(`业务小助手连接恢复失败（HTTP ${streamResponse.status}）`);
                    }
                  }
                  if (!streamCompleted) throw new Error('业务小助手连接中断，请稍后重试');
                  if (streamedError) throw new Error(streamedError);
                  qc.invalidateQueries({ queryKey: ['terminal-task', activeTaskId] });
                  qc.invalidateQueries({ queryKey: ['terminal-business-task', activeTaskId] });
                  qc.invalidateQueries({ queryKey: ['terminal-memory'] });
                  qc.invalidateQueries({ queryKey: ['application-action-confirmations'] });
                  const freshTask = await terminal.getTask(activeTaskId, selectedApplication.id);
                  const assistantMessage = [...freshTask.messages].reverse().find((item) => item.role === 'assistant');
                  const userMessage = [...freshTask.messages].reverse().find((item) => item.role === 'user');
                  const result: BusinessAssistantTurnResult = {
                    taskId: activeTaskId,
                    runId: streamedRunId,
                    userMessageId: userMessage?.id ?? null,
                    assistantMessageId: assistantMessage?.id ?? null,
                    status: streamInterrupted
                      ? 'interrupted'
                      : freshTask.run_status === 'cancelled'
                      ? 'cancelled'
                      : ['error', 'timeout', 'busy'].includes(freshTask.run_status ?? '') ? 'failed' : 'completed',
                    content: assistantMessage?.content || streamedAnswer || '操作已完成。',
                    artifacts: businessArtifactsFromMessage(assistantMessage),
                    error: null,
                    refreshRequired,
                    intent: assistantMessage?.metadata?.business_turn_intent as Record<string, unknown> | undefined,
                    pageContext: (assistantMessage?.metadata?.page_context as Record<string, unknown> | undefined) ?? context,
                    toolExecutions: Array.isArray(assistantMessage?.metadata?.tool_executions)
                      ? assistantMessage.metadata.tool_executions as Array<Record<string, unknown>>
                      : [],
                    navigationSuggestion: assistantMessage?.metadata?.navigation_suggestion as Record<string, unknown> | undefined,
                  };
                  return result;
                }}
              />
            ) : composerOpen ? (
              <HomeView
                input={input} setInput={setInput}
                invokedSkills={inputSkills} setInvokedSkills={setInputSkills}
                fileRefs={inputFileRefs} setFileRefs={setInputFileRefs}
                attachments={inputAttachments} setAttachments={setInputAttachments}
                attachmentScopeKey={`草稿-${draftAttachmentKey}`}
                placeholder={COMPOSER_PLACEHOLDER}
                config={config}
                resources={resources}
                onSetExecMode={(m) => setConfig((c) => ({ ...c, exec_mode: m }))}
                onSetWorkspace={(workspaceId) => {
                  setConfig((current) => ({ ...current, workspace_id: workspaceId }));
                  return true;
                }}
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
                invokedSkills={followUpSkills} setInvokedSkills={setFollowUpSkills}
                fileRefs={followUpFileRefs} setFileRefs={setFollowUpFileRefs}
                attachments={followUpAttachments} setAttachments={setFollowUpAttachments}
                onSend={sendFollowUp} onStop={stopStream}
                onTogglePanel={() => setDrawerOpen(true)}
                onNew={newTask}
                config={taskConfig} resources={resources}
                onSetExecMode={(m) => patchTaskConfig({ ...taskConfig, exec_mode: m })}
                onSetWorkspace={(workspaceId) => patchTaskConfig({ ...taskConfig, workspace_id: workspaceId })}
                onOpenConfig={() => { setCfgContext('chat'); setCfgOpen(true); }}
                onImportSkill={() => setView('skills')}
                selectedId={selectedId}
                onLink={openLink}
                onOpenFile={openWorkspaceFile}
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

          <Drawer
            placement="left"
            width={isMobile ? 'min(88vw, 320px)' : (effectiveApplicationNavPinned ? 248 : 280)}
            open={applicationShellActive && !applicationImmersive && (effectiveApplicationNavPinned || applicationNavOpen)}
            onClose={closeApplicationNav}
            closable={false}
            keyboard={!effectiveApplicationNavPinned}
            mask={!effectiveApplicationNavPinned}
            rootClassName={`terminal-app-nav-drawer${effectiveApplicationNavPinned ? ' terminal-app-nav-drawer--pinned' : ''}`}
            styles={{ body: { padding: 0 }, mask: { background: 'rgba(15, 23, 42, .08)' } }}
          >
            <div className="terminal-app-nav-drawer__panel">
              <div className="terminal-app-nav-drawer__header">
                <Typography.Text strong><AppstoreOutlined style={{ marginRight: 8, color: WB.primary }} />平台导航</Typography.Text>
                <div className="terminal-app-nav-drawer__header-actions">
                  {!isCompact && <Button
                    size="small"
                    type={effectiveApplicationNavPinned ? 'primary' : 'text'}
                    className="terminal-app-nav-drawer__pin"
                    aria-label={effectiveApplicationNavPinned ? '取消固定平台导航' : '固定平台导航'}
                    icon={effectiveApplicationNavPinned ? <PushpinFilled /> : <PushpinOutlined />}
                    onClick={() => updateApplicationNavPinned(!applicationNavPinned)}
                  >
                    {effectiveApplicationNavPinned ? '已固定' : '固定'}
                  </Button>}
                  <Button
                    type="text"
                    aria-label={effectiveApplicationNavPinned ? '收起固定平台导航' : '关闭平台导航'}
                    icon={effectiveApplicationNavPinned ? <MenuFoldOutlined /> : <CloseOutlined />}
                    onClick={() => effectiveApplicationNavPinned ? updateApplicationNavPinned(false) : setApplicationNavOpen(false)}
                  />
                </div>
              </div>

              <div style={{ padding: 12 }}>
                <Button type="primary" icon={<PlusOutlined />} block onClick={() => { setApplicationNavOpen(false); newTask(); }}>新建任务</Button>
              </div>

              <nav style={{ padding: '0 10px' }}>
                {terminalApplications.length > 0 && (
                  <div style={{ padding: '6px 10px 4px', fontSize: 11, color: '#9ca3af', fontWeight: 600, letterSpacing: .4 }}>企业应用</div>
                )}
                {terminalApplications.map((application) => {
                  const modules = application.modules ?? [];
                  const applicationActive = selectedApplicationId === application.id;
                  if (modules.length === 0) {
                    return (
                      <button
                        type="button"
                        key={application.id}
                        onClick={() => {
                          setSelectedApplicationId(application.id);
                          setSelectedApplicationModuleKey(null);
                          setView('application');
                          setApplicationNavOpen(false);
                        }}
                        style={navItemStyle(applicationActive)}
                      >
                        {application.icon_url
                          ? <img src={application.icon_url} alt="" style={{ width: 17, height: 17, borderRadius: 5, objectFit: 'cover' }} />
                          : <AppstoreOutlined style={{ fontSize: 16 }} />}
                        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{application.name}</span>
                        {application.assistant_enabled && <Tag color="purple" bordered={false} style={{ margin: '0 0 0 auto', fontSize: 9, lineHeight: '17px' }}>AI</Tag>}
                      </button>
                    );
                  }
                  return (
                    <div key={application.id} className="terminal-app-nav-group">
                      <div className="terminal-app-nav-group__title">
                        {application.icon_url
                          ? <img src={application.icon_url} alt="" />
                          : <PartitionOutlined />}
                        <span>{application.name}</span>
                        <Tag bordered={false}>{modules.length} 个子模块</Tag>
                      </div>
                      <div className="terminal-app-nav-group__modules">
                        {modules.map((module) => {
                          const active = applicationActive && selectedApplicationModuleKey === module.module_key;
                          return (
                            <button
                              type="button"
                              key={module.module_key}
                              className={`terminal-app-nav-group__module${active ? ' terminal-app-nav-group__module--active' : ''}`}
                              onClick={() => {
                                setSelectedApplicationId(application.id);
                                setSelectedApplicationModuleKey(module.module_key);
                                setView('application');
                                setApplicationNavOpen(false);
                              }}
                            >
                              <span className="terminal-app-nav-group__module-mark" />
                              <span>{module.name}</span>
                              {application.assistant_enabled && <span className="terminal-app-nav-group__ai">AI</span>}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  );
                })}
                {terminalApplications.length > 0 && <div style={{ height: 1, background: '#e5e7eb', margin: '8px 10px' }} />}
                <button type="button" onClick={() => { setApplicationNavOpen(false); setView('workspaces'); }} style={navItemStyle(false)}><FolderOpenOutlined style={{ fontSize: 16 }} /><span>工作空间</span></button>
                <button type="button" onClick={() => { setApplicationNavOpen(false); setView('agents'); }} style={navItemStyle(false)}><RobotOutlined style={{ fontSize: 16 }} /><span>智能体</span></button>
                <button type="button" onClick={() => { setApplicationNavOpen(false); setView('knowledge'); }} style={navItemStyle(false)}><BookOutlined style={{ fontSize: 16 }} /><span>知识库</span></button>
                <button type="button" onClick={() => { setApplicationNavOpen(false); setView('skills'); }} style={navItemStyle(false)}><ThunderboltOutlined style={{ fontSize: 16 }} /><span>技能</span></button>
              </nav>

              <div style={{ padding: '12px 16px 8px' }}>
                <div style={{ fontSize: 12, color: '#6b7280', fontWeight: 500, marginBottom: 8 }}>任务 ({tasks?.length ?? 0})</div>
                <Input allowClear size="small" prefix={<SearchOutlined />} placeholder="搜索任务" value={taskSearch} onChange={(event) => setTaskSearch(event.target.value)} style={{ fontSize: 12 }} />
              </div>
              <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '0 10px 10px' }} className="wb-scroll-hide">
                {taskGroups.length === 0 && <div style={{ padding: '8px 10px', color: '#9ca3af', fontSize: 12 }}>{taskSearch ? '没有匹配任务' : '暂无任务'}</div>}
                {taskGroups.map(([group, items]) => (
                  <div key={group} style={{ marginBottom: 8 }}>
                    <div style={{ padding: '7px 10px 3px', color: '#9ca3af', fontSize: 10, fontWeight: 600 }}>{group}</div>
                    {items.map((task) => {
                      const active = selectedId === task.id && !composerOpen;
                      return (
                        <div
                          key={task.id}
                          onClick={() => openTaskFromHistory(task)}
                          style={{ ...navItemStyle(active), fontSize: 12 }}
                        >
                          <FileTextOutlined style={{ color: active ? WB.primary : '#cbd5e1' }} />
                          <span style={{ minWidth: 0, overflow: 'hidden' }}>
                            <span style={{ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{task.title || '(未命名)'}</span>
                            {task.config?.application_id && <span style={{ display: 'block', color: '#818cf8', fontSize: 10 }}>
                              {terminalApplications.find((item) => item.id === task.config.application_id)?.name ?? '业务应用'}
                            </span>}
                            {!!task.match_excerpt && taskSearch && <span style={{ display: 'block', color: '#9ca3af', fontSize: 10, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{task.match_excerpt}</span>}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                ))}
              </div>

              <div style={{ padding: 12, borderTop: `1px solid ${WB.border}`, background: '#fff' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
                  <Avatar size={30} style={{ background: 'linear-gradient(135deg, #34d399 0%, #14b8a6 100%)' }}>{userInitial}</Avatar>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={{ color: '#374151', fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{userName}</div>
                    <div style={{ color: '#9ca3af', fontSize: 10, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{user?.organization_name || user?.organization_slug || '企业用户'}</div>
                  </div>
                  <Tooltip title="退出登录"><Button type="text" danger aria-label="退出登录" icon={<LogoutOutlined />} onClick={logout} /></Tooltip>
                </div>
              </div>
            </div>
          </Drawer>
        </div>

        {/* 右侧抽屉：资源·文件·记忆·轨迹（默认收起，按需展开） */}
        <Drawer
          placement="right" open={drawerOpen} width={isMobile ? '100%' : 460}
          onClose={() => setDrawerOpen(false)}
          rootClassName="responsive-fullscreen-drawer"
          styles={{ body: { padding: '12px 16px', background: '#fafafa' } }}
          title={<span><UnorderedListOutlined /> 资源 · 文件 · 记忆 · 轨迹</span>}
        >
          <Tabs
            activeKey={activeTab} onChange={setActiveTab} size="small"
            items={[
              {
                key: 'resources',
                label: <span><SettingOutlined /> 资源</span>,
                children: <ResourcePanel
                  taskConfig={taskConfig}
                  resources={resources}
                  agent={agentsList.find((item) => item.id === selectedAgentId)}
                />,
              },
              {
                key: 'files',
                label: <span><FileTextOutlined /> 文件</span>,
                children: <FilePanel
                  workspaceId={taskConfig.workspace_id}
                  workspaceName={resources?.workspaces.find((item) => item.id === taskConfig.workspace_id)?.name}
                />,
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
        modelCapabilities={modelData?.capabilities}
        visionFallbackAvailable={modelData?.vision_fallback_available}
        imageGenerationAvailable={modelData?.image_generation_available}
        agents={agentsList}
        agentId={selectedAgentId}
        onAgentChange={setSelectedAgentId}
      />

      <BrowserDrawer
        open={browserOpen}
        initialHref={browserHref}
        initialFileId={browserFileId}
        initialVersionId={browserVersionId}
        onClose={() => setBrowserOpen(false)}
        resolveHref={resolveHref}
        loadFileById={loadReferencedFile}
        loadFileVersionById={terminal.getWsFileVersion}
        fallbackCapabilities={resources?.workspaces.find((item) => item.id === taskConfig.workspace_id)?.capabilities}
        fallbackWorkspaceName={resources?.workspaces.find((item) => item.id === taskConfig.workspace_id)?.name}
        saveTextFile={terminal.updateWsFile}
        listFileVersions={terminal.listWsFileVersions}
        restoreFileVersion={terminal.restoreWsFileVersion}
        onFileChanged={() => {
          qc.invalidateQueries({ queryKey: ['terminal-ws-files'] });
          qc.invalidateQueries({ queryKey: ['terminal-all-ws-files'] });
          qc.invalidateQueries({ queryKey: ['ws-mgr-files'] });
        }}
        loadOriginalPreview={terminal.getWsFileOriginalPreview}
        loadOriginalPreviewSource={terminal.getWsFileOriginalPreviewSource}
        loadPdfPreviewInfo={terminal.getWsFilePdfPreviewInfo}
        loadPdfPreviewPage={terminal.getWsFilePdfPreviewPage}
        loadPreviewSession={terminal.createWsFilePreviewSession}
        refreshPreviewSession={terminal.refreshWsFilePreviewSession}
        startFallbackPreview={terminal.startWsFileFallbackPreview}
        getFallbackPreview={terminal.getWsFileFallbackPreview}
        startSpreadsheetPreview={terminal.startWsFileSpreadsheetPreview}
        getSpreadsheetPreview={terminal.getWsFileSpreadsheetPreview}
        getSpreadsheetPage={terminal.getWsFileSpreadsheetPage}
        loadDownloadTicket={terminal.getWsFileDownloadTicket}
        loadOriginalFile={terminal.downloadWsFile}
        externalVersionEvent={browserFileId ? fileEventsById[browserFileId] ?? null : null}
      />

      {/* 删除任务确认：界面正中模态框 */}
      <ConfirmModal
        open={!!delConfirm}
        title="删除该任务？"
        desc="只删除对话记录；已交付到工作空间的文件保持不变"
        onCancel={() => setDelConfirm(null)}
        onOk={() => { if (delConfirm) { deleteTask(delConfirm.id); setDelConfirm(null); } }}
      />

      {/* 删除单轮对话确认：只删该轮 user+assistant，不删除工作空间文件 */}
      <ConfirmModal
        open={!!turnDelConfirm}
        title="删除该轮对话？"
        desc="只删除本轮对话；已交付到工作空间的文件保持不变"
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
  insertSkillChip: (id: string, slug: string, name: string) => void;
  /** 插入一个工作空间文件引用 chip：有 pending @ 则替换之，否则插在光标处 */
  insertFileChip: (fileId: string, label: string) => void;
  /** / 或 @ 触发后未选中即关闭：剥离那个孤立的触发符 */
  clearPendingMention: () => void;
  focus: () => void;
}

type PendingMention = { node: Text; offset: number; ch: '/' | '@' };

const MentionInput = forwardRef<ComposerInputHandle, {
  value: string; onChange: (v: string) => void; placeholder: string;
  onSkillIdsChange: (ids: string[]) => void;
  onFileIdsChange: (ids: string[]) => void;
  onPasteFiles: (event: ReactClipboardEvent<HTMLDivElement>) => void;
  onSlashTrigger: () => void; onAtTrigger: () => void; onSubmit: () => void; canSend: boolean;
}>(function MentionInput(props, ref) {
  const { value, placeholder } = props;
  const editorRef = useRef<HTMLDivElement>(null);
  const pendingRef = useRef<PendingMention | null>(null);
  const composingRef = useRef(false);
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
    latest.current.onSkillIdsChange(Array.from(
      el.querySelectorAll<HTMLElement>('[data-skill-id]'),
      (chip) => chip.getAttribute('data-skill-id') || '',
    ).filter((id, index, all) => !!id && all.indexOf(id) === index));
    latest.current.onFileIdsChange(Array.from(
      el.querySelectorAll<HTMLElement>('[data-file-id]'),
      (chip) => chip.getAttribute('data-file-id') || '',
    ).filter((id, index, all) => !!id && all.indexOf(id) === index));
  };

  // 外部 value 变化（如发送后清空）→ 重建 DOM
  useEffect(() => {
    const el = editorRef.current;
    if (!el || composingRef.current) return;
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
    insertSkillChip: (id, slug, name) => {
      const chip = document.createElement('span');
      chip.setAttribute('contenteditable', 'false');
      chip.setAttribute('data-skill-id', id);
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
    const ev = e.nativeEvent as InputEvent & { isComposing?: boolean };
    if (composingRef.current || ev.isComposing) return;
    if (ev.inputType === 'insertText') {
      if (ev.data === '/') detectTrigger('/');
      else if (ev.data === '@') detectTrigger('@');
    }
    syncToState();
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (composingRef.current || (e.nativeEvent as { isComposing?: boolean }).isComposing) return;
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
      onPaste={props.onPasteFiles}
      onCompositionStart={() => { composingRef.current = true; }}
      onCompositionEnd={() => {
        composingRef.current = false;
        syncToState();
      }}
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
  invokedSkills: InvokedSkill[];
  setInvokedSkills: Dispatch<SetStateAction<InvokedSkill[]>>;
  fileRefs: WorkspaceFileRefV1[];
  setFileRefs: Dispatch<SetStateAction<WorkspaceFileRefV1[]>>;
  attachments: ComposerAttachment[];
  setAttachments: Dispatch<SetStateAction<ComposerAttachment[]>>;
  attachmentScopeKey: string;
  onSend: () => void; onStop?: () => void; streaming: boolean;
  placeholder: string;
  config: TaskConfig; resources: TerminalResources | undefined;
  onSetExecMode: (m: TaskConfig['exec_mode']) => void;
  onSetWorkspace: (workspaceId: string) => boolean | Promise<boolean>;
  onOpenConfig: () => void;
  onImportSkill: () => void;
  /** 当前选中智能体显示名（null=通用），点 chip 打开同一抽屉在模型下方切换。 */
  agentLabel: string;
  maxWidth?: number; sendLabel?: string;
}) {
  const {
    value, setValue, invokedSkills, setInvokedSkills, fileRefs, setFileRefs, attachments, setAttachments, attachmentScopeKey,
    onSend, onStop, streaming, placeholder, config, resources,
    onSetExecMode, onSetWorkspace, onOpenConfig, onImportSkill, agentLabel, maxWidth = 800, sendLabel = '开始执行',
  } = props;
  const configuredWorkspaceId = config.workspace_id ?? resources?.defaults?.workspace_id ?? null;
  const [workspaceOverride, setWorkspaceOverride] = useState<string | null>(null);
  const effectiveWorkspaceId = workspaceOverride ?? configuredWorkspaceId;
  const wsName = (effectiveWorkspaceId && resources?.workspaces.find((w) => w.id === effectiveWorkspaceId)?.name) || null;
  const hasReadyAttachment = attachments.some((item) => item.status === 'ready');
  const attachmentsReady = attachments.every((item) => item.status === 'ready');
  const canSend = (!!value.trim() || hasReadyAttachment || invokedSkills.length > 0 || fileRefs.length > 0) && attachmentsReady && !streaming;

  // ── 引用下拉（向上）：技能（/ 或 chip）/ 工作空间文件（@）共用一个 Popover ──
  const inputRef = useRef<ComposerInputHandle>(null);
  const attachmentsRef = useRef(attachments);
  const uploadControllersRef = useRef(new Map<string, AbortController>());
  const activeUploadsRef = useRef(0);
  const uploadWaitersRef = useRef<Array<() => void>>([]);
  const attachmentInputRef = useRef<HTMLInputElement>(null);
  const previousWorkspaceRef = useRef<string | null>(effectiveWorkspaceId);
  const searchRef = useRef<{ focus: (opts?: unknown) => void } | null>(null);
  const qc = useQueryClient();
  const [dragActive, setDragActive] = useState(false);
  const [recordingState, setRecordingState] = useState<'idle' | 'recording' | 'paused' | 'processing'>('idle');
  const recorderRef = useRef<MediaRecorder | null>(null);
  const recordingStreamRef = useRef<MediaStream | null>(null);
  const recordingChunksRef = useRef<Blob[]>([]);

  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerMode, setPickerMode] = useState<'skill' | 'file'>('skill');
  const [query, setQuery] = useState('');

  useEffect(() => {
    if (workspaceOverride && configuredWorkspaceId === workspaceOverride) setWorkspaceOverride(null);
  }, [configuredWorkspaceId, workspaceOverride]);

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
    ? files.filter((f) => workspaceFileLabel(f).toLowerCase().includes(qstr)
      || workspaceDisplayName(f).toLowerCase().includes(qstr)
      || f.workspace_name.toLowerCase().includes(qstr))
    : files;
  const detachedFileRefs = fileRefs.filter((ref) => !value.includes(`@${ref.file_id}`));

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
    inputRef.current?.insertSkillChip(s.id, s.slug, s.name);
  };
  const onPickFile = (f: WorkspaceFileSummary) => {
    setQuery(''); setPickerOpen(false);
    setFileRefs((current) => Array.from(new Map([
      ...current,
      { file_id: f.id, scope: 'task' as const, follow_latest: true },
    ].map((item) => [item.file_id, item])).values()));
    inputRef.current?.insertFileChip(f.id, workspaceFileLabel(f));
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

  const waitForAttachmentParse = useCallback(async (fileId: string, signal: AbortSignal) => {
    for (let attempt = 0; attempt < 150; attempt += 1) {
      if (signal.aborted) throw new DOMException('上传已取消', 'AbortError');
      const current = await terminal.getWsFile(fileId);
      if (!['queued', 'processing', 'unparsed'].includes(current.parse_status)) return current;
      await new Promise((resolve) => window.setTimeout(resolve, 2000));
    }
    throw new Error('文件解析等待超过 5 分钟，可稍后在工作空间重试');
  }, []);

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
        onUploadComplete: () => updateAttachment(draft.client_id, { status: 'validating', progress: 100 }),
      });
      if (!['ready', 'unsupported', 'failed'].includes(uploaded.parse_status)) {
        updateAttachment(draft.client_id, { status: 'parsing', progress: 100 });
      }
      const rawTool = rawAttachmentTool(draft.name);
      const parsed = uploaded.parse_status === 'ready' || rawTool
        ? uploaded
        : await waitForAttachmentParse(uploaded.id, controller.signal);
      const nextStatus: ComposerAttachmentStatus = parsed.parse_status === 'ready' || rawTool ? 'ready' : 'failed';
      updateAttachment(draft.client_id, {
        file_id: uploaded.id,
        workspace_id: uploaded.workspace_id,
        path: uploaded.path,
        status: nextStatus,
        raw_tool: parsed.parse_status === 'ready' ? undefined : rawTool,
        progress: 100,
        error: nextStatus === 'failed'
          ? (parsed.parse_error || (parsed.parse_status === 'unsupported' ? '暂不支持该文件格式' : '文件解析失败'))
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
  }, [refreshWorkspaceFiles, updateAttachment, waitForAttachmentParse]);

  const ensureWritableWorkspace = useCallback(async () => {
    const selected = effectiveWorkspaceId
      ? resources?.workspaces.find((workspace) => workspace.id === effectiveWorkspaceId)
      : undefined;
    // 兼容尚未返回 capabilities 的旧后端；只有明确只读时才自动回退。
    if (effectiveWorkspaceId && selected?.capabilities?.create !== false) return effectiveWorkspaceId;

    const personal = resources?.workspaces.find((workspace) => (
      workspace.id === resources.defaults?.workspace_id && workspace.capabilities?.create !== false
    ));
    if (!personal) {
      message.warning('当前工作空间不可写，且没有可用的个人工作空间');
      onOpenConfig();
      return null;
    }
    // 已存在任务的配置 PATCH 与资源查询刷新之间有一个短窗口；本地覆盖确保这段
    // 时间内附件队列不会又按旧的只读工作空间处理。
    setWorkspaceOverride(personal.id);
    const switched = await onSetWorkspace(personal.id);
    if (!switched) {
      setWorkspaceOverride(null);
      return null;
    }
    // 避免工作空间切换 effect 把刚加入队列的附件误认为旧工作空间附件而清空。
    previousWorkspaceRef.current = personal.id;
    message.info(`“${selected?.name ?? '当前工作空间'}”为只读，已切换到个人工作空间“${personal.name}”上传`);
    return personal.id;
  }, [effectiveWorkspaceId, onOpenConfig, onSetWorkspace, resources]);

  const queueFiles = useCallback(async (fileList: FileList | File[]) => {
    const workspaceId = await ensureWritableWorkspace();
    if (!workspaceId) {
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
      error: file.size > MAX_ATTACHMENT_BYTES ? '文件超过 5GB 存储上限' : undefined,
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
  }, [attachmentScopeKey, ensureWritableWorkspace, setAttachments, uploadOne]);

  const pasteFiles = useCallback((event: ReactClipboardEvent<HTMLDivElement>) => {
    const clipboardFiles = Array.from(event.clipboardData.items)
      .filter((item) => item.kind === 'file')
      .map((item) => item.getAsFile())
      .filter((file): file is File => Boolean(file));
    if (!clipboardFiles.length) {
      const internalRef = parseWorkspaceInternalUrl(event.clipboardData.getData('text/plain'));
      if (!internalRef) return;
      const { fileId, versionId } = internalRef;
      event.preventDefault();
      const known = files.find((item) => item.id === fileId);
      const add = (label: string) => {
        setFileRefs((current) => Array.from(new Map([
          ...current,
          { file_id: fileId, scope: 'task' as const, ...(versionId ? { version_id: versionId, follow_latest: false } : { follow_latest: true }) },
        ].map((item) => [item.file_id, item])).values()));
        inputRef.current?.insertFileChip(fileId, label);
      };
      if (known) add(workspaceFileLabel(known));
      else void terminal.getWsFile(fileId)
        .then((file) => add(workspaceFileLabel(file)))
        .catch(() => message.error('文件不存在或没有查看权限'));
      return;
    }
    event.preventDefault();
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
    const normalized = clipboardFiles.map((file, index) => {
      if (file.name && file.name !== 'image.png') return file;
      const extension = file.type.split('/')[1]?.replace('jpeg', 'jpg') || 'png';
      return new File([file], `粘贴附件-${timestamp}-${index + 1}.${extension}`, {
        type: file.type, lastModified: file.lastModified,
      });
    });
    void queueFiles(normalized);
  }, [files, queueFiles, setFileRefs]);

  const openAttachmentPicker = useCallback(async () => {
    const browserWindow = window as BrowserWindowWithFilePicker;
    if (typeof browserWindow.showOpenFilePicker === 'function') {
      try {
        const handles = await browserWindow.showOpenFilePicker({ multiple: true });
        const files = await Promise.all(handles.map((handle) => handle.getFile()));
        if (files.length) await queueFiles(files);
        return;
      } catch (error) {
        if ((error as Error).name === 'AbortError') return;
        // Fall through for browsers or embedded contexts that reject this API.
      }
    }
    const input = attachmentInputRef.current;
    if (!input) return;
    input.click();
  }, [queueFiles]);

  const processRecording = useCallback(async (blob: Blob) => {
    if (!effectiveWorkspaceId) throw new Error('请先选择工作空间');
    setRecordingState('processing');
    const extension = blob.type.includes('mp4') ? 'm4a' : 'webm';
    const filename = `录音-${new Date().toISOString().replace(/[:.]/g, '-')}.${extension}`;
    const file = new File([blob], filename, { type: blob.type || 'audio/webm' });
    const uploaded = await terminal.uploadWsFile(
      effectiveWorkspaceId,
      file,
      attachmentPath(attachmentScopeKey, filename),
    );
    refreshWorkspaceFiles(effectiveWorkspaceId);
    const created = await multimodal.transcribe(uploaded.id);
    for (let attempt = 0; attempt < 150; attempt += 1) {
      const job = await multimodal.job(created.job_id);
      if (job.status === 'succeeded') {
        const text = String(job.result.text || '').trim();
        if (!text) throw new Error('录音已识别，但没有可用文字');
        setValue(value.trim() ? `${value.trim()}\n${text}` : text);
        message.success('录音已转写，请确认或编辑后发送');
        setRecordingState('idle');
        return;
      }
      if (job.status === 'failed' || job.status === 'cancelled') {
        throw new Error(job.error_detail || job.error_category || '录音转写失败');
      }
      await new Promise((resolve) => window.setTimeout(resolve, 2000));
    }
    throw new Error('录音转写等待超过 5 分钟，可稍后重试');
  }, [attachmentScopeKey, effectiveWorkspaceId, refreshWorkspaceFiles, setValue, value]);

  const startRecording = useCallback(async () => {
    if (!effectiveWorkspaceId) {
      message.warning('请先选择工作空间，再开始录音');
      onOpenConfig();
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      message.error('当前浏览器不支持录音');
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const preferred = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4']
        .find((type) => MediaRecorder.isTypeSupported(type));
      const recorder = new MediaRecorder(stream, preferred ? { mimeType: preferred } : undefined);
      recordingStreamRef.current = stream;
      recorderRef.current = recorder;
      recordingChunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size) recordingChunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        const blob = new Blob(recordingChunksRef.current, { type: recorder.mimeType || 'audio/webm' });
        recordingChunksRef.current = [];
        recordingStreamRef.current?.getTracks().forEach((track) => track.stop());
        recordingStreamRef.current = null;
        recorderRef.current = null;
        void processRecording(blob).catch((error) => {
          setRecordingState('idle');
          message.error((error as Error).message || '录音处理失败');
        });
      };
      recorder.start(1000);
      setRecordingState('recording');
    } catch (error) {
      message.error((error as Error).name === 'NotAllowedError' ? '麦克风权限被拒绝' : '无法启动录音');
    }
  }, [effectiveWorkspaceId, onOpenConfig, processRecording]);

  const cancelRecording = useCallback(() => {
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== 'inactive') {
      recorder.onstop = null;
      recorder.stop();
    }
    recordingStreamRef.current?.getTracks().forEach((track) => track.stop());
    recordingStreamRef.current = null;
    recorderRef.current = null;
    recordingChunksRef.current = [];
    setRecordingState('idle');
  }, []);

  const retryAttachment = useCallback(async (item: ComposerAttachment) => {
    if (item.file.size > MAX_ATTACHMENT_BYTES) {
      message.warning('该文件超过 5GB 存储上限，请压缩或拆分后重新选择');
      return;
    }
    if (item.file_id) {
      const rawTool = rawAttachmentTool(item.name);
      if (rawTool) {
        updateAttachment(item.client_id, {
          status: 'ready', raw_tool: rawTool, error: undefined, progress: 100,
        });
        return;
      }
      updateAttachment(item.client_id, { status: 'parsing', error: undefined, progress: 100 });
      try {
        const queued = await terminal.reparseWsFile(item.file_id);
        const reparsed = await waitForAttachmentParse(queued.id, new AbortController().signal);
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
    const workspaceId = await ensureWritableWorkspace();
    if (!workspaceId) return;
    const retryDraft = { ...item, workspace_id: workspaceId };
    updateAttachment(item.client_id, { workspace_id: workspaceId });
    await uploadOne(retryDraft, workspaceId);
  }, [ensureWritableWorkspace, refreshWorkspaceFiles, updateAttachment, uploadOne, waitForAttachmentParse]);

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
    cancelRecording();
  }, [cancelRecording]);

  const statusLabel: Record<ComposerAttachmentStatus, string> = {
    uploading: '上传中', validating: '校验中', parsing: '解析中', ready: '可以发送', failed: '处理失败',
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
                {workspaceDisplayName(f)}{f.is_binary && <Tag color="default" style={{ marginLeft: 6, fontSize: 10 }}>二进制</Tag>}
              </div>
              <div title={workspaceFileLabel(f)} style={{ fontSize: 11, color: '#9ca3af', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{workspaceFileLabel(f)}</div>
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
                      {item.status === 'ready' && item.raw_tool
                        ? `可以发送（${item.raw_tool === 'image_tool' ? '图片工具' : item.raw_tool === 'audio_tool' ? '音频模型' : '压缩包工具'}读取）`
                        : statusLabel[item.status]}
                      {item.status === 'uploading' ? ` ${item.progress}%` : ''}
                    </div>
                  </div>
                  {(item.status === 'uploading' || item.status === 'validating' || item.status === 'parsing') && <Spin size="small" />}
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
        {!!detachedFileRefs.length && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, padding: attachments.length ? '6px 12px 0' : '10px 12px 0' }}>
            {detachedFileRefs.map((ref) => {
              const file = files.find((item) => item.id === ref.file_id);
              const label = file ? workspaceFileLabel(file) : `文件 ${ref.file_id.slice(0, 8)}…`;
              return (
                <Tooltip key={ref.file_id} title={`${label}（任务持续引用，无需每轮重新 @）`}>
                  <Tag icon={<FileTextOutlined />} color="blue" style={{ margin: 0, maxWidth: '100%' }}>
                    <span style={{ display: 'inline-block', maxWidth: 360, overflow: 'hidden', textOverflow: 'ellipsis', verticalAlign: 'bottom' }}>{label}</span>
                  </Tag>
                </Tooltip>
              );
            })}
          </div>
        )}
        <MentionInput
          ref={inputRef}
          value={value} onChange={setValue}
          onSkillIdsChange={(ids) => setInvokedSkills(ids.flatMap((id) => {
            const skill = skills.find((item) => item.id === id);
            return skill ? [{ id: skill.id, name: skill.name, slug: skill.slug, scope_type: skill.scope_type }] : [];
          }))}
          onFileIdsChange={(ids) => setFileRefs((current) => {
            const kept = current.filter((item) => !value.includes(`@${item.file_id}`) || ids.includes(item.file_id));
            const added = ids.map((fileId) => current.find((item) => item.file_id === fileId)
              ?? { file_id: fileId, scope: 'task' as const, follow_latest: true });
            return Array.from(new Map([...kept, ...added].map((item) => [item.file_id, item])).values());
          })}
          placeholder={placeholder}
          onPasteFiles={pasteFiles}
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
              title="明确指定本轮使用的Skill；不修改智能体配置（输入 / 也可唤出）">
              <AppstoreOutlined /> 本轮调用技能
            </span>
            <span data-picker-trigger="file" style={chipBtnStyle}
              onClick={() => { if (pickerOpen && pickerMode === 'file') closePicker(false); else openPicker('file'); }}
              title="引用工作空间文件（输入 @ 也可唤出，再次点击关闭）">
              <FileTextOutlined /> 文件
            </span>
            <button
              type="button"
              style={chipBtnStyle}
              title="从电脑选择新文件（可多选），也可以在输入框直接粘贴图片或文件"
              onClick={() => { void openAttachmentPicker(); }}
            >
              <UploadOutlined /> 上传附件
            </button>
            {recordingState === 'idle' ? (
              <button type="button" style={chipBtnStyle} title="录音并转写" onClick={() => void startRecording()}>
                <AudioOutlined /> 录音
              </button>
            ) : recordingState === 'processing' ? (
              <span style={chipBtnStyle}><Spin size="small" /> 正在转写</span>
            ) : (
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                <button
                  type="button"
                  style={chipBtnStyle}
                  onClick={() => {
                    const recorder = recorderRef.current;
                    if (!recorder) return;
                    if (recorder.state === 'recording') { recorder.pause(); setRecordingState('paused'); }
                    else if (recorder.state === 'paused') { recorder.resume(); setRecordingState('recording'); }
                  }}
                >
                  {recordingState === 'recording' ? <PauseOutlined /> : <CaretRightOutlined />}
                  {recordingState === 'recording' ? '暂停' : '继续'}
                </button>
                <button type="button" style={chipBtnStyle} onClick={() => recorderRef.current?.stop()}>
                  <StopOutlined /> 完成转写
                </button>
                <button type="button" style={chipBtnStyle} onClick={cancelRecording}>取消</button>
              </span>
            )}
            <Typography.Text
              type="secondary"
              title="支持 Word、Excel、PPT、PDF、Markdown 等常用文件"
              style={{ fontSize: 11, whiteSpace: 'nowrap' }}
            >
              单次最多 {MAX_ATTACHMENTS} 个 · 单文件最大 {MAX_ATTACHMENT_LABEL}
            </Typography.Text>
            <input
              ref={attachmentInputRef}
              type="file"
              multiple
              aria-label="选择上传附件"
              tabIndex={-1}
              style={{
                position: 'fixed', left: -10000, top: 0,
                width: 1, height: 1, opacity: 0,
              }}
              onChange={(event: ChangeEvent<HTMLInputElement>) => {
                if (event.target.files?.length) void queueFiles(event.target.files);
                event.target.value = '';
              }}
            />
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
  invokedSkills: InvokedSkill[];
  setInvokedSkills: Dispatch<SetStateAction<InvokedSkill[]>>;
  fileRefs: WorkspaceFileRefV1[];
  setFileRefs: Dispatch<SetStateAction<WorkspaceFileRefV1[]>>;
  attachments: ComposerAttachment[];
  setAttachments: Dispatch<SetStateAction<ComposerAttachment[]>>;
  attachmentScopeKey: string;
  config: TaskConfig;
  resources: TerminalResources | undefined;
  onSetExecMode: (m: TaskConfig['exec_mode']) => void;
  onSetWorkspace: (workspaceId: string) => boolean | Promise<boolean>;
  onOpenConfig: () => void; onImportSkill: () => void; onStart: () => void; streaming: boolean;
  agentLabel: string;
}) {
  const {
    input, setInput, invokedSkills, setInvokedSkills, fileRefs, setFileRefs, attachments, setAttachments, attachmentScopeKey, placeholder,
    config, resources, onSetExecMode, onSetWorkspace, onOpenConfig, onImportSkill, onStart, streaming, agentLabel,
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
        {/* BRAND_LOGO_SLOT: 用户端欢迎页品牌位 */}
        <div style={{ position: 'relative', marginBottom: 24 }}>
          <BrandLogoSlot slot={BRAND_LOGO_SLOTS.terminalWelcome} width={72} height={72} />
        </div>

        <h1 style={{ fontSize: 30, fontWeight: 700, color: '#111827', marginBottom: 4 }}>灼见</h1>
        <p style={{ fontSize: 22, fontWeight: 600, color: '#1f2937', marginBottom: 32 }}>你的职场超能力</p>

        {/* 输入框 */}
        <TaskInputBox
          value={input} setValue={setInput}
          invokedSkills={invokedSkills} setInvokedSkills={setInvokedSkills}
          fileRefs={fileRefs} setFileRefs={setFileRefs}
          attachments={attachments} setAttachments={setAttachments}
          attachmentScopeKey={attachmentScopeKey}
          onSend={onStart} streaming={streaming}
          placeholder={placeholder}
          config={config} resources={resources}
          onSetExecMode={onSetExecMode}
          onSetWorkspace={onSetWorkspace}
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
  fileMap: Map<string, WorkspaceFileSummary>,
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
  // 兼容旧消息里紧跟中英文标点的 @UUID（过去会因只认空白边界而退化成裸 UUID）。
  const re = /(^|[\s([{"'“‘，。！？；：、])([/@])([A-Za-z0-9][A-Za-z0-9_-]*)/g;
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
    const skill = ch === '/' ? skillMap.get(token) : undefined;
    const file = ch === '@' ? fileMap.get(token) : undefined;
    if (skill || file) {
      out.push(skill
        ? <span key={`s${key++}`} className="skill-ref-chip" title={`技能：${skill} (/${token})`}>{skill}</span>
        : <span key={`f${key++}`} className="file-ref-chip" title={`工作空间文件：${workspaceFileLabel(file!)}`}>{workspaceFileLabel(file!)}</span>);
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
  invokedSkills: InvokedSkill[];
  setInvokedSkills: Dispatch<SetStateAction<InvokedSkill[]>>;
  fileRefs: WorkspaceFileRefV1[];
  setFileRefs: Dispatch<SetStateAction<WorkspaceFileRefV1[]>>;
  attachments: ComposerAttachment[];
  setAttachments: Dispatch<SetStateAction<ComposerAttachment[]>>;
  onSend: () => void; onStop: () => void;
  onTogglePanel: () => void; onNew: () => void;
  config: TaskConfig; resources: TerminalResources | undefined;
  onSetExecMode: (m: TaskConfig['exec_mode']) => void;
  onSetWorkspace: (workspaceId: string) => boolean | Promise<boolean>;
  onOpenConfig: () => void;
  onImportSkill: () => void;
  selectedId: string | null;
  onLink: (href: string) => void;
  onOpenFile: (fileId: string, versionId?: string) => void;
  fileLinks: ChatFileLink[];
  fileRefMap: Map<string, WorkspaceFileSummary>;
  fileRefsLoaded: boolean;
  onDeleteTurn: (messageId: string) => void;
  agentLabel: string;
}) {
  const {
    taskTitle, chat, streaming, followUp, setFollowUp, invokedSkills, setInvokedSkills, fileRefs, setFileRefs,
    attachments, setAttachments,
    onSend, onStop, onNew, config, resources, onSetExecMode, onSetWorkspace, onOpenConfig,
    onImportSkill, selectedId, onLink, onOpenFile, fileLinks, fileRefMap, fileRefsLoaded, onDeleteTurn, agentLabel,
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
            const messageSkillMap = new Map(skillRefMap);
            (m.invokedSkills ?? []).forEach((skill) => messageSkillMap.set(skill.slug, skill.name));
            const attachmentIds = new Set((m.attachments ?? []).map((item) => item.file_id));
            const messageFileCards = [
              ...(m.attachments ?? []).map((item) => ({ fileId: item.file_id, fallbackLabel: item.name, scope: 'turn' as const, versionId: undefined as string | undefined })),
              ...(m.fileRefs ?? [])
                .filter((item) => !attachmentIds.has(item.file_id))
                .map((item) => ({
                  fileId: item.file_id,
                  fallbackLabel: messageFileRefLabel(item),
                  scope: item.scope,
                  versionId: item.version_id,
                })),
            ];
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
                      <Tooltip title="删除该轮对话（保留工作空间文件）">
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
                        <MessageTimestamp value={m.createdAt} />
                      </div>
                      {!!messageFileCards.length && (
                        <div style={{ display: 'grid', gap: 6, marginBottom: m.content ? 8 : 0 }}>
                          {messageFileCards.map((item) => {
                            const availableFile = fileRefMap.get(item.fileId);
                            const unavailable = fileRefsLoaded && !availableFile;
                            const label = availableFile ? workspaceFileLabel(availableFile) : item.fallbackLabel;
                            return (
                              <button
                                key={`${item.scope}:${item.fileId}`}
                                type="button"
                                disabled={unavailable}
                                onClick={() => onOpenFile(item.fileId, item.versionId)}
                                title={unavailable ? '文件已不存在或不可访问' : `打开 ${label}`}
                                style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%', border: `1px solid ${unavailable ? '#e5e7eb' : '#d8dcf4'}`, background: unavailable ? '#f3f4f6' : '#fff', borderRadius: 8, padding: '7px 9px', cursor: unavailable ? 'not-allowed' : 'pointer', color: unavailable ? '#9ca3af' : '#374151', textAlign: 'left' }}
                              >
                                <FileTextOutlined style={{ color: unavailable ? '#9ca3af' : WB.primary }} />
                                <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 12 }}>{label}</span>
                                <span style={{ fontSize: 10, flexShrink: 0 }}>{unavailable ? '不可访问' : item.versionId ? '历史版本' : item.scope === 'task' ? '任务引用' : '本轮引用'}</span>
                              </button>
                            );
                          })}
                        </div>
                      )}
                      <div style={{ fontSize: 14, color: '#1f2937', lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>
                        {renderUserContent(
                          removeAttachmentReferenceTokens(m.content, (m.attachments ?? []).map((item) => item.file_id)),
                          messageSkillMap,
                          fileRefMap,
                          m.agentName,
                        )}
                      </div>
                    </div>
                  </>
                ) : (
                  <AssistantBubble msg={m} streaming={streaming && isLast} onLink={onLink} fileLinks={fileLinks} taskId={selectedId} />
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
            invokedSkills={invokedSkills} setInvokedSkills={setInvokedSkills}
            fileRefs={fileRefs} setFileRefs={setFileRefs}
            attachments={attachments} setAttachments={setAttachments}
            attachmentScopeKey={selectedId || '任务未选择'}
            onSend={onSend} onStop={onStop} streaming={streaming}
            placeholder="追加消息（Enter 发送，Shift+Enter 换行）"
            config={config} resources={resources}
            onSetExecMode={onSetExecMode}
            onSetWorkspace={onSetWorkspace}
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

// ── 共享样式 ─────────────────────────────────────────────────────────────

/** 左侧功能菜单项样式：active 态用主色高亮，否则中性灰。 */
function navItemStyle(active: boolean): CSSProperties {
  return {
    display: 'flex', alignItems: 'center', gap: 12, padding: '8px 12px', borderRadius: 8,
    width: '100%', border: 0, textAlign: 'left', fontFamily: 'inherit', cursor: 'pointer', fontSize: 13,
    color: active ? WB.primary : '#4b5563',
    background: active ? `${WB.primary}1A` : 'transparent',
  };
}

const chipBtnStyle: CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, color: '#4b5563',
  background: 'transparent', border: 'none', cursor: 'pointer', padding: 0,
};
