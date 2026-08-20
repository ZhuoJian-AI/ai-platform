import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import {
  Button, Modal, Table, Tag, Form, Input, Select, InputNumber,
  Space, message, Descriptions, Switch, Row, Col, Tooltip, Alert, Typography,
} from 'antd';
import {
  PlusOutlined, DeleteOutlined, EditOutlined, CloudServerOutlined,
  BankOutlined, ApartmentOutlined, TeamOutlined,
} from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { providers } from '../api/client';
import type { LlmProvider } from '../api/client';
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
  const supportedModels = Form.useWatch('supported_models', form) as string[] | undefined;
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
        provider_type: editing.provider_type,
        base_url: editing.base_url,
        api_key: undefined,
        supported_models: editing.supported_models,
        priority: editing.priority,
        weight: editing.weight,
        timeout_seconds: editing.timeout_seconds,
        max_retries: editing.max_retries,
        is_active: editing.is_active,
        vision_models: Object.entries((editing.config?.model_capabilities as Record<string, { vision?: boolean }> | undefined) ?? {})
          .filter(([, capability]) => capability?.vision).map(([model]) => model),
        vision_fallback_model: (editing.config?.vision_fallback_model as string | null | undefined) ?? undefined,
        image_generation_enabled: Boolean((editing.config?.image_generation as Record<string, unknown> | undefined)?.enabled),
        image_generation_model: (editing.config?.image_generation as Record<string, unknown> | undefined)?.model,
        image_generation_endpoint: (editing.config?.image_generation as Record<string, unknown> | undefined)?.endpoint_path ?? '/images/generations',
        image_generation_size: (editing.config?.image_generation as Record<string, unknown> | undefined)?.default_size ?? '1024x1024',
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
      const payload: Record<string, unknown> = {
        name: data.name,
        provider_type: data.provider_type,
        scope_type: selectedNode.type,
        base_url: data.base_url,
        api_key: data.api_key,
        supported_models: data.supported_models ?? [],
        priority: data.priority ?? 0,
        weight: data.weight ?? 1,
        timeout_seconds: data.timeout_seconds ?? 120,
        max_retries: data.max_retries ?? 2,
        config: buildProviderConfig(data),
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
      payload.config = buildProviderConfig(data, editing.config);
      delete payload.vision_models;
      delete payload.vision_fallback_model;
      delete payload.image_generation_enabled;
      delete payload.image_generation_model;
      delete payload.image_generation_endpoint;
      delete payload.image_generation_size;
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

  function buildProviderConfig(data: Record<string, unknown>, existing: Record<string, unknown> = {}) {
    const visionModels = (data.vision_models as string[] | undefined) ?? [];
    const previousCapabilities = (existing.model_capabilities as Record<string, Record<string, unknown>> | undefined) ?? {};
    const modelCapabilities: Record<string, Record<string, unknown>> = {};
    for (const model of (data.supported_models as string[] | undefined) ?? supportedModels ?? []) {
      modelCapabilities[model] = { ...(previousCapabilities[model] ?? {}), vision: visionModels.includes(model) };
    }
    return {
      ...existing,
      model_capabilities: modelCapabilities,
      vision_fallback_model: (data.vision_fallback_model as string | undefined) || null,
      image_generation: {
        ...((existing.image_generation as Record<string, unknown> | undefined) ?? {}),
        enabled: Boolean(data.image_generation_enabled),
        model: (data.image_generation_model as string | undefined) || null,
        endpoint_path: (data.image_generation_endpoint as string | undefined) || '/images/generations',
        default_size: (data.image_generation_size as string | undefined) || '1024x1024',
      },
    };
  }

  const deleteProvider = useMutation({
    mutationFn: (id: string) => providers.delete(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['providers'] }); message.success('提供商已删除'); },
    onError: () => { message.error('删除失败'); },
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
                      <Descriptions column={3} size="small">
                        <Descriptions.Item label="超时时间">{r.timeout_seconds}s</Descriptions.Item>
                        <Descriptions.Item label="最大重试">{r.max_retries}</Descriptions.Item>
                        <Descriptions.Item label="权重">{r.weight}</Descriptions.Item>
                        <Descriptions.Item label="优先级">{r.priority}</Descriptions.Item>
                        <Descriptions.Item label="Key 版本">v{r.api_key_version}</Descriptions.Item>
                        <Descriptions.Item label="配置">{JSON.stringify(r.config)}</Descriptions.Item>
                      </Descriptions>
                    ),
                  }}
                  columns={[
                    { title: '名称', dataIndex: 'name', width: 200 },
                    { title: '类型', dataIndex: 'provider_type', width: 130, render: (v: string) => <Tag>{TYPE_LABELS[v] || v}</Tag> },
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
        width={640}
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
          <Form.Item name="provider_type" label="类型" rules={isEdit ? [] : [{ required: true }]}>
            <Select disabled={isEdit} options={[
              { value: 'anthropic', label: 'Anthropic' },
              { value: 'openai', label: 'OpenAI' },
              { value: 'azure_openai', label: 'Azure OpenAI' },
              { value: 'custom', label: '自定义' },
            ]} />
          </Form.Item>
          <Form.Item name="base_url" label="Base URL" rules={[{ required: true }]}>
            <Input placeholder="https://api.anthropic.com" />
          </Form.Item>
          <Form.Item
            name="api_key"
            label="API Key"
            rules={isEdit ? [] : [{ required: true }]}
            extra={isEdit ? '留空则保持原 Key 不变' : undefined}
          >
            <Input.Password placeholder="sk-ant-..." />
          </Form.Item>
          <Form.Item name="supported_models" label="支持的模型" rules={[{ required: true }]}>
            <Select mode="tags" placeholder="输入模型名称，如 claude-opus-4-8" />
          </Form.Item>
          <Alert
            type="info" showIcon style={{ marginBottom: 16 }}
            message="多模态能力（OpenAI 兼容协议）"
            description="视觉模型可直接读取图片；纯文本主模型会继承当前节点配置的视觉回退。生图模型只作为 Craft 工具，不会出现在用户主模型下拉框。"
          />
          <Form.Item name="vision_models" label="支持视觉输入的聊天模型">
            <Select mode="multiple" allowClear options={(supportedModels ?? []).map((model) => ({ value: model, label: model }))} />
          </Form.Item>
          <Form.Item name="vision_fallback_model" label="视觉回退模型">
            <Select allowClear showSearch options={(supportedModels ?? []).map((model) => ({ value: model, label: model }))} />
          </Form.Item>
          <Form.Item name="image_generation_enabled" label="启用专用生图模型" valuePropName="checked" initialValue={false}>
            <Switch checkedChildren="启用" unCheckedChildren="停用" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="image_generation_model" label="生图模型">
                <Select allowClear showSearch options={(supportedModels ?? []).map((model) => ({ value: model, label: model }))} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="image_generation_size" label="默认尺寸" initialValue="1024x1024">
                <Select options={['1024x1024', '1536x1024', '1024x1536', 'auto'].map((value) => ({ value, label: value }))} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="image_generation_endpoint" label="Images API 路径" initialValue="/images/generations">
            <Input placeholder="/images/generations" />
          </Form.Item>
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
