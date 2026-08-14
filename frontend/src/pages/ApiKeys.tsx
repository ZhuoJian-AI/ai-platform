import { useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import {
  Button, Modal, Table, Tag, Form, Input, Select, InputNumber,
  Typography, Space, message, Alert, DatePicker, Row, Col, Divider, Tooltip, Switch,
} from 'antd';
import {
  PlusOutlined, CopyOutlined, StopOutlined, BookOutlined, KeyOutlined,
  EyeInvisibleOutlined, EyeOutlined, BankOutlined, ApartmentOutlined, TeamOutlined,
  EditOutlined,
} from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import dayjs from 'dayjs';
import { apiKeys, config as configApi } from '../api/client';
import type { ApiKey } from '../api/client';
import { ApiError } from '../api/client';
import { useOrgTree } from '../hooks/useOrgTree';
import OrgSelect from '../components/OrgSelect';
import {
  FinderShell, TitleBar, Sidebar, MacTree, Toolbar,
  FinderEmpty, type FinderTreeNode,
} from '../components/finder/primitives';
import ConfirmModal from '../components/finder/ConfirmModal';
import { WB, FS } from '../components/finder/theme';

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

/** 接入指引常量 */
const INTEGRATION_GUIDE = [
  {
    label: 'OpenAI SDK / 兼容生态',
    desc: '适用于 OpenAI SDK、LangChain、LlamaIndex、Cursor 等',
    // OpenAI SDK 拼接方式: base_url + /chat/completions → 需要包含 /v1
    base_url_suffix: '/v1',
    example: `from openai import OpenAI\n\nclient = OpenAI(\n    base_url="<BASE_URL>/v1",       # SDK 会追加 /chat/completions\n    api_key="<YOUR_API_KEY>"\n)\n\nresponse = client.chat.completions.create(\n    model="glm-5.1",\n    messages=[{"role": "user", "content": "Hello!"}]\n)`,
  },
  {
    label: 'Anthropic SDK',
    desc: '适用于 Anthropic Python/TypeScript SDK 直连',
    // Anthropic SDK 拼接方式: base_url + /v1/messages → 不要包含 /v1
    base_url_suffix: '',
    example: `import anthropic\n\nclient = anthropic.Anthropic(\n    base_url="<BASE_URL>",         # SDK 会追加 /v1/messages\n    api_key="<YOUR_API_KEY>"\n)\n\nmessage = client.messages.create(\n    model="glm-5.1",\n    max_tokens=1024,\n    messages=[{"role": "user", "content": "Hello!"}]\n)`,
  },
];

/** useOrgTree 返回的原始树节点（结构最小契约）。 */
interface RawTreeNode {
  value: string;
  title: string;
  key: string;
  children?: RawTreeNode[];
}

/** 把 useOrgTree 的全树裁剪为「选中组织子树」的 Finder 树，丢弃个人级叶子。 */
function buildFinderTree(
  treeData: RawTreeNode[], orgId: string | undefined,
  nodeMap: Map<string, { type: string; id: string; name: string }>,
): FinderTreeNode[] {
  if (!orgId || treeData.length === 0) return [];
  const orgNode = treeData.find((n) => n.value === `org:${orgId}`);
  if (!orgNode) return [];

  const build = (n: RawTreeNode): FinderTreeNode | null => {
    const info = nodeMap.get(n.value);
    if (!info || info.type === 'user') return null; // 个人级 Key 不支持
    const children = (n.children ?? [])
      .map(build)
      .filter(Boolean) as FinderTreeNode[];
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

export default function ApiKeys() {
  const qc = useQueryClient();
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [guideModalOpen, setGuideModalOpen] = useState(false);
  const [selectedOrgId, setSelectedOrgId] = useState<string | undefined>();
  const [selectedNodeKey, setSelectedNodeKey] = useState<string | null>(null);
  const [form] = Form.useForm();
  const [editForm] = Form.useForm();
  const [editTarget, setEditTarget] = useState<ApiKey | null>(null);
  const [confirm, setConfirm] = useState<{ id: string; name: string } | null>(null);

  // 组织架构树（用于左侧浏览与绑定节点解析）
  const { treeData, nodeMap, isLoading: treeLoading } = useOrgTree();
  const orgId = selectedOrgId;

  // 左栏 Finder 树：仅选中组织的 org→dept→team 子树
  const finderTree = useMemo(
    () => buildFinderTree(treeData as unknown as RawTreeNode[], orgId, nodeMap as unknown as Map<string, { type: string; id: string; name: string }>),
    [treeData, nodeMap, orgId],
  );

  // 当前选中节点元信息
  const selectedNode = selectedNodeKey ? nodeMap.get(selectedNodeKey) : undefined;

  // 按当前选中组织拉取全部 Key（前端按节点精确 scope 过滤）
  const { data: keyList, isLoading } = useQuery({
    queryKey: ['apiKeys', orgId],
    queryFn: () => (orgId ? apiKeys.list(orgId) : Promise.resolve([])),
    enabled: !!orgId,
  });

  // 选中节点绑定的 Key（精确 scope：组织节点=组织级、部门节点=该部门、团队节点=该团队）
  const scopedKeys: ApiKey[] = useMemo(() => {
    const all = keyList ?? [];
    if (!selectedNode) return [];
    if (selectedNode.type === 'organization') return all.filter((k) => k.scope_type === 'organization');
    if (selectedNode.type === 'department') return all.filter((k) => k.department_id === selectedNode.id);
    if (selectedNode.type === 'team') return all.filter((k) => k.team_id === selectedNode.id);
    return [];
  }, [keyList, selectedNode]);

  const createKey = useMutation({
    mutationFn: (formData: Record<string, unknown>) => {
      if (!selectedNode) {
        message.error('请先在左侧选择绑定节点');
        return Promise.reject(new Error('No node selected'));
      }
      const payload: Record<string, unknown> = {
        key_name: formData.key_name,
        scope_type: selectedNode.type,
        allowed_models: formData.allowed_models ?? [],
        rate_limit_rpm: formData.rate_limit_rpm ?? null,
        rate_limit_tpm: formData.rate_limit_tpm ?? null,
        budget_cap_tokens: formData.budget_cap_tokens ?? null,
        expires_at: formData.expires_at ?? null,
      };

      switch (selectedNode.type) {
        case 'organization':
          return apiKeys.create(selectedNode.id, payload);
        case 'department':
          return apiKeys.createForDept(selectedNode.id, { ...payload, organization_id: selectedNode.orgId });
        case 'team':
          return apiKeys.createForTeam(selectedNode.id, { ...payload, organization_id: selectedNode.orgId });
        default:
          return Promise.reject(new Error(`Unknown scope type: ${selectedNode.type}`));
      }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['apiKeys'] });
      qc.invalidateQueries({ queryKey: ['orgTree'] });
      setCreateModalOpen(false);
      form.resetFields();
      message.success('API Key 创建成功');
    },
    onError: (err: unknown) => {
      const msg = err instanceof ApiError ? err.message : '创建失败，请检查输入';
      message.error(msg);
    },
  });

  const revokeKey = useMutation({
    mutationFn: (id: string) => apiKeys.revoke(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['apiKeys'] }); message.success('API Key 已撤销'); },
    onError: () => { message.error('撤销失败'); },
  });

  const updateKey = useMutation({
    mutationFn: (formData: Record<string, unknown>) => {
      if (!editTarget) return Promise.reject(new Error('No edit target'));
      const payload: Record<string, unknown> = {
        key_name: formData.key_name,
        allowed_models: formData.allowed_models ?? [],
        rate_limit_rpm: formData.rate_limit_rpm ?? null,
        rate_limit_tpm: formData.rate_limit_tpm ?? null,
        budget_cap_tokens: formData.budget_cap_tokens ?? null,
        expires_at: formData.expires_at ?? null,
        is_active: formData.is_active,
      };
      return apiKeys.update(editTarget.id, payload);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['apiKeys'] });
      setEditTarget(null);
      editForm.resetFields();
      message.success('API Key 已更新');
    },
    onError: (err: unknown) => {
      const msg = err instanceof ApiError ? err.message : '更新失败，请检查输入';
      message.error(msg);
    },
  });

  const openEdit = (r: ApiKey) => {
    setEditTarget(r);
    editForm.setFieldsValue({
      key_name: r.key_name,
      allowed_models: r.allowed_models,
      rate_limit_rpm: r.rate_limit_rpm,
      rate_limit_tpm: r.rate_limit_tpm,
      budget_cap_tokens: r.budget_cap_tokens,
      expires_at: r.expires_at ? dayjs(r.expires_at) : null,
      is_active: r.is_active,
    });
  };

  const copyText = (text: string, label = 'API Key') => {
    navigator.clipboard.writeText(text);
    message.success(`${label}已复制到剪贴板`);
  };

  /** 对外代理 Base URL：优先取后端环境变量配置，未配置时回退到当前站点 origin */
  const { data: publicConfig } = useQuery({
    queryKey: ['public-config'],
    queryFn: configApi.get,
    staleTime: 5 * 60 * 1000,
  });
  const baseUrl = publicConfig?.proxy_base_url
    || (typeof window !== 'undefined' ? `${window.location.protocol}//${window.location.host}` : '');

  // 创建按钮：未选节点时禁用并提示
  const createBtn = (
    <Tooltip title={!selectedNode ? '请先在左侧选择组织/部门/团队节点' : ''}>
      <Button
        type="primary"
        icon={<PlusOutlined />}
        disabled={!selectedNode}
        onClick={() => setCreateModalOpen(true)}
      >
        创建 API Key
      </Button>
    </Tooltip>
  );

  return (
    <FinderShell>
      <TitleBar
        icon={<KeyOutlined />}
        title="API Key 管理"
        titleExtra={
          <OrgSelect
            value={orgId}
            onChange={(v) => { setSelectedOrgId(v); setSelectedNodeKey(null); }}
          />
        }
        extra={
          <>
            <Button icon={<BookOutlined />} onClick={() => setGuideModalOpen(true)}>接入指引</Button>
            {createBtn}
          </>
        }
      />

      {/* 2:8 主体：左栏组织架构树 / 右栏节点绑定的 Key 管理 */}
      <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
        <Sidebar header="组织架构">
          {finderTree.length === 0 ? (
            <div style={{ padding: '8px 12px', color: WB.textAux, fontSize: FS.aux }}>
              {orgId ? (treeLoading ? '加载中…' : '该组织下暂无部门/团队节点') : '请先选择组织'}
            </div>
          ) : (
            <MacTree
              nodes={finderTree}
              selectedKey={selectedNodeKey}
              onSelect={setSelectedNodeKey}
            />
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
                  dataSource={scopedKeys}
                  rowKey="id"
                  loading={isLoading}
                  pagination={{ pageSize: 20 }}
                  columns={[
                    { title: '名称', dataIndex: 'key_name', width: 160 },
                    {
                      title: 'API Key', dataIndex: 'key_plain', width: 280,
                      render: (v: string) => (
                        !v ? (
                          <Typography.Text type="secondary" style={{ fontSize: 12 }}>历史 Key，无法查看</Typography.Text>
                        ) : (
                          <KeyCopyButton value={v} />
                        )
                      ),
                    },
                    {
                      title: '层级', dataIndex: 'scope_type', width: 80,
                      render: (v: string) => <Tag color={SCOPE_COLORS[v]}>{SCOPE_LABELS[v]}</Tag>,
                    },
                    {
                      title: '允许模型', dataIndex: 'allowed_models', width: 180,
                      render: (v: string[]) => v.length === 0
                        ? <Tag>全部</Tag>
                        : v.slice(0, 3).map((m) => <Tag key={m}>{m}</Tag>),
                    },
                    {
                      title: 'RPM', dataIndex: 'rate_limit_rpm', width: 60,
                      render: (v: number | null) => v ?? '继承',
                    },
                    {
                      title: '预算(token)', dataIndex: 'budget_cap_tokens', width: 90,
                      render: (v: number | null) => v ? v.toLocaleString() : '继承',
                    },
                    {
                      title: '状态', dataIndex: 'is_active', width: 70,
                      render: (v: boolean, r: ApiKey) =>
                        r.revoked_at ? <Tag color="red">已撤销</Tag>
                        : v ? <Tag color="green">活跃</Tag>
                        : <Tag color="default">停用</Tag>,
                    },
                    {
                      title: '过期时间', dataIndex: 'expires_at', width: 150,
                      render: (v: string | null) => v ? new Date(v).toLocaleString('zh-CN') : '永不过期',
                    },
                    {
                      title: '操作', width: 130, fixed: 'right', render: (_: unknown, r: ApiKey) =>
                        r.revoked_at ? null : (
                          <Space size={4}>
                            <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(r)}>编辑</Button>
                            {r.is_active && (
                              <Button size="small" danger icon={<StopOutlined />} onClick={() => setConfirm({ id: r.id, name: r.key_name })}>撤销</Button>
                            )}
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

      {/* 创建 Modal：绑定节点取自左栏选中节点（只读展示），不再内嵌 TreeSelect */}
      <Modal
        title="创建 API Key"
        open={createModalOpen}
        onCancel={() => setCreateModalOpen(false)}
        onOk={() => form.submit()}
        width={560}
      >
        <Form form={form} layout="vertical" onFinish={(v) => createKey.mutate(v)}>
          {selectedNode && (
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
              message={
                <span>
                  绑定节点：
                  <Tag color={SCOPE_COLORS[selectedNode.type]} style={{ marginInlineStart: 8 }}>
                    {SCOPE_LABELS[selectedNode.type]}
                  </Tag>
                  {selectedNode.name}
                </span>
              }
              description="新 Key 将绑定到左栏选中的节点，继承该节点及其上层的作用域与限额。"
            />
          )}
          <Form.Item name="key_name" label="Key 名称" rules={[{ required: true, message: '请输入 Key 名称' }]}>
            <Input placeholder="如：AI平台组-生产Key" />
          </Form.Item>
          <Form.Item name="allowed_models" label="允许的模型（空=全部）">
            <Select mode="tags" placeholder="输入模型名称，如 claude-opus-4-8" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item name="rate_limit_rpm" label="RPM 上限">
                <InputNumber min={1} style={{ width: '100%' }} placeholder="继承" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="rate_limit_tpm" label="TPM 上限">
                <InputNumber min={1} style={{ width: '100%' }} placeholder="继承" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="budget_cap_tokens" label="预算(token)">
                <InputNumber min={0} style={{ width: '100%' }} placeholder="继承" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="expires_at" label="过期时间">
            <DatePicker showTime style={{ width: '100%' }} placeholder="永不过期" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 编辑 Modal：绑定节点不可改（scope_type/department_id/team_id 只读） */}
      <Modal
        title="编辑 API Key"
        open={!!editTarget}
        onCancel={() => { setEditTarget(null); editForm.resetFields(); }}
        onOk={() => editForm.submit()}
        width={560}
      >
        {editTarget && (
          <Form form={editForm} layout="vertical" onFinish={(v) => updateKey.mutate(v)}>
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
              message={
                <span>
                  绑定节点：
                  <Tag color={SCOPE_COLORS[editTarget.scope_type]} style={{ marginInlineStart: 8 }}>
                    {SCOPE_LABELS[editTarget.scope_type]}
                  </Tag>
                  {editTarget.key_prefix}
                  <Typography.Text type="secondary" style={{ fontSize: 12, marginInlineStart: 8 }}>
                    （绑定后不可更改）
                  </Typography.Text>
                </span>
              }
            />
            <Form.Item name="key_name" label="Key 名称" rules={[{ required: true, message: '请输入 Key 名称' }]}>
              <Input placeholder="如：AI平台组-生产Key" />
            </Form.Item>
            <Form.Item name="allowed_models" label="允许的模型（空=全部）">
              <Select mode="tags" placeholder="输入模型名称，如 claude-opus-4-8" />
            </Form.Item>
            <Row gutter={16}>
              <Col span={8}>
                <Form.Item name="rate_limit_rpm" label="RPM 上限">
                  <InputNumber min={1} style={{ width: '100%' }} placeholder="继承" />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="rate_limit_tpm" label="TPM 上限">
                  <InputNumber min={1} style={{ width: '100%' }} placeholder="继承" />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="budget_cap_tokens" label="预算(token)">
                  <InputNumber min={0} style={{ width: '100%' }} placeholder="继承" />
                </Form.Item>
              </Col>
            </Row>
            <Form.Item name="expires_at" label="过期时间">
              <DatePicker showTime style={{ width: '100%' }} placeholder="永不过期" />
            </Form.Item>
            <Form.Item name="is_active" label="启用状态" valuePropName="checked">
              <Switch checkedChildren="启用" unCheckedChildren="停用" />
            </Form.Item>
          </Form>
        )}
      </Modal>

      {/* 接入指引 Modal */}
      <Modal
        title="接入指引"
        open={guideModalOpen}
        onCancel={() => setGuideModalOpen(false)}
        footer={null}
        width={720}
      >
        <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
          将下方地址配置到对应 SDK 的 <code>base_url</code> 即可接入，模型名称保持不变。
        </Typography.Paragraph>
        <Typography.Paragraph type="warning" style={{ marginBottom: 24, fontSize: 13 }}>
          ⚠️ 两套 SDK 对 base_url 的拼接规则不同：OpenAI SDK 自动追加路径，Anthropic SDK 自动追加 <code>/v1</code> + 路径，因此 base_url 写法不一样。
        </Typography.Paragraph>
        {!publicConfig?.proxy_base_url && (
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message="当前 base_url 取自浏览器地址（未在后端配置）"
            description={<>部署并测通后，请在后端 <code>.env</code> 中设置 <code>PROXY_BASE_URL</code>（如 https://api.example.com），重启服务后此处自动更新为对外真实地址。</>}
          />
        )}
        {INTEGRATION_GUIDE.map((item, idx) => (
          <div key={idx}>
            <Typography.Title level={5} style={{ marginTop: idx > 0 ? 20 : 0 }}>
              {item.label}
            </Typography.Title>
            <Typography.Text type="secondary">{item.desc}</Typography.Text>
            <div style={{ marginTop: 8 }}>
              <Typography.Text strong>base_url: </Typography.Text>
              <code style={{ fontSize: 13, background: '#f5f5f5', padding: '4px 8px', borderRadius: 4, userSelect: 'all' }}>
                {baseUrl}{item.base_url_suffix}
              </code>
              <CopyOutlined
                style={{ marginLeft: 8, color: WB.primary, cursor: 'pointer' }}
                onClick={() => copyText(`${baseUrl}${item.base_url_suffix}`, 'base_url')}
              />
            </div>
            <pre style={{
              background: '#1e1e1e', color: '#d4d4d4', padding: 12, borderRadius: 8,
              fontSize: 12, lineHeight: 1.6, marginTop: 8, overflow: 'auto',
            }}>
              {item.example.replace(/<BASE_URL>/g, baseUrl)}
            </pre>
            {idx < INTEGRATION_GUIDE.length - 1 && <Divider style={{ margin: '16px 0' }} />}
          </div>
        ))}
      </Modal>

      <ConfirmModal
        open={!!confirm}
        title={<>确定撤销 API Key「{confirm?.name}」？</>}
        desc="撤销后该 Key 立即失效，且无法恢复。"
        okText="撤销"
        loading={revokeKey.isPending}
        onCancel={() => setConfirm(null)}
        onOk={() => { if (confirm) revokeKey.mutate(confirm.id); setConfirm(null); }}
      />
    </FinderShell>
  );
}

/** API Key 显示/复制组件：默认掩码，点击眼睛可切换明文 */
function KeyCopyButton({ value }: { value: string }) {
  const [visible, setVisible] = useState(false);
  const display = visible ? value : (value.slice(0, 12) + '••••••••••••');
  return (
    <Space size={4}>
      <code style={{ fontSize: 12, userSelect: visible ? 'all' : 'none', letterSpacing: 0.3 }}>{display}</code>
      {visible ? (
        <EyeInvisibleOutlined style={{ color: WB.textAux, cursor: 'pointer' }} onClick={() => setVisible(false)} />
      ) : (
        <EyeOutlined style={{ color: WB.primary, cursor: 'pointer' }} onClick={() => setVisible(true)} />
      )}
      <CopyOutlined style={{ color: WB.primary, cursor: 'pointer' }} onClick={() => {
        navigator.clipboard.writeText(value);
        message.success('已复制完整 API Key');
      }} />
    </Space>
  );
}
