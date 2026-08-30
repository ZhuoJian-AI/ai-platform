import { useEffect, useMemo, useState } from 'react';
import {
  Alert, Button, Card, Checkbox, Empty, Form, Input, InputNumber, Modal, Select,
  Space, Switch, Table, Tag, TreeSelect, Typography, message,
} from 'antd';
import {
  AppstoreOutlined, DeleteOutlined, EditOutlined, LinkOutlined, PlusOutlined,
  RobotOutlined, SafetyCertificateOutlined, SettingOutlined, ThunderboltOutlined,
} from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  ApiError, connectors, dataInterfaces, enterpriseApplications, skillStore,
  type EnterpriseApplication,
  type EnterpriseApplicationInput, type EnterpriseApplicationModuleAccess,
  type EnterpriseApplicationOperation,
  type EnterpriseApplicationPermission, type EnterpriseApplicationScope,
  type EnterpriseApplicationTarget,
} from '../../api/client';
import OrgSelect from '../../components/OrgSelect';
import ConfirmModal from '../../components/finder/ConfirmModal';
import { FinderShell, TitleBar } from '../../components/finder/primitives';
import { useOrgTree } from '../../hooks/useOrgTree';
import EnterpriseApplicationOnboardingWizard from './EnterpriseApplicationOnboardingWizard';

export type EnterpriseApplicationsSection = 'applications' | 'navigation' | 'permissions' | 'assistant';

const PERMISSIONS: Array<{ value: EnterpriseApplicationPermission; label: string }> = [
  { value: 'view', label: '可见' },
  { value: 'ai_query', label: 'AI 查询' },
  { value: 'ai_create', label: 'AI 新增' },
  { value: 'ai_update', label: 'AI 更新' },
  { value: 'ai_delete', label: 'AI 删除' },
  { value: 'ai_approve', label: 'AI 审批' },
  { value: 'export', label: '导出' },
];

const OPERATION_OPTIONS: Array<{ value: EnterpriseApplicationOperation; label: string }> = [
  { value: 'query', label: '查询' }, { value: 'create', label: '新增' },
  { value: 'update', label: '更新' }, { value: 'delete', label: '删除' },
  { value: 'export', label: '导出' },
];

const TARGET_OPTIONS: Array<{ value: EnterpriseApplicationTarget; label: string }> = [
  { value: 'tool_endpoint', label: '连接器端点' },
  { value: 'data_interface', label: '数据接口' },
  { value: 'skill_folder', label: 'Skill 文件夹' },
];

function errorText(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback;
}

function slugify(value: string) {
  return value.toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 100);
}

type AppFormValues = EnterpriseApplicationInput & {
  visibility_mode: 'organization' | 'selected';
  visible_scopes?: string[];
};

function grantScopeValue(
  scopeType: EnterpriseApplicationScope,
  scopeId: string | null,
  organizationId?: string,
) {
  const prefix = scopeType === 'organization' ? 'org' : scopeType === 'department' ? 'dept' : scopeType;
  return `${prefix}:${scopeId ?? organizationId ?? ''}`;
}

export default function EnterpriseApplications({ section }: { section: EnterpriseApplicationsSection }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [orgId, setOrgId] = useState<string>();
  const [editing, setEditing] = useState<EnterpriseApplication | null>(null);
  const [appModalOpen, setAppModalOpen] = useState(false);
  const [onboardingOpen, setOnboardingOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<EnterpriseApplication | null>(null);
  const [selectedAppId, setSelectedAppId] = useState<string>();
  const [grantModalOpen, setGrantModalOpen] = useState(false);
  const [grantIndex, setGrantIndex] = useState<number | null>(null);
  const [appForm] = Form.useForm();
  const [grantForm] = Form.useForm();
  const [assistantForm] = Form.useForm();
  const [bindingForm] = Form.useForm();
  const bindingTargetType = Form.useWatch('target_type', bindingForm) as EnterpriseApplicationTarget | undefined;
  const { treeData, nodeMap, isLoading: treeLoading } = useOrgTree();

  const { data: apps = [], isLoading } = useQuery({
    queryKey: ['enterprise-applications', orgId],
    queryFn: () => orgId ? enterpriseApplications.list(orgId) : Promise.resolve([]),
    enabled: !!orgId,
  });
  const { data: bindingTargets = [] } = useQuery({
    queryKey: ['enterprise-application-binding-targets', orgId],
    enabled: !!orgId && section === 'assistant',
    queryFn: async () => {
      if (!orgId) return [];
      const connectorList = await connectors.list(orgId);
      const endpointGroups = await Promise.all(connectorList.map(async (connector) => ({
        connector, endpoints: await connectors.listEndpoints(connector.id),
      })));
      const systems = await dataInterfaces.listSystems(orgId, { scope_type: 'organization', scope_id: null });
      const interfaceGroups = await Promise.all(systems.map(async (system) => ({
        system, interfaces: await dataInterfaces.listInterfaces(system.id),
      })));
      const folders = await skillStore.listFolders(orgId, { scope_type: 'organization', scope_id: null });
      return [
        ...endpointGroups.flatMap(({ connector, endpoints }) => endpoints.map((endpoint) => ({
          type: 'tool_endpoint' as const, id: endpoint.id, label: `${connector.name} / ${endpoint.name}`,
        }))),
        ...interfaceGroups.flatMap(({ system, interfaces }) => interfaces.map((item) => ({
          type: 'data_interface' as const, id: item.id, label: `${system.name} / ${item.name}`,
        }))),
        ...folders.map((folder) => ({ type: 'skill_folder' as const, id: folder.id, label: folder.name })),
      ];
    },
  });
  const { data: selectedIntegration } = useQuery({
    queryKey: ['enterprise-application-integration', selectedAppId],
    queryFn: () => selectedAppId ? enterpriseApplications.integration(selectedAppId) : Promise.reject(),
    enabled: !!selectedAppId && section === 'permissions',
    retry: false,
  });
  const selectedApp = apps.find((item) => item.id === selectedAppId) ?? apps[0];

  useEffect(() => {
    const requestedApp = searchParams.get('app');
    if (requestedApp && apps.some((item) => item.id === requestedApp)) {
      setSelectedAppId(requestedApp);
      return;
    }
    if (!selectedAppId && apps[0]) setSelectedAppId(apps[0].id);
    if (selectedAppId && apps.length && !apps.some((item) => item.id === selectedAppId)) {
      setSelectedAppId(apps[0]?.id);
    }
  }, [apps, selectedAppId, searchParams]);

  const orgTree = useMemo(() => {
    if (!orgId) return [];
    const root = treeData.find((node) => node.value === `org:${orgId}`);
    return root ? [root] : [];
  }, [treeData, orgId]);

  const appOptions = apps.map((item) => ({ value: item.id, label: item.name }));
  const scopeLabel = (scopeType: string, scopeId: string | null) => {
    const prefix = scopeType === 'organization' ? 'org' : scopeType === 'department' ? 'dept' : scopeType;
    return nodeMap.get(`${prefix}:${scopeId ?? orgId}`)?.name ?? (scopeType === 'organization' ? '全企业' : scopeId);
  };

  const invalidate = () => qc.invalidateQueries({ queryKey: ['enterprise-applications', orgId] });
  const saveApp = useMutation({
    mutationFn: async (values: AppFormValues) => {
      if (!orgId) throw new Error('请先选择企业');
      const { visibility_mode, visible_scopes = [], ...applicationInput } = values;
      let saved: EnterpriseApplication | undefined;
      try {
        saved = editing
          ? await enterpriseApplications.update(editing.id, applicationInput)
          : await enterpriseApplications.create(orgId, applicationInput);

        const selectedScopes = visibility_mode === 'organization'
          ? [`org:${orgId}`]
          : visible_scopes;
        const desiredViewScopes = new Set(selectedScopes);
        const currentGrants = editing?.grants ?? saved.grants;
        const next: Array<{
          scope_type: EnterpriseApplicationScope;
          scope_id: string | null;
          permissions: EnterpriseApplicationPermission[];
          module_keys?: string[];
          module_access?: Record<string, EnterpriseApplicationModuleAccess>;
        }> = currentGrants.flatMap((grant) => {
          const scope = grantScopeValue(grant.scope_type, grant.scope_id, orgId);
          const permissions: EnterpriseApplicationPermission[] = grant.permissions.filter(
            (permission) => permission !== 'view',
          );
          if (desiredViewScopes.has(scope)) permissions.unshift('view');
          return permissions.length ? [{
            scope_type: grant.scope_type,
            scope_id: grant.scope_id,
            permissions,
            module_keys: grant.module_keys,
            module_access: grant.module_access,
          }] : [];
        });
        const existingScopes = new Set(currentGrants.map((grant) => (
          grantScopeValue(grant.scope_type, grant.scope_id, orgId)
        )));
        selectedScopes.forEach((scope) => {
          if (existingScopes.has(scope)) return;
          const node = nodeMap.get(scope);
          if (!node) throw new Error(`无法识别可见范围：${scope}`);
          next.push({
            scope_type: node.type as EnterpriseApplicationScope,
            scope_id: node.type === 'organization' ? null : node.id,
            permissions: ['view'],
          });
        });
        return await enterpriseApplications.replaceGrants(saved.id, next);
      } catch (error) {
        if (!editing && saved) await enterpriseApplications.delete(saved.id).catch(() => undefined);
        throw error;
      }
    },
    onSuccess: (saved) => {
      invalidate(); setAppModalOpen(false); setSelectedAppId(saved.id); message.success('企业应用已保存');
    },
    onError: (error) => message.error(errorText(error, '保存失败')),
  });
  const deleteApp = useMutation({
    mutationFn: (id: string) => enterpriseApplications.delete(id),
    onSuccess: () => { invalidate(); setDeleteTarget(null); message.success('企业应用已删除'); },
    onError: (error) => message.error(errorText(error, '删除失败')),
  });
  const updateApp = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<EnterpriseApplicationInput> }) =>
      enterpriseApplications.update(id, data),
    onSuccess: () => { invalidate(); message.success('配置已更新'); },
    onError: (error) => message.error(errorText(error, '更新失败')),
  });
  const testApp = useMutation({
    mutationFn: (id: string) => enterpriseApplications.test(id),
    onSuccess: (result) => {
      invalidate();
      result.status === 'healthy' ? message.success(`应用可访问（HTTP ${result.status_code ?? 'OK'}）`) : message.error(result.detail || '应用不可访问');
    },
    onError: (error) => message.error(errorText(error, '连接测试失败')),
  });

  const openCreate = () => {
    setEditing(null); appForm.resetFields();
    appForm.setFieldsValue({
      display_mode: 'embedded', sort_order: 0, is_active: true, assistant_enabled: true,
      visibility_mode: 'selected', visible_scopes: [],
    });
    setAppModalOpen(true);
  };
  const openEdit = (row: EnterpriseApplication) => {
    setEditing(row);
    const viewGrants = row.grants.filter((grant) => grant.permissions.includes('view'));
    const organizationVisible = viewGrants.some((grant) => grant.scope_type === 'organization');
    appForm.setFieldsValue({
      name: row.name, slug: row.slug, description: row.description, icon_url: row.icon_url,
      entry_url: row.entry_url, display_mode: row.display_mode, sort_order: row.sort_order,
      is_active: row.is_active, assistant_enabled: row.assistant_enabled,
      assistant_prompt: row.assistant_prompt,
      visibility_mode: organizationVisible ? 'organization' : 'selected',
      visible_scopes: organizationVisible ? [] : viewGrants.map((grant) => (
        grantScopeValue(grant.scope_type, grant.scope_id, orgId)
      )),
    });
    setAppModalOpen(true);
  };

  const saveGrant = useMutation({
    mutationFn: (values: {
      scope: string; permissions: EnterpriseApplicationPermission[]; module_keys?: string[];
      page_keys?: string[]; action_keys?: string[];
    }) => {
      if (!selectedApp) throw new Error('请先选择应用');
      const node = nodeMap.get(values.scope);
      if (!node) throw new Error('请选择授权范围');
      const moduleKeys = values.module_keys ?? [];
      const existingModuleAccess = grantIndex === null
        ? {}
        : (selectedApp.grants[grantIndex]?.module_access ?? {});
      const selectedPages = new Set(values.page_keys ?? []);
      const selectedActions = new Set(values.action_keys ?? []);
      const grant = {
        scope_type: node.type as EnterpriseApplicationScope,
        scope_id: node.type === 'organization' ? null : node.id,
        permissions: values.permissions,
        module_keys: moduleKeys,
        module_access: Object.fromEntries(moduleKeys.map((moduleKey) => {
          const module = selectedIntegration?.modules.find((item) => item.moduleKey === moduleKey);
          const moduleActions = new Set((module?.actions ?? []).map((item) => item.actionKey));
          const actionKeys = Array.from(selectedActions).filter((key) => moduleActions.has(key));
          const pageAccess = Object.fromEntries((module?.pages ?? [])
            .filter((page) => selectedPages.has(`${moduleKey}::${page.pageKey}`))
            .map((page) => [page.pageKey, {
              permissions: values.permissions,
              action_keys: page.actionKeys.filter((key) => selectedActions.has(key)),
            }]));
          return [moduleKey, {
            role: existingModuleAccess[moduleKey]?.role ?? 'member',
            permissions: values.permissions,
            action_keys: actionKeys,
            page_access: pageAccess,
          }];
        })),
      };
      const next = selectedApp.grants.map((item) => ({
        scope_type: item.scope_type, scope_id: item.scope_id, permissions: item.permissions,
        module_keys: item.module_keys,
        module_access: item.module_access,
      }));
      if (grantIndex === null) next.push(grant); else next[grantIndex] = grant;
      return enterpriseApplications.replaceGrants(selectedApp.id, next);
    },
    onSuccess: () => { invalidate(); setGrantModalOpen(false); message.success('应用权限已保存'); },
    onError: (error) => message.error(errorText(error, '权限保存失败')),
  });

  const removeGrant = (index: number) => {
    if (!selectedApp) return;
    const next = selectedApp.grants.filter((_, i) => i !== index).map((item) => ({
      scope_type: item.scope_type, scope_id: item.scope_id, permissions: item.permissions,
      module_keys: item.module_keys,
      module_access: item.module_access,
    }));
    enterpriseApplications.replaceGrants(selectedApp.id, next).then(() => {
      invalidate(); message.success('授权已移除');
    }).catch((error) => message.error(errorText(error, '移除失败')));
  };

  useEffect(() => {
    if (!selectedApp || section !== 'assistant') return;
    assistantForm.setFieldsValue({
      assistant_enabled: selectedApp.assistant_enabled,
      assistant_prompt: selectedApp.assistant_prompt,
    });
  }, [selectedApp, section, assistantForm]);

  const addBinding = useMutation({
    mutationFn: (value: { target_type: EnterpriseApplicationTarget; target_id: string; operation: EnterpriseApplicationOperation }) => {
      if (!selectedApp) throw new Error('请先选择应用');
      const existing = selectedApp.tool_bindings.map((item) => ({
        target_type: item.target_type, target_id: item.target_id,
        operation: item.operation, is_active: item.is_active,
      }));
      return enterpriseApplications.replaceToolBindings(selectedApp.id, [...existing, { ...value, is_active: true }]);
    },
    onSuccess: () => { invalidate(); bindingForm.resetFields(); message.success('工具绑定已添加'); },
    onError: (error) => message.error(errorText(error, '工具绑定失败，请确认资源属于当前企业')),
  });

  const removeBinding = (index: number) => {
    if (!selectedApp) return;
    const next = selectedApp.tool_bindings.filter((_, i) => i !== index).map((item) => ({
      target_type: item.target_type, target_id: item.target_id,
      operation: item.operation, is_active: item.is_active,
    }));
    enterpriseApplications.replaceToolBindings(selectedApp.id, next).then(() => {
      invalidate(); message.success('工具绑定已移除');
    }).catch((error) => message.error(errorText(error, '移除失败')));
  };

  const titles = {
    applications: ['应用管理', <AppstoreOutlined key="icon" />],
    navigation: ['导航配置', <SettingOutlined key="icon" />],
    permissions: ['应用权限', <SafetyCertificateOutlined key="icon" />],
    assistant: ['业务助手', <RobotOutlined key="icon" />],
  } as const;

  const renderApplications = () => (
    <Table dataSource={apps} rowKey="id" loading={isLoading} pagination={{ pageSize: 20 }} columns={[
      { title: '应用', dataIndex: 'name', width: 220, render: (name: string, row: EnterpriseApplication) => (
        <Space><AppstoreOutlined style={{ color: '#6366f1' }} /><div><Button type="link" style={{ padding: 0, height: 'auto', fontWeight: 600 }} onClick={() => navigate(`/enterprise-apps/${row.id}`)}>{name}</Button><div><Typography.Text type="secondary">{row.slug}</Typography.Text></div></div></Space>
      ) },
      { title: '入口地址', dataIndex: 'entry_url', ellipsis: true },
      { title: '展示', dataIndex: 'display_mode', width: 100, render: (value: string) => <Tag>{value === 'embedded' ? '平台内嵌' : '外部打开'}</Tag> },
      { title: '状态', width: 150, render: (_: unknown, row: EnterpriseApplication) => <Space><Tag color={row.is_active ? 'green' : 'default'}>{row.is_active ? '启用' : '停用'}</Tag><Tag>{row.health_status}</Tag></Space> },
      { title: '操作', width: 260, render: (_: unknown, row: EnterpriseApplication) => <Space>
        <Button size="small" type="primary" onClick={() => navigate(`/enterprise-apps/${row.id}`)}>管理</Button>
        <Button size="small" icon={<ThunderboltOutlined />} loading={testApp.isPending} onClick={() => testApp.mutate(row.id)}>测试</Button>
        <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(row)}>编辑</Button>
        <Button size="small" danger icon={<DeleteOutlined />} onClick={() => setDeleteTarget(row)}>删除</Button>
      </Space> },
    ]} />
  );

  const renderNavigation = () => (
    <>
      <Alert showIcon type="info" message="用户侧边栏只显示拥有 view 权限且已启用的应用；顺序越小越靠前。" style={{ marginBottom: 12 }} />
      <Table dataSource={apps} rowKey="id" loading={isLoading} pagination={false} columns={[
        { title: '模块名称', dataIndex: 'name' },
        { title: '嵌入方式', dataIndex: 'display_mode', width: 160, render: (value: EnterpriseApplication['display_mode'], row: EnterpriseApplication) => <Select value={value} style={{ width: 130 }} options={[{ value: 'embedded', label: '平台内嵌' }, { value: 'external', label: '外部打开' }]} onChange={(display_mode: EnterpriseApplication['display_mode']) => updateApp.mutate({ id: row.id, data: { display_mode } })} /> },
        { title: '排序', dataIndex: 'sort_order', width: 130, render: (value: number, row: EnterpriseApplication) => <InputNumber value={value} min={-10000} max={10000} onChange={(sort_order) => updateApp.mutate({ id: row.id, data: { sort_order: sort_order ?? 0 } })} /> },
        { title: '启用', dataIndex: 'is_active', width: 100, render: (value: boolean, row: EnterpriseApplication) => <Switch checked={value} onChange={(is_active) => updateApp.mutate({ id: row.id, data: { is_active } })} /> },
      ]} />
    </>
  );

  const renderPermissions = () => selectedApp ? (
    <>
      <Alert showIcon type="info" message="应用的基础可见范围可在“登记/编辑应用”中直接选择；这里用于进一步配置 AI 查询、新增、更新、删除和导出权限。" style={{ marginBottom: 12 }} />
      <Space style={{ marginBottom: 12 }}><Select style={{ width: 260 }} value={selectedApp.id} options={appOptions} onChange={setSelectedAppId} /><Button type="primary" icon={<PlusOutlined />} onClick={() => { setGrantIndex(null); grantForm.resetFields(); setGrantModalOpen(true); }}>新增授权</Button></Space>
      <Table dataSource={selectedApp.grants} rowKey="id" pagination={false} columns={[
        { title: '授权范围', render: (_: unknown, row) => <Space><Tag>{row.scope_type}</Tag>{scopeLabel(row.scope_type, row.scope_id)}</Space> },
        { title: '权限', dataIndex: 'permissions', render: (values: string[]) => <Space wrap>{values.map((value) => <Tag key={value} color={value === 'view' ? 'blue' : value.includes('delete') ? 'red' : 'purple'}>{PERMISSIONS.find((item) => item.value === value)?.label ?? value}</Tag>)}</Space> },
        { title: '可见子模块', dataIndex: 'module_keys', render: (values: string[]) => values?.length ? <Space wrap>{values.map((value) => <Tag key={value}>{value}</Tag>)}</Space> : <Tag color="blue">全部子模块</Tag> },
        { title: '操作', width: 150, render: (_: unknown, row, index) => <Space><Button size="small" onClick={() => {
          setGrantIndex(index);
          const moduleAccess = row.module_access ?? {};
          grantForm.setFieldsValue({
            scope: `${row.scope_type === 'organization' ? 'org' : row.scope_type === 'department' ? 'dept' : row.scope_type}:${row.scope_id ?? orgId}`,
            permissions: row.permissions,
            module_keys: row.module_keys ?? [],
            page_keys: Object.entries(moduleAccess).flatMap(([moduleKey, access]) => Object.keys(access.page_access ?? {}).map((pageKey) => `${moduleKey}::${pageKey}`)),
            action_keys: Array.from(new Set(Object.values(moduleAccess).flatMap((access) => access.action_keys ?? []))),
          });
          setGrantModalOpen(true);
        }}>编辑</Button><Button size="small" danger onClick={() => removeGrant(index)}>移除</Button></Space> },
      ]} />
    </>
  ) : <Empty description="请先创建企业应用" />;

  const renderAssistant = () => selectedApp ? (
    <div style={{ maxWidth: 1080 }}>
      <Space style={{ marginBottom: 16 }}><Select style={{ width: 260 }} value={selectedApp.id} options={appOptions} onChange={setSelectedAppId} /><Tag color="purple">业务小助手</Tag></Space>
      <Card title="助手配置" style={{ marginBottom: 16 }}>
        <Form form={assistantForm} layout="vertical" onFinish={(values) => updateApp.mutate({ id: selectedApp.id, data: values })}>
          <Form.Item name="assistant_enabled" label="在模块中启用业务小助手" valuePropName="checked"><Switch /></Form.Item>
          <Form.Item name="assistant_prompt" label="业务上下文提示词"><Input.TextArea rows={4} placeholder="例如：你是生产协同助手，只基于当前订单和本应用授权工具回答。" /></Form.Item>
          <Button type="primary" htmlType="submit">保存助手配置</Button>
        </Form>
      </Card>
      <Card title="工具绑定" extra={<Typography.Text type="secondary">绑定后，即使从个人助手调用也执行同一应用权限检查</Typography.Text>}>
        <Form form={bindingForm} layout="inline" onFinish={(values) => addBinding.mutate(values)} style={{ marginBottom: 16 }}>
          <Form.Item name="target_type" rules={[{ required: true }]}><Select placeholder="资源类型" style={{ width: 150 }} options={TARGET_OPTIONS} onChange={() => bindingForm.setFieldValue('target_id', undefined)} /></Form.Item>
          <Form.Item name="target_id" rules={[{ required: true }]}><Select showSearch optionFilterProp="label" placeholder={bindingTargetType ? '选择当前企业资源' : '请先选择资源类型'} disabled={!bindingTargetType} style={{ width: 330 }} options={bindingTargets.filter((item) => item.type === bindingTargetType).map((item) => ({ value: item.id, label: item.label }))} /></Form.Item>
          <Form.Item name="operation" rules={[{ required: true }]}><Select placeholder="操作" style={{ width: 120 }} options={OPERATION_OPTIONS} /></Form.Item>
          <Button type="primary" htmlType="submit" loading={addBinding.isPending}>添加绑定</Button>
        </Form>
        <Table dataSource={selectedApp.tool_bindings} rowKey="id" pagination={false} columns={[
          { title: '类型', dataIndex: 'target_type', render: (value: string) => TARGET_OPTIONS.find((item) => item.value === value)?.label ?? value },
          { title: '资源 UUID', dataIndex: 'target_id' },
          { title: '操作', dataIndex: 'operation', render: (value: string) => <Tag>{OPERATION_OPTIONS.find((item) => item.value === value)?.label ?? value}</Tag> },
          { title: '操作', width: 90, render: (_: unknown, __: unknown, index: number) => <Button size="small" danger onClick={() => removeBinding(index)}>移除</Button> },
        ]} />
      </Card>
    </div>
  ) : <Empty description="请先创建企业应用" />;

  return (
    <FinderShell>
      <TitleBar icon={titles[section][1]} title={titles[section][0]} titleExtra={<OrgSelect value={orgId} onChange={setOrgId} />} extra={section === 'applications' ? <Space>
        <Button icon={<LinkOutlined />} onClick={() => setOnboardingOpen(true)} disabled={!orgId}>接入模块系统</Button>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate} disabled={!orgId}>手动登记</Button>
      </Space> : undefined} />
      <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
        {section === 'applications' && renderApplications()}
        {section === 'navigation' && renderNavigation()}
        {section === 'permissions' && renderPermissions()}
        {section === 'assistant' && renderAssistant()}
      </div>

      <Modal title={editing ? '编辑企业应用' : '登记企业应用'} open={appModalOpen} onCancel={() => setAppModalOpen(false)} onOk={() => appForm.submit()} confirmLoading={saveApp.isPending} width={680} forceRender>
        <Form form={appForm} layout="vertical" onFinish={(values) => saveApp.mutate(values)} onValuesChange={(changed) => { if (!editing && changed.name && !appForm.getFieldValue('slug')) appForm.setFieldValue('slug', slugify(changed.name)); }}>
          <Space align="start" style={{ display: 'flex' }}><Form.Item name="name" label="显示名称" rules={[{ required: true }]} style={{ flex: 1 }}><Input placeholder="生产协同" /></Form.Item><Form.Item name="slug" label="模块标识" rules={[{ required: true }, { pattern: /^[a-z0-9]+(?:-[a-z0-9]+)*$/, message: '仅小写字母、数字和连字符' }]} style={{ flex: 1 }}><Input disabled={!!editing} placeholder="production-collaboration" /></Form.Item></Space>
          <Form.Item name="description" label="说明"><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="entry_url" label="独立项目入口 URL" rules={[{ required: true }, { type: 'url' }]}><Input prefix={<LinkOutlined />} placeholder="https://business.example.com" /></Form.Item>
          <Form.Item name="icon_url" label="图标 URL" rules={[{ type: 'url', warningOnly: true }]}><Input placeholder="https://.../icon.png" /></Form.Item>
          <Space align="start" style={{ display: 'flex' }}><Form.Item name="display_mode" label="打开方式" style={{ flex: 1 }}><Select options={[{ value: 'embedded', label: '平台内嵌（iframe）' }, { value: 'external', label: '外部打开' }]} /></Form.Item><Form.Item name="sort_order" label="导航排序" style={{ flex: 1 }}><InputNumber style={{ width: '100%' }} /></Form.Item></Space>
          <Card size="small" title="谁可以看到这个应用" style={{ marginBottom: 18 }}>
            <Form.Item name="visibility_mode" label="可见范围" rules={[{ required: true }]} style={{ marginBottom: 12 }}>
              <Select options={[
                { value: 'selected', label: '指定部门、团队或用户' },
                { value: 'organization', label: '全企业所有用户' },
              ]} />
            </Form.Item>
            <Form.Item noStyle shouldUpdate={(previous, current) => previous.visibility_mode !== current.visibility_mode}>
              {({ getFieldValue }) => getFieldValue('visibility_mode') === 'selected' ? (
                <Form.Item
                  name="visible_scopes"
                  label="选择可见对象"
                  extra="选择部门后，该部门用户登录时会直接在左侧看到此应用；更细的 AI CRUD 权限可在“应用权限”中配置。"
                  rules={[{
                    validator: (_, value: string[]) => value?.length
                      ? Promise.resolve()
                      : Promise.reject(new Error('请至少选择一个部门、团队或用户')),
                  }]}
                >
                  <TreeSelect
                    multiple
                    allowClear
                    treeData={orgTree}
                    treeDefaultExpandAll
                    showSearch
                    treeNodeFilterProp="title"
                    loading={treeLoading}
                    placeholder="例如：爱法贝 / 生产部"
                  />
                </Form.Item>
              ) : (
                <Alert showIcon type="warning" message="全企业用户都会在左侧看到这个应用。" />
              )}
            </Form.Item>
          </Card>
          <Space size={32}><Form.Item name="is_active" label="启用应用" valuePropName="checked"><Switch /></Form.Item><Form.Item name="assistant_enabled" label="业务小助手" valuePropName="checked"><Switch /></Form.Item></Space>
        </Form>
      </Modal>

      <Modal title={grantIndex === null ? '新增应用授权' : '编辑应用授权'} open={grantModalOpen} onCancel={() => setGrantModalOpen(false)} onOk={() => grantForm.submit()} confirmLoading={saveGrant.isPending} forceRender>
        <Form form={grantForm} layout="vertical" onFinish={(values) => saveGrant.mutate(values)}>
          <Form.Item name="scope" label="授权对象" rules={[{ required: true }]}><TreeSelect treeData={orgTree} treeDefaultExpandAll showSearch treeNodeFilterProp="title" loading={treeLoading} placeholder="选择全企业、部门、团队或用户" /></Form.Item>
          <Form.Item name="permissions" label="权限" rules={[{ required: true }]}><Checkbox.Group options={PERMISSIONS} /></Form.Item>
          <Form.Item name="module_keys" label="可见子模块" extra="不选择表示可访问整个应用；选择后，该授权对象只能进入这些子模块，业务小助手也执行同一限制。">
            <Checkbox.Group options={(selectedIntegration?.modules ?? []).map((item) => ({
              value: item.moduleKey, label: item.name || item.moduleKey,
            })).filter((item) => item.value)} />
          </Form.Item>
          <Form.Item name="page_keys" label="可见页面" extra="原生模块按页面授权；未勾选的页面不会进入该对象的导航和 AI 上下文。">
            <Checkbox.Group options={(selectedIntegration?.modules ?? []).flatMap((module) => (module.pages ?? []).map((page) => ({
              value: `${module.moduleKey}::${page.pageKey}`, label: `${module.name} / ${page.name}`,
            })))} />
          </Form.Item>
          <Form.Item name="action_keys" label="允许 AI 使用的操作" extra="这里只列 Manifest 已声明可供 AI 使用的操作；模块以后新增操作不会自动获得授权。">
            <Checkbox.Group options={(selectedIntegration?.modules ?? []).flatMap((module) => module.actions.filter((action) => action.aiEnabled).map((action) => ({
              value: action.actionKey, label: `${module.name} / ${action.name}${action.requiresConfirmation ? '（需确认）' : ''}`,
            })))} />
          </Form.Item>
          {!selectedIntegration?.modules.length && <Alert showIcon type="warning" message="尚未发现子模块" description="请先在应用详情的“系统联通”中保存连接并同步；当前留空即保持整个应用可见。" />}
        </Form>
      </Modal>

      <ConfirmModal open={!!deleteTarget} title="删除企业应用" desc={`确认删除“${deleteTarget?.name ?? ''}”？应用授权和工具绑定也会停用。`} okText="删除" okDanger loading={deleteApp.isPending} onCancel={() => setDeleteTarget(null)} onOk={() => { if (deleteTarget) deleteApp.mutate(deleteTarget.id); }} />
      {orgId && <EnterpriseApplicationOnboardingWizard
        open={onboardingOpen}
        orgId={orgId}
        nodeMap={nodeMap}
        onClose={() => setOnboardingOpen(false)}
        onComplete={(applicationId) => {
          setSelectedAppId(applicationId);
          invalidate();
        }}
      />}
    </FinderShell>
  );
}
