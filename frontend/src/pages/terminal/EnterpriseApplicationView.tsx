import { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Badge, Button, Card, Drawer, Empty, Input, Result, Select, Space, Spin, Tag, Tooltip, Typography, message } from 'antd';
import {
  AppstoreOutlined, ExportOutlined, FullscreenExitOutlined, FullscreenOutlined,
  ReloadOutlined, RobotOutlined, SendOutlined,
} from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ApiError, terminal, type EnterpriseApplicationLaunch, type TerminalEnterpriseApplication,
} from '../../api/client';
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

export default function EnterpriseApplicationView({
  application,
  moduleKey,
  onModuleChange,
  onAskAI,
  immersive,
  onOpenNavigation,
  onToggleImmersive,
}: {
  application: TerminalEnterpriseApplication;
  moduleKey: string | null;
  onModuleChange: (moduleKey: string) => void;
  onAskAI: (prompt: string, pageContext: Record<string, unknown>) => Promise<string>;
  immersive: boolean;
  onOpenNavigation: () => void;
  onToggleImmersive: () => void;
}) {
  const queryClient = useQueryClient();
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [prompt, setPrompt] = useState('');
  const [assistantRunning, setAssistantRunning] = useState(false);
  const [assistantMessages, setAssistantMessages] = useState<Array<{
    role: 'user' | 'assistant';
    content: string;
  }>>([]);
  const [frameKey, setFrameKey] = useState(0);
  const [frameLoaded, setFrameLoaded] = useState(false);
  const [frameSlow, setFrameSlow] = useState(false);
  const [bridgeContext, setBridgeContext] = useState<Record<string, unknown>>({});
  const frameRef = useRef<HTMLIFrameElement>(null);
  const launchRequestRef = useRef(0);
  const [launch, setLaunch] = useState<EnterpriseApplicationLaunch>();
  const [launchLoading, setLaunchLoading] = useState(true);
  const [launchError, setLaunchError] = useState<unknown>();
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
        setBridgeContext(parsed);
      }
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [application, launch, frameKey]);

  const submit = async () => {
    const value = prompt.trim();
    if (!value || assistantRunning) return;
    setPrompt('');
    setAssistantMessages((items) => [...items, { role: 'user', content: value }]);
    setAssistantRunning(true);
    try {
      const answer = await onAskAI(value, {
        application_id: application.id,
        application_slug: application.slug,
        application_name: application.name,
        page_url: safeContextPageUrl(launch?.url, bridgeContext.route),
        source: 'business_assistant',
        allowed_module_keys: launch?.module_keys ?? [],
        ...bridgeContext,
      });
      setAssistantMessages((items) => [...items, {
        role: 'assistant',
        content: answer || '操作已完成。',
      }]);
      await refreshFrame();
    } catch (assistantError) {
      const errorMessage = assistantError instanceof Error ? assistantError.message : '业务小助手执行失败';
      setAssistantMessages((items) => [...items, {
        role: 'assistant',
        content: `执行失败：${errorMessage}`,
      }]);
    } finally {
      setAssistantRunning(false);
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
            onLoad={() => {
              setFrameLoaded(true);
              setBridgeContext({});
              try {
                const security = validatedLaunchOrigin(launch, application);
                if (security) frameRef.current?.contentWindow?.postMessage(
                  buildHostReadyMessage(security.expectation, launch.module_keys ?? [], launch.page_keys ?? []),
                  security.origin,
                );
              } catch { /* invalid launch URL is handled by the existing fallback */ }
            }}
            className="enterprise-app-view__frame"
          />
          {frameSlow && !frameLoaded && <Alert showIcon type="warning" message="该项目可能禁止 iframe 嵌入" description="可使用右上角“备用打开”。若希望内嵌，需要独立项目允许 AI Platform 域名的 frame-ancestors。" style={{ position: 'absolute', left: 30, right: 30, bottom: 30, zIndex: 2 }} />}
        </div>
      ) : (
        <div style={{ flex: 1, display: 'grid', placeItems: 'center' }}><Result icon={<ExportOutlined style={{ color: '#6366f1' }} />} title={`${application.name} 配置为独立打开`} subTitle="应用仍由原项目独立部署和迭代；AI Platform 负责权限、导航和业务助手。" extra={<Button type="primary" onClick={() => void openFreshLaunch()}>打开应用</Button>} /></div>
      )}

      <Drawer title={<Space><RobotOutlined style={{ color: '#6366f1' }} />{application.name} · 业务小助手</Space>} open={assistantOpen} onClose={() => setAssistantOpen(false)} width={400}>
        <Alert
          showIcon type="info"
          message={typeof bridgeContext.module_name === 'string' ? `已连接当前模块：${bridgeContext.module_name}` : '助手会携带当前应用上下文'}
          description={typeof bridgeContext.entity_id === 'string' ? `当前业务对象：${bridgeContext.entity_id}` : '只会注册你在该应用中获准的查询、新增、更新、删除工具。旧版应用会自动使用应用首页上下文。'}
          style={{ marginBottom: 18 }}
        />
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
                <Typography.Paragraph style={{ margin: '4px 0 0' }}>{item.content}</Typography.Paragraph>
              </div>
            ))}
            {assistantRunning && <div style={{ padding: '8px 0' }}><Spin size="small" /> <Typography.Text type="secondary">正在理解当前页面并执行授权操作…</Typography.Text></div>}
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
