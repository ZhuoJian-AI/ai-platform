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
import {
  ApiError, connectors, dataInterfaces, enterpriseApplications, skillStore,
  type EnterpriseApplication,
  type EnterpriseApplicationInput, type EnterpriseApplicationOperation,
  type EnterpriseApplicationPermission, type EnterpriseApplicationScope,
  type EnterpriseApplicationTarget,
} from '../../api/client';
import OrgSelect from '../../components/OrgSelect';
import ConfirmModal from '../../components/finder/ConfirmModal';
import { FinderShell, TitleBar } from '../../components/finder/primitives';
import { useOrgTree } from '../../hooks/useOrgTree';

export type EnterpriseApplicationsSection = 'applications' | 'navigation' | 'permissions' | 'assistant';

const PERMISSIONS: Array<{ value: EnterpriseApplicationPermission; label: string }> = [
  { value: 'view', label: '可见' },
  { value: 'ai_query', label: 'AI 查询' },
  { value: 'ai_create', label: 'AI 新增' },
  { value: 'ai_update', label: 'AI 更新' },
  { value: 'ai_delete', label: 'AI 删除' },
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

export default function EnterpriseApplications({ section }: { section: EnterpriseApplicationsSection }) {
  const qc = useQueryClient();
  const [orgId, setOrgId] = useState<string>();
  const [editing, setEditing] = useState<EnterpriseApplication | null>(null);
  const [appModalOpen, setAppModalOpen] = useState(false);
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
  const selectedApp = apps.find((item) => item.id === selectedAppId) ?? apps[0];

  useEffect(() => {
    if (!selectedAppId && apps[0]) setSelectedAppId(apps[0].id);
    if (selectedAppId && apps.length && !apps.some((item) => item.id === selectedAppId)) {
      setSelectedAppId(apps[0]?.id);
    }
  }, [apps, selectedAppId]);

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
    mutationFn: (values: EnterpriseApplicationInput) => {
      if (!orgId) throw new Error('请先选择企业');
      return editing
        ? enterpriseApplications.update(editing.id, values)
        : enterpriseApplications.create(orgId, values);
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
    appForm.setFieldsValue({ display_mode: 'embedded', sort_order: 0, is_active: true, assistant_enabled: true });
    setAppModalOpen(true);
  };
  const openEdit = (row: EnterpriseApplication) => {
    setEditing(row);
    appForm.setFieldsValue({
      name: row.name, slug: row.slug, description: row.description, icon_url: row.icon_url,
      entry_url: row.entry_url, display_mode: row.display_mode, sort_order: row.sort_order,
      is_active: row.is_active, assistant_enabled: row.assistant_enabled,
      assistant_prompt: row.assistant_prompt,
    });
    setAppModalOpen(true);
  };

  const saveGrant = useMutation({
    mutationFn: (values: { scope: string; permissions: EnterpriseApplicationPermission[] }) => {
      if (!selectedApp) throw new Error('请先选择应用');
      const node = nodeMap.get(values.scope);
      if (!node) throw new Error('请选择授权范围');
      const grant = {
        scope_type: node.type as EnterpriseApplicationScope,
        scope_id: node.type === 'organization' ? null : node.id,
        permissions: values.permissions,
      };
      const next = selectedApp.grants.map((item) => ({
        scope_type: item.scope_type, scope_id: item.scope_id, permissions: item.permissions,
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
        <Space><AppstoreOutlined style={{ color: '#6366f1' }} /><div><div>{name}</div><Typography.Text type="secondary">{row.slug}</Typography.Text></div></Space>
      ) },
      { title: '入口地址', dataIndex: 'entry_url', ellipsis: true },
      { title: '展示', dataIndex: 'display_mode', width: 100, render: (value: string) => <Tag>{value === 'embedded' ? '平台内嵌' : '外部打开'}</Tag> },
      { title: '状态', width: 150, render: (_: unknown, row: EnterpriseApplication) => <Space><Tag color={row.is_active ? 'green' : 'default'}>{row.is_active ? '启用' : '停用'}</Tag><Tag>{row.health_status}</Tag></Space> },
      { title: '操作', width: 260, render: (_: unknown, row: EnterpriseApplication) => <Space>
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
      <Alert showIcon type="warning" message="新应用默认对所有人隐藏；只有包含“可见”权限的授权范围才能看到模块。AI 新增、更新、删除在后端分别校验。" style={{ marginBottom: 12 }} />
      <Space style={{ marginBottom: 12 }}><Select style={{ width: 260 }} value={selectedApp.id} options={appOptions} onChange={setSelectedAppId} /><Button type="primary" icon={<PlusOutlined />} onClick={() => { setGrantIndex(null); grantForm.resetFields(); setGrantModalOpen(true); }}>新增授权</Button></Space>
      <Table dataSource={selectedApp.grants} rowKey="id" pagination={false} columns={[
        { title: '授权范围', render: (_: unknown, row) => <Space><Tag>{row.scope_type}</Tag>{scopeLabel(row.scope_type, row.scope_id)}</Space> },
        { title: '权限', dataIndex: 'permissions', render: (values: string[]) => <Space wrap>{values.map((value) => <Tag key={value} color={value === 'view' ? 'blue' : value.includes('delete') ? 'red' : 'purple'}>{PERMISSIONS.find((item) => item.value === value)?.label ?? value}</Tag>)}</Space> },
        { title: '操作', width: 150, render: (_: unknown, row, index) => <Space><Button size="small" onClick={() => { setGrantIndex(index); grantForm.setFieldsValue({ scope: `${row.scope_type === 'organization' ? 'org' : row.scope_type === 'department' ? 'dept' : row.scope_type}:${row.scope_id ?? orgId}`, permissions: row.permissions }); setGrantModalOpen(true); }}>编辑</Button><Button size="small" danger onClick={() => removeGrant(index)}>移除</Button></Space> },
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
      <TitleBar icon={titles[section][1]} title={titles[section][0]} titleExtra={<OrgSelect value={orgId} onChange={setOrgId} />} extra={section === 'applications' ? <Button type="primary" icon={<PlusOutlined />} onClick={openCreate} disabled={!orgId}>登记应用</Button> : undefined} />
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
          <Space size={32}><Form.Item name="is_active" label="启用应用" valuePropName="checked"><Switch /></Form.Item><Form.Item name="assistant_enabled" label="业务小助手" valuePropName="checked"><Switch /></Form.Item></Space>
        </Form>
      </Modal>

      <Modal title={grantIndex === null ? '新增应用授权' : '编辑应用授权'} open={grantModalOpen} onCancel={() => setGrantModalOpen(false)} onOk={() => grantForm.submit()} confirmLoading={saveGrant.isPending} forceRender>
        <Form form={grantForm} layout="vertical" onFinish={(values) => saveGrant.mutate(values)}>
          <Form.Item name="scope" label="授权对象" rules={[{ required: true }]}><TreeSelect treeData={orgTree} treeDefaultExpandAll showSearch treeNodeFilterProp="title" loading={treeLoading} placeholder="选择全企业、部门、团队或用户" /></Form.Item>
          <Form.Item name="permissions" label="权限" rules={[{ required: true }]}><Checkbox.Group options={PERMISSIONS} /></Form.Item>
        </Form>
      </Modal>

      <ConfirmModal open={!!deleteTarget} title="删除企业应用" desc={`确认删除“${deleteTarget?.name ?? ''}”？应用授权和工具绑定也会停用。`} okText="删除" okDanger loading={deleteApp.isPending} onCancel={() => setDeleteTarget(null)} onOk={() => { if (deleteTarget) deleteApp.mutate(deleteTarget.id); }} />
    </FinderShell>
  );
}
