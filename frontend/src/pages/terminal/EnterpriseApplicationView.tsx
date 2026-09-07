import { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Badge, Button, Card, Drawer, Empty, Input, Result, Select, Space, Spin, Tag, Tooltip, Typography, message } from 'antd';
import {
  AppstoreOutlined, CheckCircleFilled, CloseCircleFilled, DownloadOutlined, ExportOutlined, EyeOutlined, FileTextOutlined,
  FullscreenExitOutlined, FullscreenOutlined, LoadingOutlined, ReloadOutlined,
  RobotOutlined, SendOutlined, UploadOutlined,
} from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ApiError, terminal, type EnterpriseApplicationLaunch, type TerminalEnterpriseApplication,
  type TerminalTaskMessage, type WorkspaceFileRefV1, type WorkspaceFileSummary,
  type TerminalApprovalDecidedBy, type TerminalApprovalOutcome,
} from '../../api/client';
import ApprovalCard, { type ApprovalCardData } from '../../components/terminal/ApprovalCard';
import {
  buildHostReadyMessage, isBridgeReady, parseBridgeContext, type BridgeExpectation,
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

function formatArtifactBytes(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '大小未知';
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

type BusinessAssistantApproval = ApprovalCardData & { taskId: string };

function progressForAssistantEvent(event: Record<string, unknown>): AssistantProgressItem | null {
  const type = String(event.type ?? '');
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
      data_interface: '已加载当前页面允许使用的业务接口',
      rag: '正在检索相关业务知识',
      ontology: '正在理解业务对象之间的关系',
      policy: '正在校验本次操作权限',
      file: '正在处理任务所需的文件',
    };
    if (category === 'data_interface') {
      const detail = event.detail && typeof event.detail === 'object'
        ? event.detail as Record<string, unknown>
        : {};
      const count = Number(event.interfaces ?? detail.interfaces);
      if (Number.isFinite(count) && count === 0) {
        // Manifest Actions are registered separately from legacy data interfaces.
        // A zero legacy-interface count therefore is not proof that this page has no
        // callable business capability.
        return { key: `trace:${category}`, label: '正在核对当前页面允许使用的业务能力' };
      }
    }
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
  models,
  modelAlias,
  onModelAliasChange,
  immersive,
  onOpenNavigation,
  onToggleImmersive,
  businessTaskId,
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
  models: string[];
  modelAlias: string | null;
  onModelAliasChange: (modelAlias: string) => void;
  immersive: boolean;
  onOpenNavigation: () => void;
  onToggleImmersive: () => void;
  businessTaskId: string | null;
  onNewConversation: () => Promise<void>;
  targetWorkspaceId: string | null;
  workspaceOptions: Array<{ value: string; label: string }>;
  onTargetWorkspaceChange: (workspaceId: string) => void;
  onOpenArtifact: (fileId: string, versionId: string | null) => void;
}) {
  const queryClient = useQueryClient();
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [prompt, setPrompt] = useState('');
  const [assistantRunning, setAssistantRunning] = useState(false);
  const [assistantMessages, setAssistantMessages] = useState<AssistantConversationMessage[]>([]);
  const [selectedInputFileIds, setSelectedInputFileIds] = useState<string[]>([]);
  const [uploadingInput, setUploadingInput] = useState(false);
  const [creatingConversation, setCreatingConversation] = useState(false);
  const [runtimeApprovals, setRuntimeApprovals] = useState<BusinessAssistantApproval[]>([]);
  const [frameKey, setFrameKey] = useState(0);
  const [frameLoaded, setFrameLoaded] = useState(false);
  const [frameSlow, setFrameSlow] = useState(false);
  const [bridgeContext, setBridgeContext] = useState<Record<string, unknown>>({});
  const frameRef = useRef<HTMLIFrameElement>(null);
  const launchRequestRef = useRef(0);
  const attachmentInputRef = useRef<HTMLInputElement>(null);
  const [launch, setLaunch] = useState<EnterpriseApplicationLaunch>();
  const [launchLoading, setLaunchLoading] = useState(true);
  const [launchError, setLaunchError] = useState<unknown>();
  const { data: restoredBusinessTask } = useQuery({
    queryKey: ['terminal-business-task', businessTaskId],
    queryFn: () => terminal.getTask(businessTaskId!),
    enabled: Boolean(businessTaskId),
  });
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
      })));
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
  const requestFreshLaunch = useCallback(async () => {
    const requestId = ++launchRequestRef.current;
    setFrameLoaded(false);
    setFrameSlow(false);
    setLaunch(undefined);
    setLaunchLoading(true);
    setLaunchError(undefined);
    try {
      if (application.is_active === false) throw new ApiError(403, '应用已停用，不能启动');
      // Launch URLs contain single-use SSO tickets. They must never enter the
      // shared React Query cache or be reused when an iframe is remounted.
      const freshLaunch = await terminal.launchApplication(application.id, moduleKey ?? undefined);
      validatedLaunchOrigin(freshLaunch, application);
      if (launchRequestRef.current === requestId) {
        setLaunch(freshLaunch);
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
  }, [application.id, application.is_active, application.slug, moduleKey]);
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
      if (result.status === 'completed') message.success('操作已执行');
      else if (result.status === 'rejected') message.info('操作已拒绝');
      else message.warning(result.error || `操作状态：${result.status}`);
    },
    onError: (mutationError) => message.error(
      mutationError instanceof ApiError ? mutationError.message : '确认处理失败',
    ),
  });

  const refreshFrame = async () => {
    setFrameLoaded(false);
    try {
      await requestFreshLaunch();
      setFrameKey((value) => value + 1);
    } catch { /* requestFreshLaunch exposes the error in the page state */ }
  };

  const openFreshLaunch = async () => {
    const popup = window.open('about:blank', '_blank');
    if (popup) popup.opener = null;
    try {
      const freshLaunch = await terminal.launchApplication(application.id, moduleKey ?? undefined);
      validatedLaunchOrigin(freshLaunch, application);
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

  useEffect(() => {
    if (!moduleKey && launch?.module_key) onModuleChange(launch.module_key);
  }, [launch?.module_key, moduleKey, onModuleChange]);

  useEffect(() => {
    setFrameLoaded(false); setFrameSlow(false); setBridgeContext({});
    const timer = window.setTimeout(() => setFrameSlow(true), 8000);
    return () => window.clearTimeout(timer);
  }, [application.id, moduleKey, frameKey]);

  useEffect(() => {
    if (!launch?.url || launch.display_mode !== 'embedded') return;
    let security: { origin: string; expectation: BridgeExpectation };
    try {
      const result = validatedLaunchOrigin(launch, application);
      if (!result) return;
      security = result;
    } catch { return; }
    const onMessage = (event: MessageEvent) => {
      if (event.source !== frameRef.current?.contentWindow || event.origin !== security.origin) return;
      if (isBridgeReady(event.data, security.expectation)) {
        setFrameLoaded(true);
        setFrameSlow(false);
        frameRef.current?.contentWindow?.postMessage(
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
      }
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [application, launch, frameKey]);

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
      { role: 'user', content: value },
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
        running: false,
        failed: result.status === 'failed',
        elapsedSeconds: Math.max(1, Math.round((Date.now() - startedAt) / 1000)),
        progress: appendProgress(item.progress, result.status === 'completed'
          ? { key: 'done', label: result.artifacts.length ? '文件已交付' : '回答已经生成' }
          : { key: 'error', label: '执行未完成，请查看下方原因', tone: 'error' }),
      }));
      await refreshFrame();
    } catch (assistantError) {
      const errorMessage = assistantError instanceof Error ? assistantError.message : '业务小助手执行失败';
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
        <div style={{ width: 30, height: 30, borderRadius: 9, background: '#eef2ff', color: '#6366f1', display: 'grid', placeItems: 'center', overflow: 'hidden' }}>
          {application.icon_url ? <img src={application.icon_url} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} /> : application.name.slice(0, 1)}
        </div>
        <div className="enterprise-app-view__identity">
          <Typography.Text strong>{activeModule?.name || application.name}</Typography.Text>
          <div>{activeModule ? `${application.name} · 原生子模块` : (application.description || '企业业务应用')}</div>
        </div>
        <Tag color={activeModule ? 'geekblue' : 'blue'} style={{ marginLeft: 4 }}>
          {activeModule ? '原生聚合' : (launch.display_mode === 'embedded' ? (immersive ? '完全沉浸' : '沉浸内嵌') : '独立应用')}
        </Tag>
        {(launch.modules ?? []).length > 1 && <Select
          size="small"
          value={launch.module_key ?? moduleKey ?? undefined}
          style={{ minWidth: 140 }}
          options={(launch.modules ?? []).map((item) => ({ value: item.module_key, label: item.name }))}
          onChange={onModuleChange}
          aria-label="选择子模块"
        />}
        <div style={{ flex: 1 }} />
        {launch.display_mode === 'embedded' && <Tooltip title="重新加载模块"><Button icon={<ReloadOutlined />} onClick={() => void refreshFrame()} /></Tooltip>}
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
        {application.assistant_enabled && <Badge count={pendingConfirmations.length} size="small"><Button type="primary" icon={<RobotOutlined />} onClick={() => setAssistantOpen(true)}><span className="enterprise-app-view__action-label">业务小助手</span></Button></Badge>}
      </div>

      {launch.display_mode === 'embedded' ? (
        <div className="enterprise-app-view__frame-wrap">
          {!frameLoaded && <div className="enterprise-app-view__loading"><Spin tip={frameSlow ? '应用响应较慢，可尝试“备用打开”' : '正在加载业务应用…'} /></div>}
          <iframe
            ref={frameRef}
            key={frameKey}
            src={launch.url}
            title={activeModule?.name || application.name}
            sandbox="allow-downloads allow-forms allow-modals allow-popups allow-same-origin allow-scripts"
            allow="camera 'none'; microphone 'none'; geolocation 'none'; payment 'none'; usb 'none'; serial 'none'; clipboard-read 'none'; clipboard-write 'none'; fullscreen"
            referrerPolicy="origin"
            className="enterprise-app-view__frame"
          />
          {frameSlow && !frameLoaded && <Alert showIcon type="warning" message="业务应用尚未建立连接" description="请先检查 VPN 或网络后重试；若“备用打开”正常但这里仍无法显示，再检查业务系统是否允许 AI Platform 的 iframe 嵌入。" style={{ position: 'absolute', left: 30, right: 30, bottom: 30, zIndex: 2 }} />}
        </div>
      ) : (
        <div style={{ flex: 1, display: 'grid', placeItems: 'center' }}><Result icon={<ExportOutlined style={{ color: '#6366f1' }} />} title={`${application.name} 配置为独立打开`} subTitle="应用仍由原项目独立部署和迭代；AI Platform 负责权限、导航和业务助手。" extra={<Button type="primary" onClick={() => void openFreshLaunch()}>打开应用</Button>} /></div>
      )}

      <Drawer
        title={<Space><RobotOutlined style={{ color: '#6366f1' }} />{application.name} · 业务小助手</Space>}
        extra={<Button size="small" loading={creatingConversation} disabled={assistantRunning} onClick={async () => {
          setCreatingConversation(true);
          try {
            await onNewConversation();
            setAssistantMessages([]);
            setSelectedInputFileIds([]);
            setRuntimeApprovals([]);
          } catch (error) {
            message.error(error instanceof Error ? error.message : '新建对话失败');
          } finally {
            setCreatingConversation(false);
          }
        }}>新建对话</Button>}
        open={assistantOpen} onClose={() => setAssistantOpen(false)} width={420}
      >
        <Alert
          showIcon type="info"
          message={typeof bridgeContext.module_name === 'string' ? `已连接当前模块：${bridgeContext.module_name}` : '助手会携带当前应用上下文'}
          description={typeof bridgeContext.entity_id === 'string' ? `当前业务对象：${bridgeContext.entity_id}` : '只会注册你在该应用中获准的查询、新增、更新、删除工具。旧版应用会自动使用应用首页上下文。'}
          style={{ marginBottom: 18 }}
        />
        <div style={{ marginBottom: 18 }}>
          <Typography.Text strong>本次使用模型</Typography.Text>
          <Select
            aria-label="选择业务小助手模型"
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
            aria-label="选择业务小助手文件保存位置"
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
            aria-label="选择业务小助手引用文件"
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
          <div aria-label="业务小助手对话" style={{ display: 'grid', gap: 10, marginBottom: 18 }}>
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
                <Typography.Text strong>{item.role === 'user' ? '我' : '业务小助手'}</Typography.Text>
                {item.role === 'assistant' && item.progress?.length ? (
                  <div
                    className={`business-assistant-progress${item.failed ? ' business-assistant-progress--failed' : ''}`}
                    aria-live={item.running ? 'polite' : 'off'}
                    aria-label="业务小助手实时执行过程"
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
        <Input.TextArea value={prompt} disabled={assistantRunning} onChange={(event) => setPrompt(event.target.value)} rows={6} placeholder="描述你要查询或执行的业务任务…" onPressEnter={(event) => { if (!event.shiftKey) { event.preventDefault(); void submit(); } }} />
        <Button type="primary" block icon={<SendOutlined />} loading={assistantRunning} disabled={!prompt.trim()} onClick={() => void submit()} style={{ marginTop: 12 }}>在当前页面执行</Button>
      </Drawer>
    </div>
  );
}
