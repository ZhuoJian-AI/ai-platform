import { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Badge, Button, Card, Drawer, Dropdown, Empty, Input, Popconfirm, Result, Select, Space, Spin, Tag, Tooltip, Typography, message } from 'antd';
import {
  AppstoreOutlined, CheckCircleFilled, CloseCircleFilled, DeleteOutlined, DownloadOutlined, ExportOutlined, EyeOutlined, FileTextOutlined,
  FullscreenExitOutlined, FullscreenOutlined, LoadingOutlined, ReloadOutlined,
  HistoryOutlined, MoreOutlined, PlusOutlined, RobotOutlined, SendOutlined, UploadOutlined,
} from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ApiError, terminal, type EnterpriseApplicationLaunch, type TerminalEnterpriseApplication,
  type TerminalTask, type TerminalTaskMessage, type TerminalTaskWithMessages, type WorkspaceFileRefV1, type WorkspaceFileSummary,
  type TerminalApprovalDecidedBy, type TerminalApprovalOutcome,
} from '../../api/client';
import ApprovalCard, { type ApprovalCardData } from '../../components/terminal/ApprovalCard';
import { useMobileBackDismiss, useResponsiveLayout } from '../../hooks/useResponsiveLayout';
import {
  buildHostReadyMessage, buildRefreshMessage, isBridgeReady, parseBridgeAiRun, parseBridgeContext,
  parseBridgeRefreshResult, type BridgeExpectation, type BridgeRefreshExpectation,
} from '../../utils/subsystemBridge';

function validatedLaunchOrigin(
  launch: EnterpriseApplicationLaunch,
  application: TerminalEnterpriseApplication,
): { origin: string; expectation: BridgeExpectation } | null {
  if (launch.application_id !== application.id) throw new Error('应用启动身份不匹配');
  if (launch.application_slug && launch.application_slug !== application.slug) throw new Error('应用启动标识不匹配');
  const launchUrl = new URL(launch.url);
  const localDevelopment = import.meta.env.DEV && ['localhost', '127.0.0.1', '[::1]'].includes(launchUrl.hostname);
  if (launchUrl.protocol !== 'https:' && !localDevelopment) throw new Error('应用入口必须使用 HTTPS');
  if (launch.allowed_origin) {
    const declaredOrigin = new URL(launch.allowed_origin).origin;
    if (declaredOrigin !== launch.allowed_origin || declaredOrigin !== launchUrl.origin) {
      throw new Error('应用入口与已审核 Origin 不一致');
    }
  }
  if (launch.display_mode !== 'embedded') return null;
  if (!launch.launch_nonce || !launch.allowed_origin || launch.application_slug !== application.slug) {
    throw new Error('内嵌应用缺少隔离启动参数，请重新登记或联系管理员');
  }
  return {
    origin: launch.allowed_origin,
    expectation: { applicationSlug: application.slug, launchNonce: launch.launch_nonce },
  };
}

function safeContextPageUrl(launchUrl: string | undefined, route: unknown): string | undefined {
  if (!launchUrl) return undefined;
  try {
    const origin = new URL(launchUrl).origin;
    return typeof route === 'string' && route.startsWith('/') && !route.startsWith('//')
      ? new URL(route, origin).toString()
      : `${origin}/`;
  } catch {
    return undefined;
  }
}

type AssistantProgressItem = {
  key: string;
  label: string;
  tone?: 'normal' | 'warning' | 'error';
};

type AssistantConversationMessage = {
  role: 'user' | 'assistant';
  content: string;
  progress?: AssistantProgressItem[];
  running?: boolean;
  failed?: boolean;
  startedAt?: number;
  elapsedSeconds?: number;
  artifacts?: BusinessArtifact[];
  pageKey?: string;
  pageName?: string;
  navigationSuggestion?: Record<string, unknown> | null;
};

export type BusinessArtifact = {
  fileId: string;
  versionId: string | null;
  workspaceId: string;
  canonicalPath: string;
  name: string;
  mimeType: string;
  sizeBytes: number;
  checksumSha256: string | null;
  source?: Record<string, unknown>;
};

export type BusinessAssistantTurnResult = {
  taskId: string;
  runId: number | null;
  userMessageId: string | null;
  assistantMessageId: string | null;
  status: 'running' | 'completed' | 'failed' | 'cancelled' | 'interrupted';
  content: string;
  artifacts: BusinessArtifact[];
  error: string | null;
  refreshRequired: boolean;
  intent?: Record<string, unknown> | null;
  pageContext?: Record<string, unknown>;
  toolExecutions?: Array<Record<string, unknown>>;
  navigationSuggestion?: Record<string, unknown> | null;
};

function normalizeBusinessArtifact(value: Record<string, unknown>): BusinessArtifact | null {
  const fileId = typeof value.file_id === 'string' ? value.file_id : '';
  const versionId = typeof value.version_id === 'string'
    ? value.version_id
    : typeof value.current_version_id === 'string' ? value.current_version_id : null;
  if (!fileId || !versionId) return null;
  return {
    fileId,
    versionId,
    workspaceId: typeof value.workspace_id === 'string' ? value.workspace_id : '',
    canonicalPath: typeof value.canonical_path === 'string' ? value.canonical_path : '',
    name: typeof value.display_name === 'string'
      ? value.display_name
      : typeof value.name === 'string' ? value.name : '生成文件',
    mimeType: typeof value.mime_type === 'string' ? value.mime_type : 'application/octet-stream',
    sizeBytes: typeof value.size === 'number'
      ? value.size
      : typeof value.sizeBytes === 'number' ? value.sizeBytes : 0,
    checksumSha256: typeof value.checksum_sha256 === 'string' ? value.checksum_sha256 : null,
    source: value.source && typeof value.source === 'object'
      ? value.source as Record<string, unknown>
      : value.provenance && typeof value.provenance === 'object'
        ? value.provenance as Record<string, unknown>
        : undefined,
  };
}

export function businessArtifactsFromMessage(message: TerminalTaskMessage | undefined): BusinessArtifact[] {
  const raw = message?.metadata?.artifacts;
  if (!Array.isArray(raw)) return [];
  const deduped = new Map<string, BusinessArtifact>();
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue;
    const value = item as Record<string, unknown>;
    const artifact = normalizeBusinessArtifact(value);
    if (artifact) deduped.set(`${artifact.fileId}:${artifact.versionId}`, artifact);
  }
  return [...deduped.values()];
}

function businessArtifactFromEvent(event: Record<string, unknown>): BusinessArtifact | null {
  if (event.type !== 'artifact' || !event.artifact || typeof event.artifact !== 'object') return null;
  return normalizeBusinessArtifact(event.artifact as Record<string, unknown>);
}

function businessApprovalsFromTask(
  task: TerminalTaskWithMessages | undefined,
): BusinessAssistantApproval[] {
  if (!task || !Array.isArray(task.messages)) return [];
  const approvals = new Map<string, BusinessAssistantApproval>();
  for (const message of task.messages) {
    const raw = message.metadata?.approvals;
    if (!Array.isArray(raw)) continue;
    for (const item of raw) {
      if (!item || typeof item !== 'object') continue;
      const value = item as Record<string, unknown>;
      const approvalId = typeof value.approvalId === 'string' ? value.approvalId : '';
      if (!approvalId) continue;
      approvals.set(approvalId, {
        approvalId,
        taskId: task.id,
        tool: typeof value.tool === 'string' ? value.tool : '',
        reason: typeof value.reason === 'string' ? value.reason : '',
        argumentsPreview: typeof value.argumentsPreview === 'string' ? value.argumentsPreview : '',
        expiresAt: typeof value.expiresAt === 'string' ? value.expiresAt : new Date(0).toISOString(),
        runId: typeof value.runId === 'number' ? value.runId : undefined,
        outcome: value.outcome as TerminalApprovalOutcome | undefined,
        decidedBy: value.decidedBy as TerminalApprovalDecidedBy | undefined,
      });
    }
  }
  return [...approvals.values()];
}

function formatArtifactBytes(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '大小未知';
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

type BusinessAssistantApproval = ApprovalCardData & { taskId: string };

function progressForAssistantEvent(event: Record<string, unknown>): AssistantProgressItem | null {
  const type = String(event.type ?? '');
  if (type === 'business_state') {
    const labels: Record<string, string> = {
      understanding: '正在理解需求并识别业务目标',
      planned: '已确定目标页面和本轮可用工具',
      awaiting_clarification: '需要你补充一个关键信息',
      awaiting_confirmation: '正在等待你确认业务操作',
      executing: '正在执行已授权的业务步骤',
      verifying: '正在核验工具结果和完成条件',
      committing: '正在保存回复和可信产物',
      completed: '本轮已完成并通过核验',
      failed: '本轮未通过完成条件',
    };
    const status = String(event.status ?? '');
    return labels[status]
      ? { key: `business:${status}`, label: labels[status], tone: status === 'failed' ? 'error' : 'normal' }
      : null;
  }
  if (type === 'run_status') {
    if (event.status === 'queued') {
      const position = Number(event.position) || 0;
      return {
        key: 'runtime',
        label: position > 1 ? `任务已进入队列，前方约 ${position - 1} 个任务` : '任务已进入队列，正在分配运行资源',
      };
    }
    if (event.status === 'running') return { key: 'runtime', label: '模型已连接，正在分析任务' };
  }
  if (type === 'phase') {
    const index = Math.max(0, Number(event.index) || 0);
    return {
      key: `phase:${index}`,
      label: index === 0 ? '正在理解你的需求和当前页面' : `正在推进第 ${index + 1} 步`,
    };
  }
  if (type === 'trace') {
    const category = String(event.category ?? '');
    const labels: Record<string, string> = {
      memory: '正在读取与你相关的业务上下文',
      policy: '正在校验本次操作权限',
      file: '正在处理任务所需的文件',
    };
    return labels[category] ? { key: `trace:${category}`, label: labels[category] } : null;
  }
  if (type === 'tool_call') {
    const name = String(event.name ?? '').toLowerCase();
    let label = '正在调用当前页面已授权的业务能力';
    if (name === 'business_export_to_workspace_file') label = '正在读取权限范围内的业务数据';
    else if (/(spreadsheet|document|presentation|pdf|text)_(create|edit|convert|merge|split|extract)/.test(name)) {
      label = '正在生成文件';
    } else if (/(delete|remove|_de_)/.test(name)) label = '正在准备删除业务记录';
    else if (/(update|edit|_up_)/.test(name)) label = '正在准备更新业务记录';
    else if (/(create|add|_ad_)/.test(name)) label = '正在准备新增业务记录';
    else if (/(query|search|list|_qu_)/.test(name)) label = '正在查询当前页面的业务数据';
    return { key: `tool:${String(event.id ?? name)}`, label };
  }
  if (type === 'tool_result') {
    const name = String(event.name ?? '').toLowerCase();
    if (event.ok !== false && (
      name === 'business_export_to_workspace_file'
      || /(spreadsheet|document|presentation|pdf|text)_(create|edit|convert|merge|split|extract)/.test(name)
    )) {
      return { key: `tool:${String(event.id ?? 'result')}`, label: '文件已生成，正在验证格式并保存' };
    }
    return event.ok === false
      ? { key: `tool:${String(event.id ?? 'result')}`, label: '本次业务调用未成功，正在调整处理方式', tone: 'warning' }
      : { key: `tool:${String(event.id ?? 'result')}`, label: '业务系统已返回数据，正在核对结果' };
  }
  if (type === 'approval_request') {
    return { key: 'approval', label: '操作已暂停，正在等待你的确认', tone: 'warning' };
  }
  if (type === 'artifact') return { key: 'artifact', label: '文件已验证并保存到工作空间' };
  if (type === 'assistant_message') return { key: 'answer', label: '正在整理最终结果和文件卡片' };
  if (type === 'text') return { key: 'answer', label: '数据已经核对，正在组织回答' };
  if (type === 'done') return { key: 'done', label: '回答已经生成' };
  if (type === 'error') return { key: 'error', label: '执行遇到问题，正在整理原因', tone: 'error' };
  return null;
}

function appendProgress(
  items: AssistantProgressItem[] | undefined,
  next: AssistantProgressItem,
): AssistantProgressItem[] {
  return [...(items ?? []).filter((item) => item.key !== next.key), next].slice(-7);
}

export default function EnterpriseApplicationView({
  application,
  moduleKey,
  onModuleChange,
  onAskAI,
  onResumeAI,
  models,
  modelAlias,
  onModelAliasChange,
  immersive,
  onOpenNavigation,
  onToggleImmersive,
  businessTaskId,
  businessTasks,
  onSelectConversation,
  onDeleteConversation,
  onNewConversation,
  targetWorkspaceId,
  workspaceOptions,
  onTargetWorkspaceChange,
  onOpenArtifact,
}: {
  application: TerminalEnterpriseApplication;
  moduleKey: string | null;
  onModuleChange: (moduleKey: string) => void;
  onAskAI: (
    prompt: string,
    pageContext: Record<string, unknown>,
    onProgress: (event: Record<string, unknown>) => void,
    fileRefs: WorkspaceFileRefV1[],
  ) => Promise<BusinessAssistantTurnResult>;
  onResumeAI: (
    taskId: string,
    onProgress: (event: Record<string, unknown>) => void,
  ) => Promise<BusinessAssistantTurnResult>;
  models: string[];
  modelAlias: string | null;
  onModelAliasChange: (modelAlias: string) => void;
  immersive: boolean;
  onOpenNavigation: () => void;
  onToggleImmersive: () => void;
  businessTaskId: string | null;
  businessTasks: TerminalTask[];
  onSelectConversation: (taskId: string) => void;
  onDeleteConversation: (taskId: string) => Promise<void>;
  onNewConversation: () => Promise<void>;
  targetWorkspaceId: string | null;
  workspaceOptions: Array<{ value: string; label: string }>;
  onTargetWorkspaceChange: (workspaceId: string) => void;
  onOpenArtifact: (fileId: string, versionId: string | null) => void;
}) {
  const queryClient = useQueryClient();
  const { isMobile, isCompact } = useResponsiveLayout();
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [prompt, setPrompt] = useState('');
  const [assistantRunning, setAssistantRunning] = useState(false);
  const [assistantMessages, setAssistantMessages] = useState<AssistantConversationMessage[]>([]);
  const [selectedInputFileIds, setSelectedInputFileIds] = useState<string[]>([]);
  const [uploadingInput, setUploadingInput] = useState(false);
  const [creatingConversation, setCreatingConversation] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [runtimeApprovals, setRuntimeApprovals] = useState<BusinessAssistantApproval[]>([]);
  const [frameSlots, setFrameSlots] = useState<[
    EnterpriseApplicationLaunch | undefined,
    EnterpriseApplicationLaunch | undefined,
  ]>([undefined, undefined]);
  const [activeFrameIndex, setActiveFrameIndex] = useState<0 | 1>(0);
  const [frameLoaded, setFrameLoaded] = useState(false);
  const [frameSlow, setFrameSlow] = useState(false);
  const [bridgeContext, setBridgeContext] = useState<Record<string, unknown>>({});
  const bridgeContextRef = useRef<Record<string, unknown>>({});
  const specialistRunsRef = useRef(new Map<string, Promise<void>>());
  const frameRefs = useRef<[HTMLIFrameElement | null, HTMLIFrameElement | null]>([null, null]);
  const launchRequestRef = useRef(0);
  const frameSwapRef = useRef<Promise<void> | null>(null);
  const silentRefreshTimerRef = useRef<number | null>(null);
  const silentRefreshRunningRef = useRef<Promise<void> | null>(null);
  const silentRefreshQueuedRef = useRef(false);
  const attachmentInputRef = useRef<HTMLInputElement>(null);
  const resumingTaskRef = useRef<string | null>(null);
  const launch = frameSlots[activeFrameIndex];
  const [launchLoading, setLaunchLoading] = useState(true);
  const [launchError, setLaunchError] = useState<unknown>();

  useEffect(() => {
    bridgeContextRef.current = bridgeContext;
  }, [bridgeContext]);

  useEffect(() => {
    for (const [index, frame] of frameRefs.current.entries()) {
      if (!frame) continue;
      const blocked = index !== activeFrameIndex || (isMobile && assistantOpen);
      if (blocked) frame.setAttribute('inert', '');
      else frame.removeAttribute('inert');
    }
  }, [activeFrameIndex, assistantOpen, frameSlots, isMobile]);

  const closeAssistant = useMobileBackDismiss(assistantOpen, isMobile, setAssistantOpen, 'business-assistant');
  const { data: restoredBusinessTask } = useQuery({
    queryKey: ['terminal-business-task', businessTaskId],
    queryFn: () => terminal.getTask(businessTaskId!),
    enabled: Boolean(businessTaskId),
  });
  const restoredBusinessTaskRunning = restoredBusinessTask?.run_status === 'queued'
    || restoredBusinessTask?.run_status === 'running';
  const conversationLocked = assistantRunning || restoredBusinessTaskRunning;
  const { data: availableInputFiles = [] } = useQuery<WorkspaceFileSummary[]>({
    queryKey: ['terminal-business-input-files'],
    queryFn: () => terminal.listAllWsFiles(),
    enabled: assistantOpen,
  });
  const { data: fileCapabilityRegistry } = useQuery({
    queryKey: ['workspace-file-capabilities'],
    queryFn: () => terminal.fileCapabilities(),
    enabled: assistantOpen,
    staleTime: 5 * 60_000,
  });
  const formatCapabilityByExtension = new Map(
    (fileCapabilityRegistry?.formats ?? []).map((item) => [item.format.toLowerCase(), item]),
  );

  const inputCapabilityLabel = (file: WorkspaceFileSummary): string => {
    const name = file.presentation?.display_name || file.original_filename || file.path;
    const extension = name.split('.').pop()?.toLowerCase() || '';
    const capability = formatCapabilityByExtension.get(extension);
    if (!capability) return '暂不支持';
    if (capability.nativeOrCompatibility === 'native' && capability.capabilities.edit) return '可直接编辑';
    if (capability.nativeOrCompatibility === 'compatibility' && capability.capabilities.convert) return '转换后编辑';
    if (capability.capabilities.inspect) return '仅可读取';
    return '暂不支持';
  };

  useEffect(() => {
    if (!restoredBusinessTask || assistantRunning) return;
    setAssistantMessages(restoredBusinessTask.messages
      .filter((item) => item.role === 'user' || item.role === 'assistant')
      .map((item) => ({
        role: item.role as 'user' | 'assistant',
        content: item.content,
        artifacts: item.role === 'assistant' ? businessArtifactsFromMessage(item) : [],
        pageKey: typeof (item.metadata?.page_context as Record<string, unknown> | undefined)?.page_key === 'string'
          ? String((item.metadata.page_context as Record<string, unknown>).page_key)
          : undefined,
        pageName: typeof (item.metadata?.page_context as Record<string, unknown> | undefined)?.page_name === 'string'
          ? String((item.metadata.page_context as Record<string, unknown>).page_name)
          : typeof (item.metadata?.page_context as Record<string, unknown> | undefined)?.module_name === 'string'
            ? String((item.metadata.page_context as Record<string, unknown>).module_name)
            : undefined,
        navigationSuggestion: item.role === 'assistant'
          ? item.metadata?.navigation_suggestion as Record<string, unknown> | undefined
          : undefined,
      })));
    setRuntimeApprovals(businessApprovalsFromTask(restoredBusinessTask));
  }, [restoredBusinessTask, assistantRunning]);

  const updateRunningAssistant = useCallback((
    update: (message: AssistantConversationMessage) => AssistantConversationMessage,
  ) => {
    setAssistantMessages((items) => {
      const next = [...items];
      for (let index = next.length - 1; index >= 0; index -= 1) {
        if (next[index].role === 'assistant' && next[index].running) {
          next[index] = update(next[index]);
          break;
        }
      }
      return next;
    });
  }, []);

  useEffect(() => {
    if (!assistantRunning) return undefined;
    const updateElapsed = () => updateRunningAssistant((item) => ({
      ...item,
      elapsedSeconds: Math.max(0, Math.floor((Date.now() - (item.startedAt ?? Date.now())) / 1000)),
    }));
    updateElapsed();
    const timer = window.setInterval(updateElapsed, 1_000);
    return () => window.clearInterval(timer);
  }, [assistantRunning, updateRunningAssistant]);
  const acquireFreshLaunch = useCallback(async () => {
    if (application.is_active === false) throw new ApiError(403, '应用已停用，不能启动');
    // Launch URLs contain single-use SSO tickets. They must never enter the
    // shared React Query cache or be reused when an iframe is remounted.
    const freshLaunch = await terminal.launchApplication(application.id, moduleKey ?? undefined);
    validatedLaunchOrigin(freshLaunch, application);
    return freshLaunch;
  }, [application, moduleKey]);

  const requestFreshLaunch = useCallback(async () => {
    const requestId = ++launchRequestRef.current;
    setFrameLoaded(false);
    setFrameSlow(false);
    setFrameSlots([undefined, undefined]);
    setActiveFrameIndex(0);
    setLaunchLoading(true);
    setLaunchError(undefined);
    try {
      const freshLaunch = await acquireFreshLaunch();
      if (launchRequestRef.current === requestId) {
        setFrameSlots([freshLaunch, undefined]);
        setLaunchLoading(false);
      }
      return freshLaunch;
    } catch (launchRequestError) {
      if (launchRequestRef.current === requestId) {
        setLaunchError(launchRequestError);
        setLaunchLoading(false);
      }
      throw launchRequestError;
    }
  }, [acquireFreshLaunch]);

  const replaceFrameAtomically = useCallback(async () => {
    if (frameSwapRef.current) return frameSwapRef.current;
    const operation = (async () => {
      const freshLaunch = await acquireFreshLaunch();
      const security = validatedLaunchOrigin(freshLaunch, application);
      if (!security || freshLaunch.display_mode !== 'embedded') throw new Error('应用不支持内嵌刷新');
      const previousIndex = activeFrameIndex;
      const nextIndex: 0 | 1 = previousIndex === 0 ? 1 : 0;
      let readySeen = false;
      let latestContext: Record<string, unknown> | null = null;
      let cleanup = () => undefined;
      const ready = new Promise<Record<string, unknown>>((resolve, reject) => {
        const finish = () => {
          if (!readySeen || !latestContext) return;
          cleanup();
          resolve(latestContext);
        };
        const onMessage = (event: MessageEvent) => {
          if (event.source !== frameRefs.current[nextIndex]?.contentWindow || event.origin !== security.origin) return;
          if (isBridgeReady(event.data, security.expectation)) {
            readySeen = true;
            frameRefs.current[nextIndex]?.contentWindow?.postMessage(
              buildHostReadyMessage(
                security.expectation,
                freshLaunch.module_keys ?? [],
                freshLaunch.page_keys ?? [],
              ),
              security.origin,
            );
            finish();
            return;
          }
          const parsed = parseBridgeContext(event.data, security.expectation);
          if (!parsed) return;
          const receivedModuleKey = typeof parsed.module_key === 'string' ? parsed.module_key : '';
          const receivedPageKey = typeof parsed.page_key === 'string' ? parsed.page_key : '';
          if (!(freshLaunch.module_keys ?? []).includes(receivedModuleKey)) return;
          if (!(freshLaunch.page_keys ?? []).includes(receivedPageKey)) return;
          latestContext = parsed;
          finish();
        };
        const timeout = window.setTimeout(() => {
          cleanup();
          reject(new Error('业务应用静默刷新超时'));
        }, 12_000);
        cleanup = () => {
          window.clearTimeout(timeout);
          window.removeEventListener('message', onMessage);
        };
        window.addEventListener('message', onMessage);
      });
      setFrameSlots((current) => {
        const next = [...current] as [EnterpriseApplicationLaunch | undefined, EnterpriseApplicationLaunch | undefined];
        next[nextIndex] = freshLaunch;
        return next;
      });
      try {
        const context = await ready;
        setBridgeContext(context);
        setFrameLoaded(true);
        setFrameSlow(false);
        setActiveFrameIndex(nextIndex);
        window.setTimeout(() => {
          setFrameSlots((current) => {
            if (current[nextIndex]?.launch_nonce !== freshLaunch.launch_nonce) return current;
            const next = [...current] as [EnterpriseApplicationLaunch | undefined, EnterpriseApplicationLaunch | undefined];
            next[previousIndex] = undefined;
            return next;
          });
        }, 0);
      } catch (error) {
        cleanup();
        setFrameSlots((current) => {
          const next = [...current] as [EnterpriseApplicationLaunch | undefined, EnterpriseApplicationLaunch | undefined];
          next[nextIndex] = undefined;
          return next;
        });
        throw error;
      }
    })();
    frameSwapRef.current = operation;
    try {
      await operation;
    } finally {
      if (frameSwapRef.current === operation) frameSwapRef.current = null;
    }
  }, [acquireFreshLaunch, activeFrameIndex, application]);

  const runSilentBridgeRefresh = useCallback(async () => {
    if (!launch || launch.display_mode !== 'embedded') return;
    const security = validatedLaunchOrigin(launch, application);
    const frame = frameRefs.current[activeFrameIndex];
    const activeModuleKey = typeof bridgeContext.module_key === 'string'
      ? bridgeContext.module_key
      : launch.module_key ?? moduleKey ?? '';
    const activePageKey = typeof bridgeContext.page_key === 'string'
      ? bridgeContext.page_key
      : launch.page_keys?.find((key) => key.startsWith(`${activeModuleKey}.`)) ?? '';
    if (!security || !frame?.contentWindow || !activeModuleKey || !activePageKey) {
      await replaceFrameAtomically();
      return;
    }
    const refreshExpectation: BridgeRefreshExpectation = {
      ...security.expectation,
      moduleKey: activeModuleKey,
      pageKey: activePageKey,
      requestId: crypto.randomUUID(),
    };
    try {
      const response = new Promise<ReturnType<typeof parseBridgeRefreshResult>>((resolve, reject) => {
        const onMessage = (event: MessageEvent) => {
          if (event.source !== frame.contentWindow || event.origin !== security.origin) return;
          const parsed = parseBridgeRefreshResult(event.data, refreshExpectation);
          if (!parsed) return;
          cleanup();
          resolve(parsed);
        };
        const timeout = window.setTimeout(() => {
          cleanup();
          reject(new Error('子系统未响应局部刷新'));
        }, 4_000);
        const cleanup = () => {
          window.clearTimeout(timeout);
          window.removeEventListener('message', onMessage);
        };
        window.addEventListener('message', onMessage);
      });
      frame.contentWindow.postMessage(buildRefreshMessage(refreshExpectation), security.origin);
      const result = await response;
      if (!result) throw new Error('子系统返回了无效刷新结果');
      if (result.status === 'deferred') return;
      if (result.status !== 'completed') throw new Error(result.error || '子系统局部刷新失败');
      if (result.dataVersion !== undefined) {
        setBridgeContext((current) => ({ ...current, data_version: result.dataVersion }));
      }
    } catch {
      await replaceFrameAtomically();
    }
  }, [activeFrameIndex, application, bridgeContext, launch, moduleKey, replaceFrameAtomically]);

  const scheduleSilentRefresh = useCallback(() => {
    if (silentRefreshTimerRef.current !== null) window.clearTimeout(silentRefreshTimerRef.current);
    const trigger = () => {
      silentRefreshTimerRef.current = null;
      if (silentRefreshRunningRef.current) {
        silentRefreshQueuedRef.current = true;
        return;
      }
      const operation = runSilentBridgeRefresh().finally(() => {
        if (silentRefreshRunningRef.current === operation) silentRefreshRunningRef.current = null;
        if (silentRefreshQueuedRef.current) {
          silentRefreshQueuedRef.current = false;
          silentRefreshTimerRef.current = window.setTimeout(trigger, 160);
        }
      });
      silentRefreshRunningRef.current = operation;
    };
    silentRefreshTimerRef.current = window.setTimeout(trigger, 160);
  }, [runSilentBridgeRefresh]);

  useEffect(() => {
    if (!businessTaskId || !restoredBusinessTaskRunning || assistantRunning) return;
    if (resumingTaskRef.current === businessTaskId) return;
    resumingTaskRef.current = businessTaskId;
    const startedAt = Date.now();
    setAssistantMessages((items) => items.some((item) => item.role === 'assistant' && item.running)
      ? items
      : [...items, {
        role: 'assistant', content: '', running: true, startedAt, elapsedSeconds: 0,
        progress: [{ key: 'reconnect', label: '正在恢复这段对话的执行进度' }],
      }]);
    setAssistantRunning(true);
    void onResumeAI(businessTaskId, (event) => {
      const liveArtifact = businessArtifactFromEvent(event);
      updateRunningAssistant((item) => {
        const progress = progressForAssistantEvent(event);
        const byVersion = new Map(
          (item.artifacts ?? []).map((artifact) => [`${artifact.fileId}:${artifact.versionId}`, artifact]),
        );
        if (liveArtifact) byVersion.set(`${liveArtifact.fileId}:${liveArtifact.versionId}`, liveArtifact);
        return {
          ...item,
          artifacts: [...byVersion.values()],
          progress: progress ? appendProgress(item.progress, progress) : item.progress,
        };
      });
    }).then((result) => {
      updateRunningAssistant((item) => ({
        ...item,
        content: result.content,
        artifacts: result.artifacts,
        navigationSuggestion: result.navigationSuggestion,
        running: false,
        failed: result.status === 'failed',
        elapsedSeconds: Math.max(1, Math.round((Date.now() - startedAt) / 1000)),
      }));
      if (result.refreshRequired) scheduleSilentRefresh();
    }).catch((error) => {
      updateRunningAssistant((item) => ({
        ...item,
        content: `执行恢复失败：${error instanceof Error ? error.message : '请稍后重试'}`,
        running: false,
        failed: true,
      }));
    }).finally(() => {
      resumingTaskRef.current = null;
      setAssistantRunning(false);
    });
  }, [
    assistantRunning,
    businessTaskId,
    onResumeAI,
    restoredBusinessTaskRunning,
    scheduleSilentRefresh,
    updateRunningAssistant,
  ]);

  const confirmationsQuery = useQuery({
    queryKey: ['application-action-confirmations'],
    queryFn: () => terminal.applicationActionConfirmations(),
    refetchInterval: 5_000,
  });
  const pendingConfirmations = (confirmationsQuery.data ?? []).filter((item) => (
    item.application_id === application.id && item.status === 'pending'
  ));
  const resolveConfirmation = useMutation({
    mutationFn: ({ id, decision }: { id: string; decision: 'approve' | 'reject' }) =>
      terminal.resolveApplicationAction(id, decision),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['application-action-confirmations'] });
      if (result.status === 'completed') {
        message.success('操作已执行');
        scheduleSilentRefresh();
      } else if (result.status === 'rejected') message.info('操作已拒绝');
      else message.warning(result.error || `操作状态：${result.status}`);
    },
    onError: (mutationError) => message.error(
      mutationError instanceof ApiError ? mutationError.message : '确认处理失败',
    ),
  });

  const refreshFrame = async () => {
    try {
      await replaceFrameAtomically();
    } catch (error) {
      message.error(error instanceof Error ? error.message : '应用刷新失败');
    }
  };

  const openFreshLaunch = async () => {
    const popup = window.open('about:blank', '_blank');
    if (popup) popup.opener = null;
    try {
      const freshLaunch = await acquireFreshLaunch();
      if (freshLaunch.url && popup) popup.location.replace(freshLaunch.url);
      else {
        popup?.close();
        if (!popup) message.warning('浏览器阻止了新窗口，请允许弹窗后重试');
      }
    } catch (openError) {
      popup?.close();
      message.error(openError instanceof ApiError ? openError.message : '应用入口获取失败');
    }
  };

  useEffect(() => {
    void requestFreshLaunch().catch(() => undefined);
    return () => { launchRequestRef.current += 1; };
  }, [requestFreshLaunch]);

  useEffect(() => () => {
    if (silentRefreshTimerRef.current !== null) window.clearTimeout(silentRefreshTimerRef.current);
    silentRefreshQueuedRef.current = false;
  }, []);

  useEffect(() => {
    if (!moduleKey && launch?.module_key) onModuleChange(launch.module_key);
  }, [launch?.module_key, moduleKey, onModuleChange]);

  useEffect(() => {
    setFrameLoaded(false); setFrameSlow(false); setBridgeContext({});
    const timer = window.setTimeout(() => setFrameSlow(true), 8000);
    return () => window.clearTimeout(timer);
  }, [application.id, moduleKey]);

  useEffect(() => {
    if (!launch?.url || launch.display_mode !== 'embedded') return;
    let security: { origin: string; expectation: BridgeExpectation };
    try {
      const result = validatedLaunchOrigin(launch, application);
      if (!result) return;
      security = result;
    } catch { return; }
    const onMessage = (event: MessageEvent) => {
      if (event.source !== frameRefs.current[activeFrameIndex]?.contentWindow || event.origin !== security.origin) return;
      if (isBridgeReady(event.data, security.expectation)) {
        setFrameLoaded(true);
        setFrameSlow(false);
        frameRefs.current[activeFrameIndex]?.contentWindow?.postMessage(
          buildHostReadyMessage(security.expectation, launch.module_keys ?? [], launch.page_keys ?? []),
          security.origin,
        );
        return;
      }
      const parsed = parseBridgeContext(event.data, security.expectation);
      if (parsed) {
        const receivedModuleKey = typeof parsed.module_key === 'string' ? parsed.module_key : null;
        const pageKey = typeof parsed.page_key === 'string' ? parsed.page_key : null;
        const allowedModules = launch.module_keys ?? [];
        const allowedPages = launch.page_keys ?? [];
        if (!receivedModuleKey || !allowedModules.includes(receivedModuleKey)) return;
        if (!pageKey || !allowedPages.includes(pageKey)) return;
        setFrameLoaded(true);
        setFrameSlow(false);
        setBridgeContext(parsed);
        bridgeContextRef.current = parsed;
        return;
      }
      const aiRequest = parseBridgeAiRun(event.data, security.expectation);
      if (!aiRequest) return;
      const target = event.source as Window;
      const respond = (payload: Record<string, unknown>) => {
        if (target !== frameRefs.current[activeFrameIndex]?.contentWindow) return;
        target.postMessage({
          ...payload,
          version: 1,
          launch_nonce: security.expectation.launchNonce,
          application_slug: security.expectation.applicationSlug,
          module_key: aiRequest.moduleKey,
          page_key: aiRequest.pageKey,
          action_key: aiRequest.actionKey,
          request_id: aiRequest.requestId,
        }, security.origin);
      };
      const activeContext = bridgeContextRef.current;
      if (
        activeContext.module_key !== aiRequest.moduleKey
        || activeContext.page_key !== aiRequest.pageKey
        || !(launch.module_keys ?? []).includes(aiRequest.moduleKey)
        || !(launch.page_keys ?? []).includes(aiRequest.pageKey)
      ) {
        respond({
          type: 'zhuojian:ai-result',
          status: 'failed',
          error: { code: 'page_context_changed', messageZh: '当前页面已变化，请在目标页面重新发起 AI 操作', retryable: false },
        });
        return;
      }
      if (specialistRunsRef.current.has(aiRequest.requestId)) {
        respond({ type: 'zhuojian:ai-progress', status: 'processing', message: '该请求正在处理中' });
        return;
      }
      const operation = (async () => {
        try {
          const created = await terminal.createSubsystemAiRun({
            applicationId: application.id,
            moduleKey: aiRequest.moduleKey,
            pageKey: aiRequest.pageKey,
            actionKey: aiRequest.actionKey,
            capability: aiRequest.capability,
            instruction: aiRequest.instruction,
            context: aiRequest.context,
            textInput: aiRequest.textInput,
            requestId: aiRequest.requestId,
            files: aiRequest.files,
          });
          respond({
            type: 'zhuojian:ai-accepted',
            status: created.status,
            run_id: created.run_id,
          });
          let previousStatus = '';
          for (let attempt = 0; attempt < 900; attempt += 1) {
            const run = await terminal.getSubsystemAiRun(created.run_id);
            if (run.status !== previousStatus) {
              previousStatus = run.status;
              respond({
                type: 'zhuojian:ai-progress',
                status: run.status,
                run_id: run.run_id,
                message: run.status === 'queued' ? '专业 AI 任务已排队' : '专业 AI 正在处理',
              });
            }
            if (run.status === 'succeeded') {
              respond({
                type: 'zhuojian:ai-result',
                status: 'draft_ready',
                run_id: run.run_id,
                result: run.result,
              });
              return;
            }
            if (run.status === 'failed' || run.status === 'cancelled') {
              respond({
                type: 'zhuojian:ai-result',
                status: run.status,
                run_id: run.run_id,
                error: run.error ?? {
                  code: run.status,
                  messageZh: run.status === 'cancelled' ? '专业 AI 任务已取消' : '专业 AI 处理失败',
                  retryable: false,
                },
              });
              return;
            }
            await new Promise((resolve) => window.setTimeout(resolve, 1_000));
          }
          respond({
            type: 'zhuojian:ai-result',
            status: 'failed',
            run_id: created.run_id,
            error: { code: 'poll_timeout', messageZh: '专业 AI 处理时间过长，请稍后查看或重试', retryable: true },
          });
        } catch (error) {
          respond({
            type: 'zhuojian:ai-result',
            status: 'failed',
            error: {
              code: error instanceof ApiError ? `http_${error.status}` : 'bridge_execution_failed',
              messageZh: error instanceof Error ? error.message : '专业 AI 操作失败，请稍后重试',
              retryable: !(error instanceof ApiError) || error.status >= 500,
            },
          });
        } finally {
          specialistRunsRef.current.delete(aiRequest.requestId);
        }
      })();
      specialistRunsRef.current.set(aiRequest.requestId, operation);
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [activeFrameIndex, application, launch]);

  const submit = async () => {
    const value = prompt.trim();
    if (!value || assistantRunning) return;
    const fallbackModuleKey = launch?.module_key ?? moduleKey ?? undefined;
    const fallbackPageKey = fallbackModuleKey
      ? launch?.page_keys?.find((key) => key.startsWith(`${fallbackModuleKey}.`))
      : undefined;
    setPrompt('');
    setRuntimeApprovals([]);
    const startedAt = Date.now();
    setAssistantMessages((items) => [
      ...items,
      {
        role: 'user',
        content: value,
        pageKey: typeof bridgeContext.page_key === 'string' ? bridgeContext.page_key : fallbackPageKey,
        pageName: typeof bridgeContext.page_name === 'string'
          ? bridgeContext.page_name
          : typeof bridgeContext.module_name === 'string' ? bridgeContext.module_name : activeModule?.name,
      },
      {
        role: 'assistant',
        content: '',
        running: true,
        startedAt,
        elapsedSeconds: 0,
        progress: [{ key: 'connect', label: '正在连接业务助手' }],
      },
    ]);
    setAssistantRunning(true);
    try {
      const selectedFileRefs: WorkspaceFileRefV1[] = selectedInputFileIds.map((fileId) => {
        const selected = availableInputFiles.find((item) => item.id === fileId);
        return {
          file_id: fileId,
          scope: 'task',
          ...(selected?.current_version_id
            ? { version_id: selected.current_version_id, follow_latest: false }
            : { follow_latest: true }),
        };
      });
      const result = await onAskAI(value, {
        application_id: application.id,
        application_slug: application.slug,
        application_name: application.name,
        page_url: safeContextPageUrl(launch?.url, bridgeContext.route),
        source: 'business_assistant',
        allowed_module_keys: launch?.module_keys ?? [],
        module_key: fallbackModuleKey,
        page_key: fallbackPageKey,
        ...bridgeContext,
      }, (event) => {
        const liveArtifact = businessArtifactFromEvent(event);
        if (liveArtifact) {
          updateRunningAssistant((item) => {
            const byVersion = new Map(
              (item.artifacts ?? []).map((artifact) => [`${artifact.fileId}:${artifact.versionId}`, artifact]),
            );
            byVersion.set(`${liveArtifact.fileId}:${liveArtifact.versionId}`, liveArtifact);
            return { ...item, artifacts: [...byVersion.values()] };
          });
        }
        if (event.type === 'approval_request') {
          const approvalId = String(event.approval_id ?? '');
          const taskId = String(event.task_id ?? '');
          if (approvalId && taskId) {
            const rawPreview = event.arguments_preview;
            const argumentsPreview = typeof rawPreview === 'string'
              ? rawPreview
              : rawPreview == null ? '' : JSON.stringify(rawPreview, null, 2);
            setRuntimeApprovals((items) => items.some((item) => item.approvalId === approvalId)
              ? items
              : [...items, {
                approvalId,
                taskId,
                tool: String(event.tool ?? ''),
                reason: String(event.reason ?? ''),
                argumentsPreview,
                expiresAt: String(event.expires_at ?? new Date(Date.now() + 5 * 60_000).toISOString()),
                runId: typeof event.run_id === 'number' ? event.run_id : undefined,
              }]);
          }
        } else if (event.type === 'approval_decided') {
          const approvalId = String(event.approval_id ?? '');
          setRuntimeApprovals((items) => items.map((item) => item.approvalId === approvalId ? {
            ...item,
            outcome: event.outcome as TerminalApprovalOutcome | undefined,
            decidedBy: event.decided_by as TerminalApprovalDecidedBy | undefined,
          } : item));
        }
        const progress = progressForAssistantEvent(event);
        if (!progress) return;
        updateRunningAssistant((item) => ({
          ...item,
          progress: appendProgress(item.progress, progress),
        }));
      }, selectedFileRefs);
      updateRunningAssistant((item) => ({
        ...item,
        content: result.content || (result.status === 'completed' ? '操作已完成。' : '执行未完成，请稍后重试。'),
        artifacts: result.artifacts,
        navigationSuggestion: result.navigationSuggestion,
        running: false,
        failed: result.status === 'failed',
        elapsedSeconds: Math.max(1, Math.round((Date.now() - startedAt) / 1000)),
        progress: appendProgress(item.progress, result.status === 'completed'
          ? { key: 'done', label: result.artifacts.length ? '文件已交付' : '回答已经生成' }
          : { key: 'error', label: '执行未完成，请查看下方原因', tone: 'error' }),
      }));
      if (result.refreshRequired) scheduleSilentRefresh();
    } catch (assistantError) {
      const errorMessage = assistantError instanceof Error ? assistantError.message : '灼见助手执行失败';
      updateRunningAssistant((item) => ({
        ...item,
        content: `执行失败：${errorMessage}`,
        running: false,
        failed: true,
        elapsedSeconds: Math.max(1, Math.round((Date.now() - startedAt) / 1000)),
        progress: appendProgress(item.progress, {
          key: 'error', label: '执行未完成，请查看下方原因', tone: 'error',
        }),
      }));
    } finally {
      setAssistantRunning(false);
    }
  };

  const uploadInputFiles = async (files: FileList | null) => {
    if (!files?.length || !targetWorkspaceId || assistantRunning) return;
    setUploadingInput(true);
    try {
      const uploadedIds: string[] = [];
      for (const file of Array.from(files).slice(0, 5)) {
        const safeName = file.name.replace(/[\\/:*?"<>|]+/g, '-').replace(/^\.+/, '') || '附件';
        const uploaded = await terminal.uploadWsFile(
          targetWorkspaceId,
          file,
          `会话附件/业务助手/${crypto.randomUUID()}-${safeName}`,
        );
        uploadedIds.push(uploaded.id);
      }
      setSelectedInputFileIds((current) => [...new Set([...current, ...uploadedIds])]);
      await queryClient.invalidateQueries({ queryKey: ['terminal-business-input-files'] });
      message.success(`已上传并引用 ${uploadedIds.length} 个文件`);
    } catch (uploadError) {
      message.error(uploadError instanceof ApiError ? uploadError.message : '附件上传失败');
    } finally {
      if (attachmentInputRef.current) attachmentInputRef.current.value = '';
      setUploadingInput(false);
    }
  };

  const downloadArtifact = async (artifact: BusinessArtifact) => {
    try {
      const blob = await terminal.downloadWsFile(artifact.fileId, undefined, artifact.versionId ?? undefined);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = artifact.name;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '文件下载失败');
    }
  };

  if (launchLoading) return <div style={{ flex: 1, display: 'grid', placeItems: 'center' }}><Spin tip="正在校验应用权限…" /></div>;
  if (launchError) {
    const unavailable = launchError instanceof ApiError && (launchError.status === 403 || launchError.status === 404);
    return <Result status={unavailable ? '403' : 'error'} title={unavailable ? '应用未授权或已停用' : '应用加载失败'} subTitle={unavailable ? (launchError.message || '请联系企业管理员审核应用、页面和允许操作。') : (launchError instanceof Error ? launchError.message : '无法获取新的应用入口')} extra={<Button onClick={() => void requestFreshLaunch().catch(() => undefined)}>重试</Button>} />;
  }
  if (!launch) return <Empty description="应用入口不可用" />;
  const activeModule = launch.modules.find((item) => item.module_key === launch.module_key);

  return (
    <div className="enterprise-app-view">
      <div className="enterprise-app-view__header">
        <Tooltip title="打开平台导航">
          <Button aria-label="打开平台导航" icon={<AppstoreOutlined />} onClick={onOpenNavigation} />
        </Tooltip>
        <div className="enterprise-app-view__icon" style={{ width: 30, height: 30, borderRadius: 9, background: '#eef2ff', color: '#6366f1', display: 'grid', placeItems: 'center', overflow: 'hidden' }}>
          {application.icon_url ? <img src={application.icon_url} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} /> : application.name.slice(0, 1)}
        </div>
        <div className="enterprise-app-view__identity">
          <Typography.Text strong title={activeModule?.name || application.name}>{activeModule?.name || application.name}</Typography.Text>
          <div>{activeModule ? `${application.name} · 原生子模块` : (application.description || '企业业务应用')}</div>
        </div>
        <Tag color={activeModule ? 'geekblue' : 'blue'} style={{ marginLeft: 4 }}>
          {activeModule ? '原生聚合' : (launch.display_mode === 'embedded' ? (immersive ? '完全沉浸' : '沉浸内嵌') : '独立应用')}
        </Tag>
        {(launch.modules ?? []).length > 1 && <Select
          className="enterprise-app-view__module-select"
          size="small"
          value={launch.module_key ?? moduleKey ?? undefined}
          style={{ minWidth: 140 }}
          options={(launch.modules ?? []).map((item) => ({ value: item.module_key, label: item.name }))}
          onChange={onModuleChange}
          aria-label="选择子模块"
        />}
        <div className="enterprise-app-view__header-spacer" />
        {!isMobile && <div className="enterprise-app-view__actions">
          {launch.display_mode === 'embedded' && <Tooltip title="重新加载模块"><Button aria-label="重新加载模块" icon={<ReloadOutlined />} onClick={() => void refreshFrame()} /></Tooltip>}
          {launch.display_mode === 'embedded' && (
            <Tooltip title={immersive ? '显示平台导航轨' : '隐藏平台导航轨'}>
              <Button
                aria-label={immersive ? '退出完全沉浸' : '进入完全沉浸'}
                icon={immersive ? <FullscreenExitOutlined /> : <FullscreenOutlined />}
                onClick={onToggleImmersive}
              ><span className="enterprise-app-view__action-label">{immersive ? '退出沉浸' : '完全沉浸'}</span></Button>
            </Tooltip>
          )}
          <Button icon={<ExportOutlined />} onClick={() => void openFreshLaunch()}><span className="enterprise-app-view__action-label">备用打开</span></Button>
        </div>}
        {isMobile && <Dropdown
          trigger={['click']}
          menu={{
            items: [
              ...(launch.display_mode === 'embedded' ? [
                { key: 'reload', label: '重新加载模块', icon: <ReloadOutlined /> },
                { key: 'immersive', label: immersive ? '退出完全沉浸' : '进入完全沉浸', icon: immersive ? <FullscreenExitOutlined /> : <FullscreenOutlined /> },
              ] : []),
              { key: 'external', label: '备用打开', icon: <ExportOutlined /> },
            ],
            onClick: ({ key }) => {
              if (key === 'reload') void refreshFrame();
              else if (key === 'immersive') onToggleImmersive();
              else if (key === 'external') void openFreshLaunch();
            },
          }}
        >
          <Button className="enterprise-app-view__more" aria-label="更多应用操作" icon={<MoreOutlined />} />
        </Dropdown>}
        {application.assistant_enabled && <Badge count={pendingConfirmations.length} size="small"><Button type="primary" icon={<RobotOutlined />} onClick={() => setAssistantOpen(true)}><span className="enterprise-app-view__action-label">灼见助手</span></Button></Badge>}
      </div>

      {launch.display_mode === 'embedded' ? (
        <div className="enterprise-app-view__frame-wrap">
          {!frameLoaded && <div className="enterprise-app-view__loading"><Spin tip={frameSlow ? '应用响应较慢，可尝试“备用打开”' : '正在加载业务应用…'} /></div>}
          {frameSlots.map((slotLaunch, slotIndex) => slotLaunch?.display_mode === 'embedded' ? (
            <iframe
              ref={(node) => { frameRefs.current[slotIndex as 0 | 1] = node; }}
              key={`frame-slot-${slotIndex}-${slotLaunch.launch_nonce}`}
              src={slotLaunch.url}
              title={activeModule?.name || application.name}
              sandbox="allow-downloads allow-forms allow-modals allow-popups allow-same-origin allow-scripts"
              allow="camera 'none'; microphone 'none'; geolocation 'none'; payment 'none'; usb 'none'; serial 'none'; clipboard-read 'none'; clipboard-write 'none'; fullscreen"
              referrerPolicy="origin"
              aria-hidden={slotIndex !== activeFrameIndex || (isMobile && assistantOpen)}
              tabIndex={slotIndex === activeFrameIndex && !(isMobile && assistantOpen) ? 0 : -1}
              className={`enterprise-app-view__frame ${slotIndex === activeFrameIndex ? 'enterprise-app-view__frame--active' : 'enterprise-app-view__frame--standby'}`}
            />
          ) : null)}
          {frameSlow && !frameLoaded && <Alert showIcon type="warning" message="业务应用尚未建立连接" description="请先检查 VPN 或网络后重试；若“备用打开”正常但这里仍无法显示，再检查业务系统是否允许 AI Platform 的 iframe 嵌入。" style={{ position: 'absolute', left: 30, right: 30, bottom: 30, zIndex: 2 }} />}
        </div>
      ) : (
        <div style={{ flex: 1, display: 'grid', placeItems: 'center' }}><Result icon={<ExportOutlined style={{ color: '#6366f1' }} />} title={`${application.name} 配置为独立打开`} subTitle="应用仍由原项目独立部署和迭代；AI Platform 负责权限、导航和业务助手。" extra={<Button type="primary" onClick={() => void openFreshLaunch()}>打开应用</Button>} /></div>
      )}

      <Drawer
        title={<Space className="business-assistant-drawer__title"><RobotOutlined style={{ color: '#6366f1' }} /><span>灼见助手</span></Space>}
        extra={<Space className="business-assistant-drawer__header-actions">
          <Button size="small" icon={<HistoryOutlined />} aria-label="历史对话" disabled={conversationLocked} onClick={() => setHistoryOpen((value) => !value)}><span className="business-assistant-drawer__header-label">历史对话</span></Button>
          <Button size="small" icon={<PlusOutlined />} aria-label="新建对话" loading={creatingConversation} disabled={conversationLocked} onClick={async () => {
            setCreatingConversation(true);
            try {
              await onNewConversation();
              setAssistantMessages([]);
              setSelectedInputFileIds([]);
              setRuntimeApprovals([]);
              setHistoryOpen(false);
            } catch (error) {
              message.error(error instanceof Error ? error.message : '新建对话失败');
            } finally {
              setCreatingConversation(false);
            }
          }}><span className="business-assistant-drawer__header-label">新建对话</span></Button>
        </Space>}
        open={assistantOpen}
        onClose={closeAssistant}
        width={isMobile ? '100%' : (isCompact ? 460 : 420)}
        rootClassName="business-assistant-drawer responsive-fullscreen-drawer"
        styles={{ body: { padding: isMobile ? '12px 12px calc(12px + env(safe-area-inset-bottom))' : undefined } }}
      >
        {historyOpen && <Card size="small" title="助手历史对话" style={{ marginBottom: 16 }}>
          {businessTasks.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无历史对话" /> : (
            <div style={{ display: 'grid', gap: 8 }}>
              {businessTasks.map((task) => {
                const page = task.last_page_context ?? {};
                const pageName = typeof page.page_name === 'string'
                  ? page.page_name
                  : typeof page.module_name === 'string' ? page.module_name : '未记录页面';
                const running = task.run_status === 'queued' || task.run_status === 'running';
                return <div
                  key={task.id}
                  style={{
                    border: task.id === businessTaskId ? '1px solid #818cf8' : '1px solid #e5e7eb',
                    borderRadius: 8,
                    padding: 10,
                    cursor: conversationLocked ? 'not-allowed' : 'pointer',
                    background: task.id === businessTaskId ? '#eef2ff' : '#fff',
                  }}
                  onClick={() => {
                    if (conversationLocked || task.id === businessTaskId) return;
                    onSelectConversation(task.id);
                    setSelectedInputFileIds([]);
                    setRuntimeApprovals([]);
                  }}
                >
                  <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <Typography.Text strong ellipsis style={{ display: 'block' }}>{task.title || '未命名对话'}</Typography.Text>
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        {new Date(task.updated_at).toLocaleString('zh-CN', { hour12: false })} · {pageName}
                      </Typography.Text>
                      <div style={{ marginTop: 4 }}>
                        {running && <Tag color="processing">执行中</Tag>}
                        <Tag>{task.artifact_count ?? 0} 个文件</Tag>
                      </div>
                    </div>
                    <Popconfirm
                      title="删除这段对话？"
                      description="只删除对话引用，已交付到工作空间的文件会保留。"
                      okText="删除"
                      cancelText="取消"
                      disabled={conversationLocked || running}
                      onConfirm={async (event) => {
                        event?.stopPropagation();
                        await onDeleteConversation(task.id);
                      }}
                    >
                      <Button
                        type="text"
                        danger
                        size="small"
                        aria-label={`删除对话 ${task.title}`}
                        icon={<DeleteOutlined />}
                        disabled={conversationLocked || running}
                        onClick={(event) => event.stopPropagation()}
                      />
                    </Popconfirm>
                  </div>
                </div>;
              })}
            </div>
          )}
        </Card>}
        <Alert
          showIcon type="info"
          message={typeof bridgeContext.module_name === 'string' ? `已连接当前模块：${bridgeContext.module_name}` : '助手会携带当前应用上下文'}
          description={typeof bridgeContext.entity_id === 'string' ? `当前业务对象：${bridgeContext.entity_id}` : '只会注册你在该应用中获准的查询、新增、更新、删除工具。旧版应用会自动使用应用首页上下文。'}
          style={{ marginBottom: 18 }}
        />
        <div style={{ marginBottom: 18 }}>
          <Typography.Text strong>本次使用模型</Typography.Text>
          <Select
            aria-label="选择灼见助手模型"
            value={modelAlias ?? undefined}
            options={models.map((model) => ({ value: model, label: model }))}
            onChange={onModelAliasChange}
            disabled={assistantRunning}
            placeholder="请选择模型"
            style={{ width: '100%', marginTop: 8 }}
          />
        </div>
        <div style={{ marginBottom: 18 }}>
          <Typography.Text strong>文件保存位置</Typography.Text>
          <Select
            aria-label="选择灼见助手文件保存位置"
            value={targetWorkspaceId ?? undefined}
            options={workspaceOptions}
            onChange={onTargetWorkspaceChange}
            disabled={assistantRunning}
            placeholder="默认保存到个人空间"
            style={{ width: '100%', marginTop: 8 }}
          />
        </div>
        <div style={{ marginBottom: 18 }}>
          <Typography.Text strong>本对话引用文件</Typography.Text>
          <Select
            mode="multiple"
            aria-label="选择灼见助手引用文件"
            value={selectedInputFileIds}
            options={availableInputFiles.map((file) => ({
              value: file.id,
              label: `${file.presentation?.display_name || file.original_filename || file.path} · ${file.workspace_name} · ${inputCapabilityLabel(file)}`,
            }))}
            onChange={setSelectedInputFileIds}
            disabled={assistantRunning || uploadingInput}
            placeholder="可选择当前有权读取的工作空间文件"
            optionFilterProp="label"
            showSearch
            maxTagCount="responsive"
            style={{ width: '100%', marginTop: 8 }}
          />
          <input
            ref={attachmentInputRef}
            type="file"
            multiple
            hidden
            onChange={(event) => { void uploadInputFiles(event.target.files); }}
          />
          <Button
            size="small"
            icon={<UploadOutlined />}
            loading={uploadingInput}
            disabled={assistantRunning || !targetWorkspaceId}
            onClick={() => attachmentInputRef.current?.click()}
            style={{ marginTop: 8 }}
          >
            上传并引用
          </Button>
          {!targetWorkspaceId && <Typography.Text type="secondary" style={{ marginLeft: 8 }}>请先选择可写工作空间</Typography.Text>}
        </div>
        {pendingConfirmations.length > 0 && <div style={{ marginBottom: 18 }}>
          <Typography.Title level={5}>等待你确认的操作</Typography.Title>
          <Space direction="vertical" style={{ width: '100%' }}>
            {pendingConfirmations.map((item) => <Card key={item.id} size="small" title={item.action.name} extra={<Tag color="red">高风险</Tag>}>
              <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>{item.action.description || `${item.action.operation} · ${item.module_key}`}</Typography.Paragraph>
              {Object.keys(item.params).length > 0 && <Typography.Paragraph code copyable style={{ marginBottom: 8 }}>{JSON.stringify(item.params, null, 2)}</Typography.Paragraph>}
              <Typography.Text type="secondary">请求编号：{item.request_id}</Typography.Text>
              <div style={{ marginTop: 12 }}><Space>
                <Button danger loading={resolveConfirmation.isPending} onClick={() => resolveConfirmation.mutate({ id: item.id, decision: 'reject' })}>拒绝</Button>
                <Button type="primary" loading={resolveConfirmation.isPending} onClick={() => resolveConfirmation.mutate({ id: item.id, decision: 'approve' })}>确认执行</Button>
              </Space></div>
            </Card>)}
          </Space>
        </div>}
        {runtimeApprovals.length > 0 && <div style={{ marginBottom: 18 }}>
          <Typography.Title level={5}>本轮需要你确认的操作</Typography.Title>
          {runtimeApprovals.map((item) => (
            <ApprovalCard key={item.approvalId} b={item} taskId={item.taskId} />
          ))}
        </div>}
        {assistantMessages.length > 0 && (
          <div aria-label="灼见助手对话" style={{ display: 'grid', gap: 10, marginBottom: 18 }}>
            {assistantMessages.map((item, index) => (
              <div
                key={`${item.role}-${index}`}
                style={{
                  padding: '10px 12px',
                  borderRadius: 10,
                  whiteSpace: 'pre-wrap',
                  background: item.role === 'user' ? '#eef2ff' : '#f5f5f5',
                  marginLeft: item.role === 'user' ? 28 : 0,
                  marginRight: item.role === 'assistant' ? 28 : 0,
                }}
              >
                <Space size={6} wrap>
                  <Typography.Text strong>{item.role === 'user' ? '我' : '灼见助手'}</Typography.Text>
                  {item.pageName && <Tag style={{ marginInlineEnd: 0 }}>当时页面：{item.pageName}</Tag>}
                </Space>
                {item.role === 'assistant' && item.progress?.length ? (
                  <div
                    className={`business-assistant-progress${item.failed ? ' business-assistant-progress--failed' : ''}`}
                    aria-live={item.running ? 'polite' : 'off'}
                    aria-label="灼见助手实时执行过程"
                  >
                    <div className="business-assistant-progress__header">
                      <span>{item.running ? '实时执行中' : (item.failed ? '执行未完成' : '本轮执行过程')}</span>
                      <span>{item.running ? `已等待 ${item.elapsedSeconds ?? 0} 秒` : `用时 ${item.elapsedSeconds ?? 0} 秒`}</span>
                    </div>
                    <div className="business-assistant-progress__steps">
                      {item.progress.map((step, progressIndex) => {
                        const active = Boolean(item.running && progressIndex === item.progress!.length - 1);
                        const failed = Boolean(!active && step.tone === 'error');
                        return (
                          <div
                            key={step.key}
                            className={`business-assistant-progress__step${active ? ' business-assistant-progress__step--active' : ''}${step.tone === 'warning' ? ' business-assistant-progress__step--warning' : ''}${step.tone === 'error' ? ' business-assistant-progress__step--error' : ''}`}
                          >
                            <span className="business-assistant-progress__icon">
                              {active ? <LoadingOutlined spin /> : (failed ? <CloseCircleFilled /> : <CheckCircleFilled />)}
                            </span>
                            <span>{step.label}</span>
                          </div>
                        );
                      })}
                    </div>
                    {item.running && <div className="business-assistant-progress__hint">执行仍在继续，进度会自动更新，请不用重复提交。</div>}
                  </div>
                ) : null}
                {item.content && item.role === 'assistant' ? (
                  <div className="business-assistant-markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{item.content}</ReactMarkdown></div>
                ) : item.content ? <Typography.Paragraph style={{ margin: '8px 0 0' }}>{item.content}</Typography.Paragraph> : null}
                {item.role === 'assistant' && item.navigationSuggestion && typeof item.navigationSuggestion.moduleKey === 'string' && (
                  <Button
                    size="small"
                    type="link"
                    style={{ paddingInline: 0, marginTop: 8 }}
                    onClick={() => onModuleChange(String(item.navigationSuggestion?.moduleKey))}
                  >
                    前往{typeof item.navigationSuggestion.pageName === 'string'
                      ? `「${item.navigationSuggestion.pageName}」`
                      : '建议页面'}
                  </Button>
                )}
                {!!item.artifacts?.length && <section aria-label="本轮交付文件" style={{ display: 'grid', gap: 8, marginTop: 10 }}>
                  {item.artifacts.map((artifact) => <Card
                    key={`${artifact.fileId}:${artifact.versionId}`}
                    size="small"
                    title={<Space><FileTextOutlined />{artifact.name}</Space>}
                    extra={<Space>
                      <Button size="small" icon={<EyeOutlined />} onClick={() => onOpenArtifact(artifact.fileId, artifact.versionId)}>预览</Button>
                      <Button size="small" icon={<DownloadOutlined />} onClick={() => void downloadArtifact(artifact)}>下载</Button>
                    </Space>}
                  >
                    <Space direction="vertical" size={2}>
                      <Typography.Text type="secondary">
                        {(artifact.name.split('.').pop() || '文件').toUpperCase()} · {formatArtifactBytes(artifact.sizeBytes)} · 版本 {artifact.versionId?.slice(0, 8)}
                      </Typography.Text>
                      <Typography.Text type="secondary">{artifact.canonicalPath || '已保存到工作空间'}</Typography.Text>
                    </Space>
                  </Card>)}
                </section>}
              </div>
            ))}
          </div>
        )}
        <Typography.Paragraph type="secondary">你可以问：</Typography.Paragraph>
        <Space direction="vertical" style={{ width: '100%', marginBottom: 16 }}>
          {['汇总当前页面异常并给出处理建议', '查询今天待处理的业务记录', '根据当前业务数据生成一份 Excel'].map((item) => <Button key={item} block style={{ textAlign: 'left' }} onClick={() => setPrompt(item)}>{item}</Button>)}
        </Space>
        {restoredBusinessTaskRunning && <Alert
          type="info"
          showIcon
          message="这段对话仍在执行，暂时不能切换或继续发送。刷新页面后会保留已有记录。"
          style={{ marginBottom: 12 }}
        />}
        <div className="business-assistant-drawer__composer">
          <Input.TextArea value={prompt} disabled={conversationLocked} onChange={(event) => setPrompt(event.target.value)} autoSize={{ minRows: 3, maxRows: 6 }} placeholder="描述你要查询或执行的业务任务…" onPressEnter={(event) => { if (!event.shiftKey) { event.preventDefault(); void submit(); } }} />
          <Button type="primary" block icon={<SendOutlined />} loading={assistantRunning} disabled={conversationLocked || !prompt.trim()} onClick={() => void submit()} style={{ marginTop: 10 }}>在当前页面执行</Button>
        </div>
      </Drawer>
    </div>
  );
}
