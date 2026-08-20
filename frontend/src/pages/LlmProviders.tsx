import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import {
  Button, Modal, Table, Tag, Form, Input, Select, InputNumber,
  Space, message, Descriptions, Switch, Row, Col, Tooltip, Alert, Typography,
} from 'antd';
import {
  PlusOutlined, DeleteOutlined, EditOutlined, CloudServerOutlined,
  BankOutlined, ApartmentOutlined, TeamOutlined, ApiOutlined, ThunderboltOutlined,
} from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { providers } from '../api/client';
import type { LlmProvider, ModelCapability, ModelDeploymentInput } from '../api/client';
import { ApiError } from '../api/client';
import { useOrgTree } from '../hooks/useOrgTree';
import OrgSelect from '../components/OrgSelect';
import {
  FinderShell, TitleBar, Sidebar, MacTree, Toolbar,
  FinderEmpty, type FinderTreeNode,
} from '../components/finder/primitives';
import ConfirmModal from '../components/finder/ConfirmModal';
import { WB, FS } from '../components/finder/theme';

const TYPE_LABELS: Record<string, string> = {
  anthropic: 'Anthropic',
  openai: 'OpenAI',
  azure_openai: 'Azure OpenAI',
  custom: '自定义',
};

const VENDOR_LABELS: Record<string, string> = {
  aliyun_bailian: '阿里云百炼',
  volcengine_ark: '火山方舟',
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  azure_openai: 'Azure OpenAI',
  custom: '自定义兼容服务',
};

const CAPABILITY_LABELS: Record<ModelCapability, string> = {
  chat: '聊天', vision: '视觉理解', embedding: 'Embedding', image_generation: '生图',
};

const ADAPTER_OPTIONS = [
  { value: 'openai_chat_completions', label: 'OpenAI Chat Completions' },
  { value: 'openai_responses', label: 'OpenAI Responses（方舟等）' },
  { value: 'anthropic_messages', label: 'Anthropic Messages' },
  { value: 'openai_embeddings', label: 'OpenAI Embeddings' },
  { value: 'openai_images', label: 'OpenAI Images' },
  { value: 'volcengine_images', label: '火山方舟图片生成' },
  { value: 'bailian_multimodal_generation', label: '百炼图片生成' },
];

const SCOPE_LABELS: Record<string, string> = {
  organization: '组织级',
  department: '部门级',
  team: '团队级',
};

const SCOPE_COLORS: Record<string, string> = {
  organization: 'blue',
  department: 'green',
  team: 'orange',
};

const NODE_ICON: Record<string, ReactNode> = {
  organization: <BankOutlined />,
  department: <ApartmentOutlined />,
  team: <TeamOutlined />,
};

interface RawTreeNode { value: string; title: string; key: string; children?: RawTreeNode[] }

/** 把 useOrgTree 全树裁剪为「选中组织子树」的 Finder 树，丢弃个人级叶子。 */
function buildFinderTree(
  treeData: RawTreeNode[], orgId: string | undefined,
  nodeMap: Map<string, { type: string; id: string; name: string }>,
): FinderTreeNode[] {
  if (!orgId || treeData.length === 0) return [];
  const orgNode = treeData.find((n) => n.value === `org:${orgId}`);
  if (!orgNode) return [];
  const build = (n: RawTreeNode): FinderTreeNode | null => {
    const info = nodeMap.get(n.value);
    if (!info || info.type === 'user') return null;
    const children = (n.children ?? []).map(build).filter(Boolean) as FinderTreeNode[];
    return {
      key: n.value,
      label: n.title,
      icon: NODE_ICON[info.type],
      pill: SCOPE_LABELS[info.type] ?? info.type,
      selectable: true,
      children: children.length ? children : undefined,
    };
  };
  const root = build(orgNode);
  return root ? [root] : [];
}

export default function LlmProviders() {
  const qc = useQueryClient();
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<LlmProvider | null>(null);
  const [selectedOrgId, setSelectedOrgId] = useState<string | undefined>();
  const [selectedNodeKey, setSelectedNodeKey] = useState<string | null>(null);
  const [form] = Form.useForm();
  const [modelForm] = Form.useForm();
  const [modelProvider, setModelProvider] = useState<LlmProvider | null>(null);
  const vendor = Form.useWatch('vendor', form) as string | undefined;
  const providerType = Form.useWatch('provider_type', form) as string | undefined;
  const [confirm, setConfirm] = useState<{ id: string; name: string } | null>(null);

  const { treeData, nodeMap, isLoading: treeLoading } = useOrgTree();
  const orgId = selectedOrgId;

  const finderTree = useMemo(
    () => buildFinderTree(treeData as unknown as RawTreeNode[], orgId, nodeMap as unknown as Map<string, { type: string; id: string; name: string }>),
    [treeData, nodeMap, orgId],
  );
  const selectedNode = selectedNodeKey ? nodeMap.get(selectedNodeKey) : undefined;

  const { data: providerList, isLoading } = useQuery({
    queryKey: ['providers', orgId],
    queryFn: () => orgId ? providers.list(orgId) : Promise.resolve([]),
    enabled: !!orgId,
  });

  // 选中节点精确 scope 过滤
  const scopedProviders: LlmProvider[] = useMemo(() => {
    const all = providerList ?? [];
    if (!selectedNode) return [];
    if (selectedNode.type === 'organization') return all.filter((p) => p.scope_type === 'organization');
    if (selectedNode.type === 'department') return all.filter((p) => p.department_id === selectedNode.id);
    if (selectedNode.type === 'team') return all.filter((p) => p.team_id === selectedNode.id);
    return [];
  }, [providerList, selectedNode]);

  const isEdit = !!editing;

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({
      vendor: 'aliyun_bailian', provider_type: 'openai', region: 'cn-beijing',
      access_mode: 'payg', priority: 0, weight: 1, timeout_seconds: 120, max_retries: 2,
      model_deployments: [{ adapter: 'openai_chat_completions', capabilities: ['chat'], routing_priority: 0 }],
    });
    setModalOpen(true);
  };

  const openEdit = (r: LlmProvider) => {
    setEditing(r);
    setModalOpen(true);
  };

  useEffect(() => {
    if (modalOpen && editing) {
      form.setFieldsValue({
        name: editing.name,
        vendor: editing.vendor,
        provider_type: editing.provider_type,
        region: editing.region,
        workspace_id: editing.workspace_id,
        base_url: editing.base_url,
        api_key: undefined,
        supported_models: editing.supported_models,
        priority: editing.priority,
        weight: editing.weight,
        timeout_seconds: editing.timeout_seconds,
        max_retries: editing.max_retries,
        is_active: editing.is_active,
      });
    }
  }, [modalOpen, editing, form]);

  const closeModal = () => {
    setModalOpen(false);
    setEditing(null);
    form.resetFields();
  };

  const createProvider = useMutation({
    mutationFn: (data: Record<string, unknown>) => {
      if (!selectedNode) {
        message.error('请先在左侧选择绑定节点');
        return Promise.reject(new Error('No node selected'));
      }
      const deployments = (data.model_deployments as ModelDeploymentInput[] | undefined) ?? [];
      const payload: Record<string, unknown> = {
        name: data.name,
        vendor: data.vendor,
        provider_type: data.provider_type,
        region: data.region,
        workspace_id: data.workspace_id,
        access_mode: 'payg',
        scope_type: selectedNode.type,
        base_url: data.base_url || undefined,
        api_key: data.api_key,
        supported_models: deployments.map((item) => item.model_id),
        model_deployments: deployments,
        priority: data.priority ?? 0,
        weight: data.weight ?? 1,
        timeout_seconds: data.timeout_seconds ?? 120,
        max_retries: data.max_retries ?? 2,
        config: {},
      };
      switch (selectedNode.type) {
        case 'organization':
          return providers.create(selectedNode.id, payload);
        case 'department':
          return providers.createForDept(selectedNode.id, { ...payload, organization_id: selectedNode.orgId });
        case 'team':
          return providers.createForTeam(selectedNode.id, { ...payload, organization_id: selectedNode.orgId });
        default:
          return Promise.reject(new Error(`Unknown scope type: ${selectedNode.type}`));
      }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['providers'] });
      qc.invalidateQueries({ queryKey: ['orgTree'] });
      closeModal();
      message.success('提供商注册成功');
    },
    onError: (err: unknown) => {
      const msg = err instanceof ApiError ? err.message : '注册失败，请检查输入';
      message.error(msg);
    },
  });

  const updateProvider = useMutation({
    mutationFn: (data: Record<string, unknown>) => {
      if (!editing) return Promise.reject(new Error('No provider'));
      const payload: Record<string, unknown> = { ...data };
      delete payload.vendor;
      delete payload.provider_type;
      delete payload.model_deployments;
      delete payload.supported_models;
      if (
        ['aliyun_bailian', 'volcengine_ark', 'openai', 'anthropic'].includes(editing.vendor)
        && payload.base_url === editing.base_url
      ) delete payload.base_url;
      // api_key 仅在填写时才提交，避免覆盖为空
      if (!payload.api_key) delete payload.api_key;
      return providers.update(editing.id, payload);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['providers'] });
      closeModal();
      message.success('提供商已更新');
    },
    onError: (err: unknown) => {
      const msg = err instanceof ApiError ? err.message : '更新失败，请检查输入';
      message.error(msg);
    },
  });

  const submit = (v: Record<string, unknown>) => {
    if (isEdit) updateProvider.mutate(v);
    else createProvider.mutate(v);
  };

  const deleteProvider = useMutation({
    mutationFn: (id: string) => providers.delete(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['providers'] }); message.success('提供商已删除'); },
    onError: () => { message.error('删除失败'); },
  });

  const testProvider = useMutation({
    mutationFn: (id: string) => providers.test(id),
    onSuccess: (result) => { message.success(result.detail); qc.invalidateQueries({ queryKey: ['providers'] }); },
    onError: (err: unknown) => message.error(err instanceof ApiError ? err.message : '连接测试失败'),
  });

  const createModel = useMutation({
    mutationFn: (data: ModelDeploymentInput) => {
      if (!modelProvider) return Promise.reject(new Error('No provider'));
      return providers.createModel(modelProvider.id, data);
    },
    onSuccess: () => {
      message.success('模型部署已添加，请执行真实能力测试后加入生产路由');
      qc.invalidateQueries({ queryKey: ['providers'] });
      setModelProvider(null);
      modelForm.resetFields();
    },
    onError: (err: unknown) => message.error(err instanceof ApiError ? err.message : '模型部署添加失败'),
  });

  const testModel = useMutation({
    mutationFn: ({ providerId, modelId, capability }: { providerId: string; modelId: string; capability: ModelCapability }) =>
      providers.testModel(providerId, modelId, capability),
    onSuccess: (result) => {
      message.success(`${CAPABILITY_LABELS[result.capability as ModelCapability]}：${result.detail}`);
      qc.invalidateQueries({ queryKey: ['providers'] });
    },
    onError: (err: unknown) => message.error(err instanceof ApiError ? err.message : '模型能力测试失败'),
  });

  const removeModel = useMutation({
    mutationFn: ({ providerId, modelId }: { providerId: string; modelId: string }) => providers.deleteModel(providerId, modelId),
    onSuccess: () => { message.success('模型部署已删除'); qc.invalidateQueries({ queryKey: ['providers'] }); },
    onError: () => message.error('模型部署删除失败'),
  });

  const createBtn = (
    <Tooltip title={!selectedNode ? '请先在左侧选择组织/部门/团队节点' : ''}>
      <Button type="primary" icon={<PlusOutlined />} disabled={!selectedNode} onClick={openCreate}>注册提供商</Button>
    </Tooltip>
  );

  return (
    <FinderShell>
      <TitleBar
        icon={<CloudServerOutlined />}
        title="模型提供商"
        titleExtra={<OrgSelect value={orgId} onChange={(v) => { setSelectedOrgId(v); setSelectedNodeKey(null); }} />}
        extra={createBtn}
      />

      <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
        <Sidebar header="组织架构">
          {finderTree.length === 0 ? (
            <div style={{ padding: '8px 12px', color: WB.textAux, fontSize: FS.aux }}>
              {orgId ? (treeLoading ? '加载中…' : '该组织下暂无部门/团队节点') : '请先选择组织'}
            </div>
          ) : (
            <MacTree nodes={finderTree} selectedKey={selectedNodeKey} onSelect={setSelectedNodeKey} />
          )}
        </Sidebar>

        <section style={{ flex: 8, minWidth: 0, display: 'flex', flexDirection: 'column', background: '#fff' }}>
          {!selectedNode ? (
            <FinderEmpty description="请从左侧选择组织 / 部门 / 团队节点" />
          ) : (
            <>
              <Toolbar
                left={
                  <Space size={8}>
                    <Tag color={SCOPE_COLORS[selectedNode.type]}>{SCOPE_LABELS[selectedNode.type]}</Tag>
                    <Typography.Text style={{ fontSize: FS.aux, color: WB.textAux }}>
                      绑定节点：{selectedNode.name}
                    </Typography.Text>
                  </Space>
                }
              />
              <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
                <Table
                  dataSource={scopedProviders}
                  rowKey="id"
                  loading={isLoading}
                  pagination={{ pageSize: 20 }}
                  scroll={{ x: 'max-content' }}
                  expandable={{
                    expandedRowRender: (r: LlmProvider) => (
                      <Space direction="vertical" style={{ width: '100%' }} size={12}>
                        <Descriptions column={4} size="small">
                          <Descriptions.Item label="地域">{r.region || '默认'}</Descriptions.Item>
                          <Descriptions.Item label="超时">{r.timeout_seconds}s</Descriptions.Item>
                          <Descriptions.Item label="Key">{r.api_key_masked} · v{r.api_key_version}</Descriptions.Item>
                          <Descriptions.Item label="健康状态">{r.health_status}</Descriptions.Item>
                        </Descriptions>
                        <Space>
                          <Button size="small" icon={<ApiOutlined />} loading={testProvider.isPending} onClick={() => testProvider.mutate(r.id)}>测试供应商连接</Button>
                          <Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => {
                            setModelProvider(r);
                            modelForm.setFieldsValue({ adapter: 'openai_chat_completions', capabilities: ['chat'], routing_priority: 0 });
                          }}>添加模型部署</Button>
                        </Space>
                        <Table
                          size="small"
                          pagination={false}
                          rowKey="id"
                          dataSource={r.model_deployments ?? []}
                          columns={[
                            { title: '模型ID', dataIndex: 'model_id' },
                            { title: '适配器', dataIndex: 'adapter', render: (value: string) => <Tag>{value}</Tag> },
                            { title: '能力', dataIndex: 'capabilities', render: (values: ModelCapability[]) => values.map((value) => <Tag color="blue" key={value}>{CAPABILITY_LABELS[value]}</Tag>) },
                            { title: '状态', dataIndex: 'verification_status', render: (value: string, model) => <Tooltip title={model.last_error}><Tag color={value === 'verified' || value === 'legacy' ? 'green' : value === 'failed' ? 'red' : 'gold'}>{value === 'verified' ? '真实已验证' : value === 'legacy' ? '旧配置兼容' : value === 'partially_verified' ? '部分能力已验证' : value === 'failed' ? '验证失败' : '待验证'}</Tag></Tooltip> },
                            {
                              title: '操作', render: (_value: unknown, model) => (
                                <Space wrap>
                                  {(model.capabilities as ModelCapability[]).map((capability) => (
                                    <Button key={capability} size="small" icon={<ThunderboltOutlined />} loading={testModel.isPending} onClick={() => testModel.mutate({ providerId: r.id, modelId: model.id, capability })}>
                                      测试{CAPABILITY_LABELS[capability]}
                                    </Button>
                                  ))}
                                  <Button size="small" danger icon={<DeleteOutlined />} loading={removeModel.isPending} onClick={() => removeModel.mutate({ providerId: r.id, modelId: model.id })}>删除</Button>
                                </Space>
                              ),
                            },
                          ]}
                        />
                      </Space>
                    ),
                  }}
                  columns={[
                    { title: '名称', dataIndex: 'name', width: 200 },
                    { title: '供应商', dataIndex: 'vendor', width: 140, render: (v: string) => <Tag color="blue">{VENDOR_LABELS[v] || v}</Tag> },
                    { title: '协议', dataIndex: 'provider_type', width: 120, render: (v: string) => <Tag>{TYPE_LABELS[v] || v}</Tag> },
                    { title: 'Base URL', dataIndex: 'base_url', ellipsis: true },
                    {
                      title: '支持模型', dataIndex: 'supported_models', width: 260,
                      render: (v: string[], r: LlmProvider) => v?.map((m) => {
                        const caps = (r.config?.model_capabilities as Record<string, { vision?: boolean }> | undefined)?.[m];
                        const imageModel = (r.config?.image_generation as Record<string, unknown> | undefined)?.model === m;
                        return <Tag key={m} color={imageModel ? 'magenta' : caps?.vision ? 'cyan' : undefined} style={{ marginBottom: 2 }}>
                          {m}{imageModel ? ' · 生图' : caps?.vision ? ' · 视觉' : ''}
                        </Tag>;
                      }),
                    },
                    {
                      title: '启用', dataIndex: 'is_active', width: 70,
                      render: (v: boolean) => <Tag color={v ? 'green' : 'red'}>{v ? '是' : '否'}</Tag>,
                    },
                    {
                      title: '操作', width: 180, fixed: 'right',
                      render: (_: unknown, r: LlmProvider) => (
                        <Space size="small">
                          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(r)}>编辑</Button>
                          <Button size="small" danger icon={<DeleteOutlined />} onClick={() => setConfirm({ id: r.id, name: r.name })}>删除</Button>
                        </Space>
                      ),
                    },
                  ]}
                />
              </div>
            </>
          )}
        </section>
      </div>

      {/* 注册 / 编辑 Modal */}
      <Modal
        title={isEdit ? '编辑模型提供商' : '注册模型提供商'}
        open={modalOpen}
        onCancel={closeModal}
        onOk={() => form.submit()}
        confirmLoading={createProvider.isPending || updateProvider.isPending}
        width={860}
      >
        <Form form={form} layout="vertical" onFinish={submit} onFinishFailed={() => message.warning('请检查表单必填项')}>
          {!isEdit && selectedNode && (
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
              message={
                <span>
                  绑定节点：
                  <Tag color={SCOPE_COLORS[selectedNode.type]} style={{ marginInlineStart: 8 }}>{SCOPE_LABELS[selectedNode.type]}</Tag>
                  {selectedNode.name}
                </span>
              }
              description="新提供商绑定到左栏选中节点；调用解析遵循 团队级 > 部门级 > 组织级 优先级且继承。"
            />
          )}
          <Form.Item name="name" label="提供商名称" rules={[{ required: true }]}>
            <Input placeholder="如：Anthropic Direct" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="vendor" label="供应商" rules={[{ required: true }]}>
                <Select disabled={isEdit} options={[
                  { value: 'aliyun_bailian', label: '阿里云百炼' },
                  { value: 'volcengine_ark', label: '火山方舟' },
                  { value: 'openai', label: 'OpenAI' },
                  { value: 'anthropic', label: 'Anthropic' },
                  { value: 'custom', label: '自定义兼容服务' },
                ]} onChange={(value) => {
                  if (value === 'anthropic') form.setFieldValue('provider_type', 'anthropic');
                  else form.setFieldValue('provider_type', 'openai');
                  if (value === 'aliyun_bailian' || value === 'volcengine_ark') form.setFieldValue('region', 'cn-beijing');
                }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="provider_type" label="默认通信协议" rules={[{ required: true }]}>
                <Select disabled={isEdit || vendor === 'openai' || vendor === 'anthropic' || vendor === 'volcengine_ark'} options={[
                  { value: 'openai', label: 'OpenAI 兼容协议' },
                  { value: 'anthropic', label: 'Anthropic Messages 协议' },
                  { value: 'azure_openai', label: 'Azure OpenAI' },
                ]} />
              </Form.Item>
            </Col>
          </Row>
          {(vendor === 'aliyun_bailian' || vendor === 'volcengine_ark') && (
            <Row gutter={16}>
              <Col span={12}>
                <Form.Item name="region" label="地域" rules={[{ required: true }]}>
                  <Select options={vendor === 'volcengine_ark' ? [
                    { value: 'cn-beijing', label: '北京' },
                  ] : [
                    { value: 'cn-beijing', label: '中国（北京）' },
                    { value: 'ap-southeast-1', label: '新加坡' },
                    { value: 'ap-northeast-1', label: '日本（东京）' },
                    { value: 'eu-central-1', label: '德国（法兰克福）' },
                  ]} />
                </Form.Item>
              </Col>
              {vendor === 'aliyun_bailian' && (
                <Col span={12}><Form.Item name="workspace_id" label="业务空间 ID" extra="生产建议填写；日本和德国地域必须填写"><Input /></Form.Item></Col>
              )}
            </Row>
          )}
          <Form.Item
            name="base_url"
            label="Base URL"
            rules={(vendor === 'custom' || vendor === 'azure_openai') ? [{ required: true }] : []}
            extra={(vendor === 'aliyun_bailian' || vendor === 'volcengine_ark' || vendor === 'openai' || vendor === 'anthropic') ? '可留空，由平台根据供应商、地域和协议自动生成' : undefined}
          >
            <Input placeholder="留空使用官方端点；自定义服务必须填写 https:// 地址" />
          </Form.Item>
          <Form.Item
            name="api_key"
            label="API Key"
            rules={isEdit ? [] : [{ required: true }]}
            extra={isEdit ? '留空则保持原 Key 不变' : undefined}
          >
            <Input.Password placeholder="sk-ant-..." />
          </Form.Item>
          <Alert
            type="info" showIcon style={{ marginBottom: 16 }}
            message="供应商账号与模型能力分开配置"
            description={vendor === 'aliyun_bailian'
              ? '请使用按量付费 API Key。Coding Plan / Token Plan 不适用于 SaaS 后端。Key、地域和 Base URL 必须属于同一地域。'
              : vendor === 'volcengine_ark'
                ? '聊天/视觉、Embedding 和图片生成需要按实际模型选择不同适配器；图片生成不会被当作聊天接口调用。'
                : '模型必须明确填写能力和适配器，平台不再根据模型名称猜测。'}
          />
          {!isEdit ? (
            <Form.List name="model_deployments" rules={[{ validator: async (_rule, value) => { if (!value?.length) throw new Error('至少配置一个模型部署'); } }]}>
              {(fields, { add, remove }, { errors }) => (
                <Space direction="vertical" style={{ width: '100%' }}>
                  {fields.map(({ key, name, ...rest }) => (
                    <div key={key} style={{ padding: 12, border: '1px solid #e5e7eb', borderRadius: 8 }}>
                      <Row gutter={12}>
                        <Col span={10}><Form.Item {...rest} name={[name, 'model_id']} label="供应商模型ID" rules={[{ required: true }]}><Input placeholder="例如 qwen-plus / ep-..." /></Form.Item></Col>
                        <Col span={10}><Form.Item {...rest} name={[name, 'adapter']} label="调用适配器" rules={[{ required: true }]}><Select options={ADAPTER_OPTIONS} /></Form.Item></Col>
                        <Col span={4}><Button danger style={{ marginTop: 30 }} onClick={() => remove(name)} disabled={fields.length === 1}>移除</Button></Col>
                      </Row>
                      <Row gutter={12}>
                        <Col span={12}><Form.Item {...rest} name={[name, 'capabilities']} label="能力" rules={[{ required: true }]}><Select mode="multiple" options={(Object.entries(CAPABILITY_LABELS) as [ModelCapability, string][]).map(([value, label]) => ({ value, label }))} /></Form.Item></Col>
                        <Col span={6}><Form.Item {...rest} name={[name, 'endpoint_path']} label="接口路径"><Input placeholder={providerType === 'anthropic' ? '/v1/messages' : '通常留空'} /></Form.Item></Col>
                        <Col span={6}><Form.Item {...rest} name={[name, 'embedding_dimensions']} label="向量维度"><InputNumber min={1} style={{ width: '100%' }} /></Form.Item></Col>
                      </Row>
                    </div>
                  ))}
                  <Button block icon={<PlusOutlined />} onClick={() => add({ adapter: 'openai_chat_completions', capabilities: ['chat'], routing_priority: 0 })}>增加模型部署</Button>
                  <Form.ErrorList errors={errors} />
                </Space>
              )}
            </Form.List>
          ) : (
            <Alert type="warning" showIcon style={{ marginBottom: 16 }} message="模型部署在列表展开区独立管理" description="编辑供应商只修改账号、地域、端点和密钥，不会覆盖已验证模型。" />
          )}
          <Row gutter={16}>
            <Col span={6}><Form.Item name="priority" label="优先级" initialValue={0}><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={6}><Form.Item name="weight" label="权重" initialValue={1}><InputNumber min={1} style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={6}><Form.Item name="timeout_seconds" label="超时(s)" initialValue={120}><InputNumber min={10} style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={6}><Form.Item name="max_retries" label="最大重试" initialValue={2}><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
          </Row>
          {isEdit && (
            <Form.Item name="is_active" label="启用" valuePropName="checked">
              <Switch checkedChildren="启用" unCheckedChildren="停用" />
            </Form.Item>
          )}
        </Form>
      </Modal>

      <Modal
        title={`添加模型部署${modelProvider ? ` · ${modelProvider.name}` : ''}`}
        open={!!modelProvider}
        onCancel={() => { setModelProvider(null); modelForm.resetFields(); }}
        onOk={() => modelForm.submit()}
        confirmLoading={createModel.isPending}
        width={680}
      >
        <Alert
          type="info" showIcon style={{ marginBottom: 16 }}
          message="保存后默认为“待验证”"
          description="只有真实能力测试通过后才进入新网关生产路由；旧 DeepSeek 不受影响。生图测试可能产生供应商费用。"
        />
        <Form form={modelForm} layout="vertical" onFinish={(values) => createModel.mutate(values as ModelDeploymentInput)}>
          <Row gutter={16}>
            <Col span={12}><Form.Item name="model_id" label="供应商模型ID" rules={[{ required: true }]}><Input /></Form.Item></Col>
            <Col span={12}><Form.Item name="display_name" label="显示名称"><Input /></Form.Item></Col>
          </Row>
          <Form.Item name="adapter" label="调用适配器" rules={[{ required: true }]}><Select options={ADAPTER_OPTIONS} /></Form.Item>
          <Form.Item name="capabilities" label="能力" rules={[{ required: true }]}>
            <Select mode="multiple" options={(Object.entries(CAPABILITY_LABELS) as [ModelCapability, string][]).map(([value, label]) => ({ value, label }))} />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}><Form.Item name="endpoint_path" label="能力接口路径"><Input placeholder="通常留空，图片生成可填写专用路径" /></Form.Item></Col>
            <Col span={6}><Form.Item name="embedding_dimensions" label="向量维度"><InputNumber min={1} style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={6}><Form.Item name="routing_priority" label="路由优先级"><InputNumber style={{ width: '100%' }} /></Form.Item></Col>
          </Row>
        </Form>
      </Modal>

      <ConfirmModal
        open={!!confirm}
        title={<>确定删除提供商「{confirm?.name}」？</>}
        okText="删除"
        loading={deleteProvider.isPending}
        onCancel={() => setConfirm(null)}
        onOk={() => { if (confirm) deleteProvider.mutate(confirm.id); setConfirm(null); }}
      />
    </FinderShell>
  );
}
