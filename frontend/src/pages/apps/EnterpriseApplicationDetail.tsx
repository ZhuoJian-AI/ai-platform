import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Alert, Button, Card, Descriptions, Empty, Form, Input, Modal, Popconfirm, Select, Space,
  Switch, Table, Tabs, Tag, TreeSelect, Typography, message,
} from 'antd';
import {
  ApiOutlined, AppstoreOutlined, ArrowLeftOutlined, CheckCircleOutlined,
  CloudServerOutlined, EditOutlined, ExportOutlined, LinkOutlined, LockOutlined,
  PlayCircleOutlined, PlusOutlined, RobotOutlined, SafetyCertificateOutlined, ThunderboltOutlined,
} from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ApiError, enterpriseApplications,
  type EnterpriseApplicationCapability,
  type EnterpriseApplicationAction,
  type EnterpriseApplicationInput,
  type EnterpriseApplicationOperation,
  type EnterpriseApplicationPermission,
} from '../../api/client';
import { FinderShell } from '../../components/finder/primitives';
import { useOrgTree } from '../../hooks/useOrgTree';
import './EnterpriseApplicationDetail.css';
import { validateHttpsApplicationUrl } from '../../utils/applicationUrl';

const OPERATION_META: Record<EnterpriseApplicationOperation, { label: string; color: string }> = {
  query: { label: '查询', color: '#2563eb' },
  create: { label: '新增', color: '#059669' },
  update: { label: '更新', color: '#d97706' },
  delete: { label: '删除', color: '#dc2626' },
  approve: { label: '审批', color: '#ea580c' },
  export: { label: '导出', color: '#7c3aed' },
};

const PERMISSION_LABEL: Record<EnterpriseApplicationPermission, string> = {
  view: '访问应用',
  ai_query: 'AI 查询',
  ai_create: 'AI 新增',
  ai_update: 'AI 更新',
  ai_delete: 'AI 删除',
  ai_approve: 'AI 审批',
  export: '导出',
};

const TARGET_LABEL = {
  tool_endpoint: '连接器端点',
  data_interface: '数据接口',
  skill_folder: 'Skill 运行包',
};

function errorText(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback;
}

function statusLabel(capability: EnterpriseApplicationCapability) {
  if (!capability.binding_active) return <Tag>绑定已停用</Tag>;
  if (!capability.target_active) return <Tag color="red">资源不可用</Tag>;
  if (capability.health_status === 'healthy' || capability.health_status === 'ready') {
    return <Tag color="green">可调用</Tag>;
  }
  if (capability.health_status === 'unhealthy' || capability.health_status === 'unavailable') {
    return <Tag color="red">检查失败</Tag>;
  }
  return <Tag color="blue">已启用</Tag>;
}

export default function EnterpriseApplicationDetail() {
  const { appId = '' } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { nodeMap, treeData } = useOrgTree();
  const [editOpen, setEditOpen] = useState(false);
  const [routeOpen, setRouteOpen] = useState(false);
  const [form] = Form.useForm();
  const [integrationForm] = Form.useForm();
  const [routeForm] = Form.useForm();

  const appQuery = useQuery({
    queryKey: ['enterprise-application', appId],
    queryFn: () => enterpriseApplications.get(appId),
    enabled: !!appId,
  });
  const overviewQuery = useQuery({
    queryKey: ['enterprise-application-overview', appId],
    queryFn: () => enterpriseApplications.overview(appId),
    enabled: !!appId,
  });
  const integrationQuery = useQuery({
    queryKey: ['enterprise-application-integration', appId],
    queryFn: () => enterpriseApplications.integration(appId),
    enabled: !!appId,
    retry: false,
  });
  const routesQuery = useQuery({
    queryKey: ['enterprise-application-event-routes', appId],
    queryFn: () => enterpriseApplications.eventRoutes(appId),
    enabled: !!appId,
  });
  const actionsQuery = useQuery({
    queryKey: ['enterprise-application-actions', appId],
    queryFn: () => enterpriseApplications.actions(appId),
    enabled: !!appId,
  });
  const app = appQuery.data;
  const overview = overviewQuery.data;
  const organizationAppsQuery = useQuery({
    queryKey: ['enterprise-applications', app?.organization_id],
    queryFn: () => enterpriseApplications.list(app!.organization_id),
    enabled: !!app?.organization_id,
  });

  useEffect(() => {
    if (!app) return;
    integrationForm.setFieldsValue({
      manifest_url: integrationQuery.data?.manifest_url || `${app.entry_url.replace(/\/$/, '')}/api/integration/manifest`,
      manifest_access_token: '',
      sso_exchange_token: '',
      action_signing_secret: '',
      event_signing_secret: '',
      sync_enabled: integrationQuery.data?.sync_enabled ?? true,
    });
  }, [app, integrationForm, integrationQuery.data]);

  const refresh = () => Promise.all([
    qc.invalidateQueries({ queryKey: ['enterprise-application', appId] }),
    qc.invalidateQueries({ queryKey: ['enterprise-application-overview', appId] }),
  ]);

  const updateApp = useMutation({
    mutationFn: (values: Partial<EnterpriseApplicationInput>) => {
      const securityBoundaryChanged = !!app && (
        values.entry_url !== app.entry_url || values.display_mode !== app.display_mode
      );
      return enterpriseApplications.update(appId, securityBoundaryChanged ? { ...values, is_active: false } : values);
    },
    onSuccess: () => {
      setEditOpen(false);
      refresh();
      message.success('应用配置已保存');
    },
    onError: (error) => message.error(errorText(error, '保存失败')),
  });
  const testApp = useMutation({
    mutationFn: () => enterpriseApplications.test(appId),
    onSuccess: (result) => {
      refresh();
      if (result.status === 'healthy') message.success(`页面连接正常${result.status_code ? `（HTTP ${result.status_code}）` : ''}`);
      else message.error(result.detail || '页面连接失败');
    },
    onError: (error) => message.error(errorText(error, '连接测试失败')),
  });
  const configureIntegration = useMutation({
    mutationFn: (values: {
      manifest_url: string;
      manifest_access_token?: string;
      sso_exchange_token?: string;
      action_signing_secret?: string;
      event_signing_secret?: string;
      sync_enabled: boolean;
    }) => {
      const payload = { ...values };
      const secretFields = [
        'manifest_access_token',
        'sso_exchange_token',
        'action_signing_secret',
        'event_signing_secret',
      ] as const;
      for (const field of secretFields) {
        const value = payload[field];
        if (!value?.trim()) delete payload[field];
        else payload[field] = value.trim();
      }
      return enterpriseApplications.configureIntegration(appId, payload);
    },
    onSuccess: (result) => {
      qc.setQueryData(['enterprise-application-integration', appId], result);
      integrationForm.setFieldsValue({
        manifest_access_token: '',
        sso_exchange_token: '',
        action_signing_secret: '',
        event_signing_secret: '',
      });
      message.success('子系统连接已保存，密钥不会回显');
    },
    onError: (error) => message.error(errorText(error, '连接配置保存失败')),
  });
  const revokeIntegration = useMutation({
    mutationFn: () => enterpriseApplications.configureIntegration(appId, {
      manifest_url: integrationQuery.data!.manifest_url,
      clear_auth_token: true,
      clear_sso_exchange_token: true,
      clear_action_signing_secret: true,
      clear_event_signing_secret: true,
      sync_enabled: false,
    }),
    onSuccess: (result) => {
      qc.setQueryData(['enterprise-application-integration', appId], result);
      message.success('连接密钥已撤销，新的登录和 AI 操作已停止');
    },
    onError: (error) => message.error(errorText(error, '撤销连接密钥失败')),
  });
  const syncIntegration = useMutation({
    mutationFn: () => enterpriseApplications.syncIntegration(appId),
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ['enterprise-application-integration', appId] });
      qc.invalidateQueries({ queryKey: ['enterprise-application-actions', appId] });
      if (result.status === 'healthy') {
        message.success(`同步完成：新增 ${result.received_events} 个事件，生成 ${result.created_work_items} 个跨部门待办，投递 ${result.delivered_events} 个目标系统事件`);
      } else if (result.status === 'pending_review') {
        message.info('同步完成；新清单需要管理员审核后才会生效');
      } else message.error(result.detail || '子系统同步失败');
    },
    onError: (error) => message.error(errorText(error, '子系统同步失败')),
  });
  const reviewManifest = useMutation({
    mutationFn: (decision: 'approve' | 'reject') => {
      const expectedDigest = integrationQuery.data?.pending_manifest_digest;
      if (!expectedDigest) return Promise.reject(new Error('待审核清单摘要缺失，请先刷新'));
      return enterpriseApplications.reviewManifest(appId, decision, expectedDigest);
    },
    onSuccess: (result, decision) => {
      qc.setQueryData(['enterprise-application-integration', appId], result);
      void Promise.all([
        qc.invalidateQueries({ queryKey: ['enterprise-application-actions', appId] }),
        qc.invalidateQueries({ queryKey: ['enterprise-application-overview', appId] }),
      ]);
      message.success(decision === 'approve' ? 'Manifest 变更已批准并生效' : 'Manifest 变更已拒绝，继续使用当前版本');
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) {
        void qc.invalidateQueries({ queryKey: ['enterprise-application-integration', appId] });
        message.warning('清单已发生变化，已刷新待审核内容，请重新确认');
        return;
      }
      message.error(errorText(error, 'Manifest 审核失败'));
    },
  });
  const routePayload = (route: NonNullable<typeof routesQuery.data>[number]) => ({
    name: route.name,
    event_type: route.event_type,
    module_key: route.module_key,
    target_scope_type: route.target_scope_type,
    target_scope_id: route.target_scope_id,
    target_application_id: route.target_application_id,
    target_module_key: route.target_module_key,
    is_active: route.is_active,
  });
  const saveRoute = useMutation({
    mutationFn: (values: { name: string; event_type: string; module_key?: string; target_scope: string; target_application_id?: string; target_module_key?: string }) => {
      const [prefix, id] = values.target_scope.split(':', 2);
      const scopeType = prefix === 'org' ? 'organization' : prefix === 'dept' ? 'department' : prefix as 'team' | 'user';
      return enterpriseApplications.replaceEventRoutes(appId, [
        ...(routesQuery.data ?? []).map(routePayload),
        {
          name: values.name, event_type: values.event_type, module_key: values.module_key || null,
          target_scope_type: scopeType, target_scope_id: scopeType === 'organization' ? null : id,
          target_application_id: values.target_application_id || null,
          target_module_key: values.target_module_key || null, is_active: true,
        },
      ]);
    },
    onSuccess: () => {
      setRouteOpen(false);
      routeForm.resetFields();
      qc.invalidateQueries({ queryKey: ['enterprise-application-event-routes', appId] });
      message.success('跨部门分发规则已保存');
    },
    onError: (error) => message.error(errorText(error, '分发规则保存失败')),
  });
  const removeRoute = useMutation({
    mutationFn: (routeId: string) => enterpriseApplications.replaceEventRoutes(
      appId, (routesQuery.data ?? []).filter((route) => route.id !== routeId).map(routePayload),
    ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['enterprise-application-event-routes', appId] }),
    onError: (error) => message.error(errorText(error, '移除规则失败')),
  });

  const scopeLabel = (scopeType: string, scopeId: string | null) => {
    const prefix = scopeType === 'organization' ? 'org' : scopeType === 'department' ? 'dept' : scopeType;
    return nodeMap.get(`${prefix}:${scopeId ?? app?.organization_id ?? ''}`)?.name
      ?? (scopeType === 'organization' ? '全企业' : scopeId ?? '未知范围');
  };

  const operationCards = (['query', 'create', 'update', 'delete'] as EnterpriseApplicationOperation[]).map((operation) => ({
    operation,
    value: overview?.operation_counts[operation] ?? 0,
    ...OPERATION_META[operation],
  }));

  const openEdit = () => {
    if (!app) return;
    form.setFieldsValue({
      name: app.name,
      description: app.description,
      entry_url: app.entry_url,
      display_mode: app.display_mode,
      is_active: app.is_active,
      assistant_enabled: app.assistant_enabled,
      assistant_prompt: app.assistant_prompt,
    });
    setEditOpen(true);
  };

  const capabilityColumns = useMemo(() => [
    {
      title: 'AI 工具', dataIndex: 'name',
      render: (name: string, row: EnterpriseApplicationCapability) => (
        <div className="app-detail-tool-name">
          <Typography.Text strong>{name}</Typography.Text>
          <Typography.Text type="secondary">{row.description || `${row.source_name}提供的业务能力`}</Typography.Text>
        </div>
      ),
    },
    { title: '来源', dataIndex: 'source_name', width: 180 },
    {
      title: '接口', width: 290,
      render: (_: unknown, row: EnterpriseApplicationCapability) => row.path ? (
        <Space size={6}><Tag color="blue">{row.method || 'CALL'}</Tag><Typography.Text code>{row.path}</Typography.Text></Space>
      ) : <Tag>{TARGET_LABEL[row.target_type]}</Tag>,
    },
    {
      title: '权限动作', dataIndex: 'operation', width: 110,
      render: (operation: EnterpriseApplicationOperation) => (
        <Tag color={OPERATION_META[operation].color}>{OPERATION_META[operation].label}</Tag>
      ),
    },
    { title: '状态', width: 110, render: (_: unknown, row: EnterpriseApplicationCapability) => statusLabel(row) },
  ], []);

  if (appQuery.isLoading || overviewQuery.isLoading) {
    return <FinderShell><div className="app-detail-loading">正在汇总企业应用配置…</div></FinderShell>;
  }
  if (!app) {
    return <FinderShell><Empty description="应用不存在或无权访问" /></FinderShell>;
  }

  const pendingManifestReview = integrationQuery.data?.manifest_review_status === 'pending'
    ? integrationQuery.data
    : null;
  const changedManifestPaths = Array.from(new Set(
    (pendingManifestReview?.manifest_diff ?? []).flatMap((item) => (
      Array.isArray(item.changedPaths)
        ? item.changedPaths.filter((path): path is string => typeof path === 'string' && path.length > 0)
        : []
    )),
  ));
  const securitySensitiveManifestChange = (pendingManifestReview?.manifest_diff ?? [])
    .some((item) => item.securitySensitive === true);
  const changedManifestPathCount = Math.max(
    changedManifestPaths.length,
    ...(pendingManifestReview?.manifest_diff ?? []).map((item) => (
      typeof item.changedPathCount === 'number' ? item.changedPathCount : 0
    )),
  );
  const changedManifestPathsTruncated = (pendingManifestReview?.manifest_diff ?? [])
    .some((item) => item.changedPathsTruncated === true);

  const permissionTable = (
    <Table
      rowKey="id"
      pagination={false}
      dataSource={app.grants}
      locale={{ emptyText: '尚未授权任何部门，普通用户看不到此应用' }}
      columns={[
        {
          title: '可使用范围',
          render: (_: unknown, row) => <Space><Tag>{row.scope_type}</Tag><Typography.Text strong>{scopeLabel(row.scope_type, row.scope_id)}</Typography.Text></Space>,
        },
        {
          title: '应用与 AI 权限', dataIndex: 'permissions',
          render: (permissions: EnterpriseApplicationPermission[]) => (
            <Space wrap>{permissions.map((permission) => (
              <Tag key={permission} color={permission === 'view' ? 'blue' : permission === 'ai_delete' ? 'red' : 'purple'}>
                {PERMISSION_LABEL[permission]}
              </Tag>
            ))}</Space>
          ),
        },
        {
          title: '子模块权限', dataIndex: 'module_access',
          render: (access: Record<string, { role: string; permissions: EnterpriseApplicationPermission[] }>) => (
            Object.keys(access ?? {}).length ? <Space wrap>{Object.entries(access).map(([moduleKey, value]) => (
              <Tag key={moduleKey} color="cyan">{moduleKey} · {value.role}</Tag>
            ))}</Space> : <Tag>沿用应用级权限</Tag>
          ),
        },
        {
          title: '结论', width: 180,
          render: (_: unknown, row) => row.permissions.includes('ai_query')
            ? <Typography.Text type="success"><CheckCircleOutlined /> AI 可在此范围调用</Typography.Text>
            : <Typography.Text type="secondary"><LockOutlined /> 仅查看应用</Typography.Text>,
        },
      ]}
    />
  );

  const recentCallsTable = (
    <Table
      rowKey="id"
      pagination={false}
      dataSource={overview?.recent_calls ?? []}
      locale={{ emptyText: '暂无工具调用记录；应用页面访问不会被计为 AI 工具调用' }}
      columns={[
        { title: '工具', dataIndex: 'capability_name' },
        { title: '接口', width: 300, render: (_: unknown, row) => <Space><Tag>{row.method || 'CALL'}</Tag><Typography.Text code>{row.path || '-'}</Typography.Text></Space> },
        { title: '结果', width: 110, render: (_: unknown, row) => <Tag color={row.status === 'success' ? 'green' : 'red'}>{row.status === 'success' ? '成功' : '失败'}</Tag> },
        { title: '耗时', width: 100, render: (_: unknown, row) => row.latency_ms == null ? '-' : `${row.latency_ms} ms` },
        { title: '时间', dataIndex: 'created_at', width: 190, render: (value: string) => new Date(value).toLocaleString('zh-CN') },
      ]}
    />
  );

  const capabilitiesPanel = (
    <div className="app-detail-section-stack">
      <div className="app-detail-metrics">
        {operationCards.map((item) => (
          <Card key={item.operation} className="app-detail-metric-card">
            <div className="app-detail-metric-icon" style={{ color: item.color }}><ThunderboltOutlined /></div>
            <div><div className="app-detail-metric-value">{item.value}</div><div className="app-detail-metric-label">{item.label}工具</div></div>
          </Card>
        ))}
      </div>
      <Card
        title={<Space><ApiOutlined />AI 实际可调用能力</Space>}
        extra={<Button type="link" onClick={() => navigate(`/enterprise-apps/assistant?app=${app.id}`)}>管理工具绑定</Button>}
      >
        <Alert
          showIcon
          type="info"
          message={`当前应用配置 ${overview?.direct_capability_count ?? 0} 个业务接口${overview?.skill_binding_count ? `，另有 ${overview.skill_binding_count} 个运行包负责执行` : ''}。只有启用且用户具备对应权限的能力才会注册给 AI。`}
          style={{ marginBottom: 16 }}
        />
        <Table rowKey="binding_id" pagination={false} dataSource={overview?.capabilities ?? []} columns={capabilityColumns} />
      </Card>
      <Card title={<Space><SafetyCertificateOutlined />部门权限</Space>} extra={<Button type="link" onClick={() => navigate(`/enterprise-apps/permissions?app=${app.id}`)}>编辑权限</Button>}>
        {permissionTable}
      </Card>
      <div className="app-detail-two-columns">
        <Card title={<Space><RobotOutlined />业务小助手</Space>}>
          <Descriptions column={1} size="small">
            <Descriptions.Item label="状态"><Tag color={app.assistant_enabled ? 'green' : 'default'}>{app.assistant_enabled ? '已启用' : '未启用'}</Tag></Descriptions.Item>
            <Descriptions.Item label="业务提示词">{app.assistant_prompt ? '已配置' : '使用平台默认提示词'}</Descriptions.Item>
            <Descriptions.Item label="绑定能力">{overview?.active_capability_count ?? 0} 个动作</Descriptions.Item>
          </Descriptions>
          <Button type="link" style={{ paddingInline: 0 }} onClick={() => navigate(`/enterprise-apps/assistant?app=${app.id}`)}>查看助手配置</Button>
        </Card>
        <Card title={<Space><CloudServerOutlined />最近工具调用</Space>}>
          {(overview?.recent_calls.length ?? 0) > 0 ? (
            <div className="app-detail-call-summary">
              {overview?.recent_calls.slice(0, 3).map((call) => (
                <div key={call.id}><span>{call.capability_name}</span><Tag color={call.status === 'success' ? 'green' : 'red'}>{call.status === 'success' ? '成功' : '失败'}</Tag></div>
              ))}
            </div>
          ) : <Typography.Text type="secondary">尚无真实工具调用</Typography.Text>}
        </Card>
      </div>
    </div>
  );

  const tabItems = [
    {
      key: 'overview', label: '应用概览',
      children: (
        <div className="app-detail-two-columns">
          <Card title="应用状态">
            <Descriptions column={1}>
              <Descriptions.Item label="运行状态"><Tag color={app.is_active ? 'green' : 'default'}>{app.is_active ? '已启用' : '已停用'}</Tag></Descriptions.Item>
              <Descriptions.Item label="页面连接"><Tag color={app.health_status === 'healthy' ? 'green' : 'default'}>{app.health_status === 'healthy' ? '正常' : app.health_status}</Tag></Descriptions.Item>
              <Descriptions.Item label="展示方式">{app.display_mode === 'embedded' ? '平台内嵌' : '外部打开'}</Descriptions.Item>
              <Descriptions.Item label="工具动作">{overview?.active_capability_count ?? 0}</Descriptions.Item>
            </Descriptions>
          </Card>
          <Card title="管理员下一步">
            <Space direction="vertical" align="start">
              <Button type="link" icon={<ApiOutlined />} onClick={() => navigate(`/enterprise-apps/assistant?app=${app.id}`)}>确认 AI 能调用哪些接口</Button>
              <Button type="link" icon={<SafetyCertificateOutlined />} onClick={() => navigate(`/enterprise-apps/permissions?app=${app.id}`)}>设置哪些部门可以使用</Button>
              <Button type="link" icon={<RobotOutlined />} onClick={() => navigate(`/enterprise-apps/assistant?app=${app.id}`)}>配置业务小助手</Button>
            </Space>
          </Card>
        </div>
      ),
    },
    {
      key: 'page', label: '页面入口',
      children: <Card><Descriptions bordered column={1}><Descriptions.Item label="入口地址"><Typography.Text copyable>{app.entry_url}</Typography.Text></Descriptions.Item><Descriptions.Item label="打开方式">{app.display_mode === 'embedded' ? '平台内嵌（iframe）' : '新窗口打开'}</Descriptions.Item><Descriptions.Item label="连接状态">{app.health_status}</Descriptions.Item></Descriptions></Card>,
    },
    {
      key: 'integration', label: '系统联通',
      children: (
        <div className="app-detail-section-stack">
          <Alert
            showIcon type="info" message="页面更新与业务数据同步是两条链路"
            description="iframe 负责实时显示子系统页面；这里的 HTTPS 连接负责发现模块、增量接收业务事件，并按管理员规则生成跨部门待办。中央平台不会复制子系统业务表。"
          />
          {pendingManifestReview && (
            <Card title={<Space><SafetyCertificateOutlined />待审核的 Manifest 变更</Space>}>
              <Alert
                showIcon
                type={securitySensitiveManifestChange ? 'warning' : 'info'}
                message={securitySensitiveManifestChange ? '此次变更涉及权限或安全边界' : '子系统声明已发生变化'}
                description="批准前，平台继续使用当前已生效版本；请核对变更路径后再决定。"
                style={{ marginBottom: 16 }}
              />
              <Descriptions bordered size="small" column={1} style={{ marginBottom: 16 }}>
                <Descriptions.Item label="目标契约版本">
                  {pendingManifestReview.pending_contract_revision || '未声明'}
                </Descriptions.Item>
                <Descriptions.Item label="变更路径">
                  <Space wrap>
                    {changedManifestPaths.length > 0
                      ? changedManifestPaths.map((path) => <Typography.Text code key={path}>{path}</Typography.Text>)
                      : <Typography.Text type="secondary">清单内容有变化，但未提供路径摘要</Typography.Text>}
                    {changedManifestPathsTruncated && <Tag>共 {changedManifestPathCount} 项，仅展示前 200 项</Tag>}
                  </Space>
                </Descriptions.Item>
              </Descriptions>
              <details style={{ marginBottom: 16 }}>
                <summary style={{ cursor: 'pointer', fontWeight: 600 }}>查看当前版本与候选版本完整内容</summary>
                <div className="app-detail-two-columns" style={{ marginTop: 12 }}>
                  <Card size="small" title="当前已生效">
                    <pre style={{ maxHeight: 360, overflow: 'auto', whiteSpace: 'pre-wrap', margin: 0 }}>
                      {JSON.stringify(pendingManifestReview.manifest, null, 2)}
                    </pre>
                  </Card>
                  <Card size="small" title="等待批准">
                    <pre style={{ maxHeight: 360, overflow: 'auto', whiteSpace: 'pre-wrap', margin: 0 }}>
                      {JSON.stringify(pendingManifestReview.pending_manifest, null, 2)}
                    </pre>
                  </Card>
                </div>
              </details>
              {!pendingManifestReview.credentials_complete && (
                <Alert
                  showIcon
                  type="warning"
                  message="四类独立凭证尚未全部配置，当前不能批准"
                  style={{ marginBottom: 16 }}
                />
              )}
              <Space>
                <Popconfirm
                  title="批准这版 Manifest？"
                  description="批准后，新模块、页面与操作声明将立即成为生效版本。"
                  okText="批准"
                  cancelText="取消"
                  onConfirm={() => reviewManifest.mutate('approve')}
                >
                  <Button
                    type="primary"
                    disabled={!pendingManifestReview.credentials_complete || !pendingManifestReview.pending_manifest_digest}
                    loading={reviewManifest.isPending}
                  >
                    批准变更
                  </Button>
                </Popconfirm>
                <Popconfirm
                  title="拒绝这版 Manifest？"
                  description="拒绝后继续使用当前已生效版本。"
                  okText="拒绝"
                  cancelText="取消"
                  okButtonProps={{ danger: true }}
                  onConfirm={() => reviewManifest.mutate('reject')}
                >
                  <Button danger disabled={!pendingManifestReview.pending_manifest_digest} loading={reviewManifest.isPending}>
                    拒绝变更
                  </Button>
                </Popconfirm>
              </Space>
            </Card>
          )}
          <Card title={<Space><CloudServerOutlined />子系统连接</Space>} extra={integrationQuery.data && (
            <Button type="primary" loading={syncIntegration.isPending} onClick={() => syncIntegration.mutate()}>立即同步</Button>
          )}>
            <Form
              form={integrationForm} layout="vertical"
              initialValues={{
                manifest_url: integrationQuery.data?.manifest_url || `${app.entry_url.replace(/\/$/, '')}/api/integration/manifest`,
                manifest_access_token: '', sso_exchange_token: '', action_signing_secret: '',
                event_signing_secret: '', sync_enabled: integrationQuery.data?.sync_enabled ?? true,
              }}
              onFinish={(values) => configureIntegration.mutate(values)}
            >
              <Form.Item name="manifest_url" label="系统清单地址" extra="必须与应用入口同域；生产环境必须使用 HTTPS。" rules={[{ required: true }, { type: 'url' }]}>
                <Input prefix={<LinkOutlined />} placeholder="https://业务系统/api/integration/manifest" />
              </Form.Item>
              <Alert
                showIcon
                type="info"
                message="新系统由 ECS Runtime 自动完成凭证配置"
                description="以下输入框只用于旧系统迁移或凭证轮换；已配置的项目留空即可，不需要日常填写。"
                style={{ marginBottom: 16 }}
              />
              <div className="app-detail-two-columns">
                <Form.Item
                  name="manifest_access_token"
                  label={`清单读取凭证${integrationQuery.data?.manifest_token_configured ? '（已配置）' : ''}`}
                >
                  <Input.Password autoComplete="new-password" placeholder="zjmf_…（留空不修改）" />
                </Form.Item>
                <Form.Item
                  name="sso_exchange_token"
                  label={`登录交换凭证${integrationQuery.data?.sso_exchange_configured ? '（已配置）' : ''}`}
                >
                  <Input.Password autoComplete="new-password" placeholder="zjss_…（留空不修改）" />
                </Form.Item>
                <Form.Item
                  name="action_signing_secret"
                  label={`业务操作凭证${integrationQuery.data?.action_signing_configured ? '（已配置）' : ''}`}
                >
                  <Input.Password autoComplete="new-password" placeholder="zjac_…（留空不修改）" />
                </Form.Item>
                <Form.Item
                  name="event_signing_secret"
                  label={`事件签名凭证${integrationQuery.data?.event_signing_configured ? '（已配置）' : ''}`}
                >
                  <Input.Password autoComplete="new-password" placeholder="zjev_…（留空不修改）" />
                </Form.Item>
              </div>
              <Space size={24} align="start">
                <Form.Item name="sync_enabled" valuePropName="checked"><Switch checkedChildren="自动同步" unCheckedChildren="暂停同步" /></Form.Item>
                <Button type="primary" htmlType="submit" loading={configureIntegration.isPending}>保存连接</Button>
                {integrationQuery.data?.token_configured && <Popconfirm
                  title="撤销全部系统凭证？"
                  description="撤销后新的 iframe 登录、业务操作和自动同步都会停止。"
                  okText="确认撤销"
                  cancelText="取消"
                  okButtonProps={{ danger: true }}
                  onConfirm={() => revokeIntegration.mutate()}
                >
                  <Button danger loading={revokeIntegration.isPending}>撤销全部凭证</Button>
                </Popconfirm>}
              </Space>
            </Form>
            {integrationQuery.data && <Descriptions bordered size="small" column={2}>
              <Descriptions.Item label="同步状态"><Tag color={integrationQuery.data.sync_status === 'healthy' ? 'green' : integrationQuery.data.sync_status === 'error' ? 'red' : 'blue'}>{integrationQuery.data.sync_status}</Tag></Descriptions.Item>
              <Descriptions.Item label="已接收游标">{integrationQuery.data.cursor_sequence}</Descriptions.Item>
              <Descriptions.Item label="发现模块">{integrationQuery.data.modules.length} 个</Descriptions.Item>
              <Descriptions.Item label="四类凭证">
                <Tag color={integrationQuery.data.credentials_complete ? 'green' : 'orange'}>
                  {integrationQuery.data.credentials_complete ? '已完整配置' : '需要迁移或补齐'}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="最近同步">{integrationQuery.data.last_event_sync_at ? new Date(integrationQuery.data.last_event_sync_at).toLocaleString('zh-CN') : '尚未同步'}</Descriptions.Item>
              {integrationQuery.data.last_error && <Descriptions.Item label="最近错误" span={2}><Typography.Text type="danger">{integrationQuery.data.last_error}</Typography.Text></Descriptions.Item>}
            </Descriptions>}
          </Card>
          <Card title="已发现的业务子模块">
            <Space wrap>{integrationQuery.data?.modules.length ? integrationQuery.data.modules.map((item) => {
              const key = item.moduleKey || 'unknown';
              return <Tag key={key} color="blue">{item.name || key} · {key}</Tag>;
            }) : <Typography.Text type="secondary">首次同步成功后自动显示；之后子系统新增模块也会自动更新。</Typography.Text>}</Space>
          </Card>
          <Card title={<Space><ApiOutlined />页面与 AI 共用操作</Space>}>
            <Alert showIcon type="info" message="这些操作由模块 Manifest 自动同步" description="AI 和模块页面调用相同业务命令；标记为高风险的操作会先等待当前用户确认。" style={{ marginBottom: 14 }} />
            <Table<EnterpriseApplicationAction>
              rowKey="id"
              pagination={false}
              dataSource={actionsQuery.data ?? []}
              locale={{ emptyText: '当前系统还没有声明 v2 操作' }}
              columns={[
                { title: '操作', render: (_, row) => <div><Typography.Text strong>{row.name}</Typography.Text><div><Typography.Text type="secondary">{row.action_key}</Typography.Text></div></div> },
                { title: '子模块', dataIndex: 'module_key' },
                { title: '类型', dataIndex: 'operation', width: 100, render: (value: EnterpriseApplicationOperation) => <Tag color={OPERATION_META[value].color}>{OPERATION_META[value].label}</Tag> },
                { title: 'AI', dataIndex: 'ai_enabled', width: 90, render: (value: boolean) => <Tag color={value ? 'purple' : 'default'}>{value ? '可调用' : '页面专用'}</Tag> },
                { title: '确认', dataIndex: 'requires_confirmation', width: 100, render: (value: boolean) => <Tag color={value ? 'red' : 'green'}>{value ? '用户确认' : '直接执行'}</Tag> },
                { title: '状态', dataIndex: 'is_active', width: 90, render: (value: boolean) => <Tag color={value ? 'green' : 'default'}>{value ? '启用' : '已停用'}</Tag> },
              ]}
            />
          </Card>
          <Card title="跨部门分发规则" extra={<Button icon={<PlusOutlined />} onClick={() => setRouteOpen(true)} disabled={!integrationQuery.data?.modules.length}>新增规则</Button>}>
            <Alert showIcon type="success" message="规则只传递业务变化，不复制对方数据库" description="例如：生产部“款号资料中心”变化后，为设计部生成待办；设计部进入自己的系统继续处理。" style={{ marginBottom: 14 }} />
            <Table rowKey="id" pagination={false} dataSource={routesQuery.data ?? []} locale={{ emptyText: '尚未配置跨部门分发规则' }} columns={[
              { title: '规则', dataIndex: 'name' },
              { title: '来源子模块', dataIndex: 'module_key', render: (value: string | null) => value || '全部模块' },
              { title: '接收范围', render: (_: unknown, row) => scopeLabel(row.target_scope_type, row.target_scope_id) },
              { title: '目标系统', dataIndex: 'target_application_id', render: (value: string | null) => organizationAppsQuery.data?.find((item) => item.id === value)?.name || (value ? '已登记系统' : '仅平台待办') },
              { title: '进入目标模块', dataIndex: 'target_module_key', render: (value: string | null) => value || '跨部门待办' },
              { title: '操作', width: 90, render: (_: unknown, row) => <Button size="small" danger loading={removeRoute.isPending} onClick={() => removeRoute.mutate(row.id)}>移除</Button> },
            ]} />
          </Card>
        </div>
      ),
    },
    { key: 'capabilities', label: `AI 能力 ${overview?.direct_capability_count ?? 0}`, children: capabilitiesPanel },
    { key: 'permissions', label: `部门权限 ${app.grants.length}`, children: <Card extra={<Button type="primary" onClick={() => navigate(`/enterprise-apps/permissions?app=${app.id}`)}>编辑权限</Button>}>{permissionTable}</Card> },
    {
      key: 'assistant', label: '业务助手',
      children: <Card><Descriptions bordered column={1}><Descriptions.Item label="启用状态">{app.assistant_enabled ? '已启用' : '未启用'}</Descriptions.Item><Descriptions.Item label="提示词">{app.assistant_prompt || '未单独配置，使用平台默认提示词'}</Descriptions.Item><Descriptions.Item label="AI 工具">{overview?.direct_capability_count ?? 0} 个业务接口</Descriptions.Item></Descriptions><Button type="primary" style={{ marginTop: 16 }} onClick={() => navigate(`/enterprise-apps/assistant?app=${app.id}`)}>管理助手与工具</Button></Card>,
    },
    { key: 'calls', label: '调用记录', children: <Card>{recentCallsTable}</Card> },
  ];

  return (
    <FinderShell>
      <div className="app-detail-page">
        <div className="app-detail-header">
          <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/enterprise-apps')}>返回应用</Button>
          <div className="app-detail-identity">
            <div className="app-detail-logo"><AppstoreOutlined /></div>
            <div>
              <div className="app-detail-title-row"><Typography.Title level={3}>{app.name}</Typography.Title><Tag color={app.is_active ? 'green' : 'default'}>{app.is_active ? '已启用' : '已停用'}</Tag><Tag color={app.health_status === 'healthy' ? 'blue' : 'default'}>{app.health_status === 'healthy' ? '页面正常' : '页面待检查'}</Tag>{(overview?.operation_counts.query ?? 0) > 0 && <Tag color="purple">AI 查询可用</Tag>}</div>
              <Typography.Text type="secondary">{app.description || '企业业务应用'} · {app.slug}</Typography.Text>
            </div>
          </div>
          <Space>
            <Button icon={<PlayCircleOutlined />} loading={testApp.isPending} onClick={() => testApp.mutate()}>检查连接</Button>
            <Button icon={<ExportOutlined />} disabled={!app.is_active} title={!app.is_active ? '应用待审核或已停用' : undefined} onClick={() => window.open(app.entry_url, '_blank', 'noopener,noreferrer')}>打开应用</Button>
            <Button type="primary" icon={<EditOutlined />} onClick={openEdit}>编辑配置</Button>
          </Space>
        </div>
        <Tabs defaultActiveKey="capabilities" items={tabItems} className="app-detail-tabs" />
      </div>

      <Modal title="编辑企业应用" open={editOpen} onCancel={() => setEditOpen(false)} onOk={() => form.submit()} confirmLoading={updateApp.isPending} width={680} forceRender>
        <Form form={form} layout="vertical" onFinish={(values) => updateApp.mutate(values)}>
          <Form.Item name="name" label="应用名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="description" label="说明"><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="entry_url" label="入口地址" rules={[{ required: true }, { validator: validateHttpsApplicationUrl }]}><Input prefix={<LinkOutlined />} /></Form.Item>
          <Form.Item name="display_mode" label="打开方式"><Select options={[{ value: 'embedded', label: '平台内嵌（iframe）' }, { value: 'external', label: '外部打开' }]} /></Form.Item>
          <Form.Item name="assistant_prompt" label="业务助手提示词"><Input.TextArea rows={4} /></Form.Item>
          <Space size={32}><Form.Item name="is_active" label="审核并启用应用" valuePropName="checked"><Switch /></Form.Item><Form.Item name="assistant_enabled" label="启用业务助手" valuePropName="checked"><Switch /></Form.Item></Space>
        </Form>
      </Modal>
      <Modal title="新增跨部门分发规则" open={routeOpen} onCancel={() => setRouteOpen(false)} onOk={() => routeForm.submit()} confirmLoading={saveRoute.isPending} forceRender>
        <Form form={routeForm} layout="vertical" onFinish={(values) => saveRoute.mutate(values)}>
          <Form.Item name="name" label="规则名称" rules={[{ required: true }]}><Input placeholder="例如：款号资料更新后通知设计部" /></Form.Item>
          <Form.Item name="module_key" label="来源子模块" extra="选择“全部模块”时，这个系统的任何业务更新都会通知接收方。">
            <Select allowClear placeholder="全部模块" options={(integrationQuery.data?.modules ?? []).map((item) => ({ value: item.moduleKey, label: item.name || item.moduleKey }))} />
          </Form.Item>
          <Form.Item name="event_type" label="来源事件类型" rules={[{ required: true }]} extra="使用 Manifest 中带版本的稳定事件类型，例如 design.sample_review.approved.v1。"><Input placeholder="design.sample_review.approved.v1" /></Form.Item>
          <Form.Item name="target_scope" label="接收部门、团队或人员" rules={[{ required: true }]}><TreeSelect treeData={treeData} treeDefaultExpandAll showSearch treeNodeFilterProp="title" placeholder="例如：设计部" /></Form.Item>
          <Form.Item name="target_application_id" label="目标模块系统（可选）" extra="选择后，平台会把事件签名投递到目标系统；留空则只生成平台待办。"><Select allowClear showSearch optionFilterProp="label" options={(organizationAppsQuery.data ?? []).filter((item) => item.id !== appId).map((item) => ({ value: item.id, label: item.name }))} /></Form.Item>
          <Form.Item name="target_module_key" label="目标模块标识（可选）" extra="目标部门有独立系统时填写其模块 key；暂未接入时留空，先进入平台跨部门待办。"><Input placeholder="例如：style_design" /></Form.Item>
        </Form>
      </Modal>
    </FinderShell>
  );
}
