import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from 'react';
import { Form, Input, InputNumber, Select, Switch, Tag, Typography, message, Empty, Spin } from 'antd';
import {
  PlusOutlined, DeleteOutlined, EditOutlined, RobotOutlined,
  BankOutlined, ApartmentOutlined, TeamOutlined, UserOutlined, FolderOutlined,
  RightOutlined, SearchOutlined,
} from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  terminal, type Agent, type KbNode,
} from '../../api/client';
import { ApiError } from '../../api/client';
import { useUserAuth } from '../../context/UserAuthContext';
import ConfirmModal from '../../components/finder/ConfirmModal';

/** WorkBuddy 配色（与 KnowledgeBaseView / SkillManagerView 一致）。 */
const WB = {
  primary: '#6366F1', sidebar: '#F5F5F7', hover: '#ECECEF', border: '#E5E7EB',
  activeBg: '#E8EAFE', text: '#1d1d1f', textAux: '#86868b',
};
const WB_FONT = '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif';
const { TextArea } = Input;

const SCOPE_LABEL: Record<string, string> = {
  organization: '组织级', department: '部门级', team: '团队级', user: '个人级',
};
const SCOPE_ICON: Record<string, ReactNode> = {
  organization: <BankOutlined />, department: <ApartmentOutlined />, team: <TeamOutlined />, user: <UserOutlined />,
};

interface TreeNode {
  key: string;
  name: string;
  scope: string;
  scopeId: string | null;
  children?: TreeNode[];
}

/** 把后端单链 KbNode[] 组装成 组织→部门→团队→个人 嵌套树（每级至多一个）。 */
function buildTree(nodes: KbNode[]): TreeNode[] {
  let child: TreeNode | null = null;
  for (let i = nodes.length - 1; i >= 0; i--) {
    const n = nodes[i];
    const node: TreeNode = {
      key: `${n.scope_type}:${n.scope_id ?? ''}`,
      name: n.name, scope: n.scope_type, scopeId: n.scope_id,
      children: child ? [child] : undefined,
    };
    child = node;
  }
  return child ? [child] : [];
}

/** 终端「智能体」视图：用户级智能体管理（参照 SkillManagerView 自包含范式）。
 *  左栏：用户可见作用域单链（组织/部门/团队/个人）。
 *  中栏：选中 scope 下的智能体列表。
 *  右栏：选中智能体的编辑表单。
 *  权限：列表展示用户权限范围内可见的全部智能体；创建可在 个人/团队/部门 scope（不允许组织级）；
 *       修改/删除仅限「自己创建」（created_by === 当前用户），非自己创建的只读。 */
export default function AgentManagerView() {
  const qc = useQueryClient();
  const { user } = useUserAuth();
  const myId = user?.id ?? null;

  const [scope, setScope] = useState<{ type: string; id: string | null; name: string } | null>(null);
  const [keyword, setKeyword] = useState('');
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);
  const [createModal, setCreateModal] = useState(false);
  const [confirm, setConfirm] = useState<{ id: string; name: string } | null>(null);

  const [form] = Form.useForm();
  const [createForm] = Form.useForm();
  const [dirty, setDirty] = useState(false);

  // 左栏 scope 链（与知识库/技能同源）
  const { data: kbNodes, isLoading: nodesLoading } = useQuery({
    queryKey: ['kb-nodes'], queryFn: () => terminal.kbNodes(),
  });
  const treeData = useMemo(() => buildTree(kbNodes ?? []), [kbNodes]);

  // 默认选中个人节点
  useEffect(() => {
    if (scope || !kbNodes?.length) return;
    const userNode = kbNodes.find((n) => n.scope_type === 'user');
    if (userNode) setScope({ type: userNode.scope_type, id: userNode.scope_id, name: userNode.name });
  }, [kbNodes, scope]);

  // 中栏：选中 scope 下的智能体
  const { data: agents, isLoading: agentsLoading } = useQuery({
    queryKey: ['terminal-agents', scope?.type, scope?.id],
    queryFn: () => terminal.listAgents({ scope_type: scope!.type, scope_id: scope!.id }),
    enabled: !!scope,
  });

  // 智能体可绑定用户继承到的全部资源，而非只看当前树节点的直接资源。
  // 后端只返回已安装成功的 Skill，组织/部门/团队来源在选项中显式标注。
  const { data: resources } = useQuery({
    queryKey: ['terminal-resources'], queryFn: () => terminal.resources(),
  });

  const isOwner = (created_by: string | null) => !!myId && created_by === myId;

  // 选中 agent → 同步表单
  useEffect(() => {
    if (selectedAgent) {
      form.setFieldsValue({
        name: selectedAgent.name,
        description: selectedAgent.description ?? '',
        system_prompt: selectedAgent.system_prompt ?? '',
        rag_collection_ids: selectedAgent.rag_collection_ids ?? [],
        skill_ids: selectedAgent.skill_ids ?? [],
        temperature: selectedAgent.temperature ?? null,
        max_tokens: selectedAgent.max_tokens ?? null,
        is_active: selectedAgent.is_active,
      });
      setDirty(false);
    } else {
      form.resetFields();
    }
  }, [selectedAgent, form]);

  // 切 scope → 清选中
  useEffect(() => { setSelectedAgent(null); }, [scope?.type, scope?.id]);

  const save = useMutation({
    mutationFn: (v: Record<string, unknown>) => {
      if (!selectedAgent) return Promise.reject(new Error('no agent'));
      return terminal.updateAgent(selectedAgent.id, v);
    },
    onSuccess: (updated: Agent) => {
      qc.invalidateQueries({ queryKey: ['terminal-agents'] });
      setSelectedAgent(updated);
      setDirty(false);
      message.success('已保存');
    },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '保存失败'),
  });

  const create = useMutation({
    mutationFn: (v: Record<string, unknown>) => {
      if (!scope) return Promise.reject(new Error('no scope'));
      v.scope_type = scope.type;
      v.scope_id = scope.id;
      return terminal.createAgent(v);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['terminal-agents'] });
      setCreateModal(false);
      message.success('已创建');
    },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '创建失败'),
  });

  const del = useMutation({
    mutationFn: (id: string) => terminal.deleteAgent(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['terminal-agents'] });
      setSelectedAgent(null);
      message.success('已删除');
    },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '删除失败'),
  });

  const kw = keyword.trim().toLowerCase();
  const filtered = kw
    ? (agents ?? []).filter((a) => a.name.toLowerCase().includes(kw) || a.slug.toLowerCase().includes(kw))
    : (agents ?? []);
  const canCreate = !!scope && scope.type !== 'organization';

  const ragOptions = (resources?.rags ?? []).map((c) => ({ value: c.id, label: c.name }));
  const skillOptions = (resources?.skills ?? []).map((s) => ({
    value: s.id, label: `${s.name}（${SCOPE_LABEL[s.scope_type] ?? s.scope_type}）`,
  }));

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, fontFamily: WB_FONT, background: '#fff' }}>
      {/* 顶部标题栏 */}
      <div style={titleBarStyle}>
        <RobotOutlined style={{ color: WB.primary, fontSize: 16 }} />
        <span style={{ fontSize: 13, fontWeight: 600, color: WB.text }}>智能体</span>
        <Typography.Text style={{ fontSize: 12, color: WB.textAux }}>
          {scope ? `${scope.name} · ${SCOPE_LABEL[scope.type]}` : '选择左侧节点'}
        </Typography.Text>
      </div>

      {/* 三栏主体：树(2) / 列表(3) / 编辑(5) */}
      <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
        {/* 左栏：作用域树 */}
        <aside style={sidebarStyle}>
          <div style={sidebarHeaderStyle}>组织架构</div>
          {nodesLoading ? (
            <div style={{ padding: 16, textAlign: 'center' }}><Spin /></div>
          ) : treeData.length === 0 ? (
            <div style={{ padding: '8px 12px', color: WB.textAux, fontSize: 12 }}>暂无可访问的作用域</div>
          ) : (
            <MacTree
              nodes={treeData}
              selectedKey={scope ? `${scope.type}:${scope.id ?? ''}` : null}
              onSelect={(type, id, name) => setScope({ type, id, name })}
            />
          )}
        </aside>

        {/* 中栏：智能体列表 */}
        <section style={{ flex: 3, minWidth: 0, display: 'flex', flexDirection: 'column', borderRight: `1px solid ${WB.border}`, background: '#fbfbfd' }}>
          <div style={toolbarStyle}>
            <Input
              allowClear size="small" placeholder="搜索智能体"
              prefix={<SearchOutlined style={{ color: '#9ca3af' }} />}
              style={{ width: 180 }} value={keyword} onChange={(e) => setKeyword(e.target.value)}
            />
            <button
              style={{ ...toolBtnStyle, background: canCreate ? WB.primary : '#eef0f3', color: canCreate ? '#fff' : WB.textAux, border: 'none' }}
              disabled={!canCreate}
              title={canCreate ? '新建智能体' : '组织级不允许新建，请选择个人/团队/部门节点'}
              onClick={() => { createForm.resetFields(); setCreateModal(true); }}
            >
              <PlusOutlined style={{ fontSize: 13 }} /> 新建
            </button>
          </div>
          <div style={{ flex: 1, overflowY: 'auto', padding: '4px 0' }} className="wb-scroll-hide">
            {!scope ? (
              <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请从左侧选择作用域节点" />
              </div>
            ) : agentsLoading ? (
              <div style={{ textAlign: 'center', padding: 32 }}><Spin /></div>
            ) : filtered.length === 0 ? (
              <PaneEmpty text={kw ? '无匹配智能体' : '该作用域下暂无智能体，点「新建」创建'} />
            ) : (
              filtered.map((r) => {
                const active = selectedAgent?.id === r.id;
                const owner = isOwner(r.created_by);
                return (
                  <div
                    key={r.id}
                    onClick={() => setSelectedAgent(r)}
                    onMouseEnter={(e) => { if (!active) e.currentTarget.style.background = WB.hover; }}
                    onMouseLeave={(e) => { if (!active) e.currentTarget.style.background = 'transparent'; }}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 8, padding: '7px 12px', margin: '1px 6px', borderRadius: 6,
                      cursor: 'pointer', fontSize: 13, lineHeight: 1,
                      background: active ? WB.activeBg : 'transparent',
                      color: active ? WB.primary : WB.text, fontWeight: active ? 600 : 400,
                    }}
                  >
                    <RobotOutlined style={{ fontSize: 15, color: active ? WB.primary : '#722ed1', flex: '0 0 auto' }} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.name}</span>
                        {owner && <span style={minePillStyle}>我创建</span>}
                      </div>
                      <div style={{ fontSize: 11, color: WB.textAux, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.slug} · {r.model_alias}</div>
                    </div>
                    {!r.is_active && <Tag color="red" style={{ marginInlineEnd: 0, fontSize: 10, lineHeight: '16px', padding: '0 4px' }}>停用</Tag>}
                  </div>
                );
              })
            )}
          </div>
        </section>

        {/* 右栏：智能体配置 */}
        <section style={{ flex: 5, minWidth: 0, display: 'flex', flexDirection: 'column', background: '#fff' }}>
          <div style={{ ...toolbarStyle, justifyContent: 'space-between' }}>
            <Typography.Text style={{ fontSize: 12, color: WB.textAux }}>
              {selectedAgent ? `${selectedAgent.name} · ${SCOPE_LABEL[selectedAgent.scope_type]}` : '智能体配置'}
            </Typography.Text>
            {selectedAgent && (
              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  style={{ ...toolBtnStyle, color: '#ff3b30' }}
                  disabled={!isOwner(selectedAgent.created_by) || del.isPending}
                  title={isOwner(selectedAgent.created_by) ? '删除' : '仅可删除自己创建的'}
                  onClick={() => setConfirm({ id: selectedAgent.id, name: selectedAgent.name })}
                >
                  <DeleteOutlined style={{ fontSize: 13 }} /> 删除
                </button>
                <button
                  style={{ ...toolBtnStyle, background: WB.primary, color: '#fff', border: 'none' }}
                  disabled={!isOwner(selectedAgent.created_by) || !dirty || save.isPending}
                  title={isOwner(selectedAgent.created_by) ? '保存' : '仅可修改自己创建的'}
                  onClick={() => form.submit()}
                >
                  <EditOutlined style={{ fontSize: 13 }} /> 保存
                </button>
              </div>
            )}
          </div>
          <div style={{ flex: 1, overflowY: 'auto', padding: 16 }} className="wb-scroll-hide">
            {!selectedAgent ? (
              <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请从中栏选择智能体" />
              </div>
            ) : (
              <>
                {!isOwner(selectedAgent.created_by) && (
                  <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 12, fontSize: 12 }}>
                    该智能体非你创建，仅可查看，不可修改/删除。
                  </Typography.Text>
                )}
                <Form
                  form={form} layout="vertical" disabled={!isOwner(selectedAgent.created_by)}
                  onValuesChange={() => setDirty(true)}
                  onFinish={(v) => save.mutate(v)}
                  initialValues={{ is_active: true }}
                >
                  <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item>
                  <Form.Item name="description" label="描述"><Input /></Form.Item>
                  <Form.Item name="system_prompt" label="系统提示词" rules={[{ required: true }]}>
                    <TextArea rows={10} style={{ fontFamily: 'monospace' }} />
                  </Form.Item>
                  <Form.Item name="rag_collection_ids" label="绑定 RAG 集合（可多选，仅此智能体使用）">
                    <Select mode="multiple" allowClear showSearch placeholder="无" optionFilterProp="label" options={ragOptions} />
                  </Form.Item>
                  <Form.Item name="skill_ids" label="绑定技能（可多选，仅此智能体可调用）">
                    <Select mode="multiple" allowClear showSearch placeholder="无" optionFilterProp="label" options={skillOptions} />
                  </Form.Item>
                  <Typography.Text type="secondary" style={{ display: 'block', marginTop: -16, marginBottom: 16, fontSize: 12 }}>
                    未绑定的技能不会暴露给模型，自动调用和 /command 都不可使用。
                  </Typography.Text>
                  <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
                    <Form.Item name="temperature" label="Temperature"><InputNumber min={0} max={2} step={0.1} /></Form.Item>
                    <Form.Item name="max_tokens" label="Max Tokens"><InputNumber min={1} /></Form.Item>
                    <Form.Item name="is_active" label="启用" valuePropName="checked"><Switch /></Form.Item>
                  </div>
                </Form>
              </>
            )}
          </div>
        </section>
      </div>

      {/* 新建智能体 */}
      {createModal && (
        <CreateModal
          loading={create.isPending}
          scopeLabel={scope ? `${scope.name} · ${SCOPE_LABEL[scope.type]}` : '—'}
          onCancel={() => setCreateModal(false)}
          onSubmit={() => createForm.submit()}
        >
          <Form
            form={createForm} layout="vertical"
            onFinish={(v) => create.mutate(v)}
            initialValues={{ is_active: true, system_prompt: '', rag_collection_ids: [], skill_ids: [] }}
          >
            <Form.Item name="name" label="名称" rules={[{ required: true }]}>
              <Input placeholder="智能体名称" />
            </Form.Item>
            <Form.Item name="description" label="描述"><Input /></Form.Item>
            <Form.Item name="system_prompt" label="系统提示词" rules={[{ required: true }]}>
              <TextArea rows={6} style={{ fontFamily: 'monospace' }} />
            </Form.Item>
            <Form.Item name="rag_collection_ids" label="绑定 RAG 集合（可多选）">
              <Select mode="multiple" allowClear showSearch placeholder="无" optionFilterProp="label" options={ragOptions} />
            </Form.Item>
            <Form.Item name="skill_ids" label="绑定技能（可多选）">
              <Select mode="multiple" allowClear showSearch placeholder="无" optionFilterProp="label" options={skillOptions} />
            </Form.Item>
          </Form>
        </CreateModal>
      )}

      {/* 删除确认 */}
      <ConfirmModal
        open={!!confirm}
        title={<>确定删除智能体「{confirm?.name}」？</>}
        desc="将软删除该智能体，此操作不可撤销。"
        okText="删除"
        loading={del.isPending}
        onCancel={() => setConfirm(null)}
        onOk={() => { if (confirm) del.mutate(confirm.id); setConfirm(null); }}
      />
    </div>
  );
}

// ── 新建弹窗（MacOS 风格，包裹 antd Form） ───────────────────────────────

function CreateModal(props: {
  loading: boolean;
  scopeLabel: string;
  onCancel: () => void;
  onSubmit: () => void;
  children: ReactNode;
}) {
  const { loading, scopeLabel, onCancel, onSubmit, children } = props;
  return (
    <div style={modalOverlayStyle} onClick={onCancel}>
      <div style={{ ...modalCardStyle, width: 720 }} onClick={(e) => e.stopPropagation()}>
        <div style={{ padding: '14px 18px', fontSize: 13, fontWeight: 600, color: WB.text, borderBottom: `1px solid ${WB.border}` }}>
          新建智能体
        </div>
        <div style={{ padding: 18, maxHeight: '70vh', overflowY: 'auto' }}>
          <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 12, fontSize: 12 }}>
            作用域：{scopeLabel}（不允许组织级；slug 由系统按名称自动生成，新建后可在右栏修改配置）
          </Typography.Text>
          {children}
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, padding: '0 18px 16px' }}>
          <button style={toolBtnStyle} onClick={onCancel}>取消</button>
          <button
            style={{ ...toolBtnStyle, background: WB.primary, color: '#fff', border: 'none' }}
            disabled={loading} onClick={onSubmit}
          >
            {loading ? '创建中…' : '创建'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── MacOS 风格作用域树 ──────────────────────────────────────────────────

function MacTree({ nodes, selectedKey, onSelect }: {
  nodes: TreeNode[];
  selectedKey: string | null;
  onSelect: (type: string, id: string | null, name: string) => void;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(nodes.map((n) => n.key)));
  const toggle = (key: string) => setExpanded((s) => {
    const next = new Set(s);
    if (next.has(key)) next.delete(key); else next.add(key);
    return next;
  });
  const renderNode = (node: TreeNode, level: number): ReactNode => {
    const hasChildren = !!node.children?.length;
    const isOpen = expanded.has(node.key);
    const active = selectedKey === node.key;
    return (
      <div key={node.key}>
        <div
          onClick={() => onSelect(node.scope, node.scopeId, node.name)}
          onMouseEnter={(e) => { if (!active) e.currentTarget.style.background = WB.hover; }}
          onMouseLeave={(e) => { if (!active) e.currentTarget.style.background = 'transparent'; }}
          style={treeRowStyle(active, level)}
        >
          <span style={{ width: 12, display: 'inline-flex', justifyContent: 'center', flex: '0 0 12px' }}>
            {hasChildren && (
              <RightOutlined
                onClick={(e) => { e.stopPropagation(); toggle(node.key); }}
                style={{ fontSize: 9, color: WB.textAux, cursor: 'pointer', transform: isOpen ? 'rotate(90deg)' : 'none', transition: 'transform .15s' }}
              />
            )}
          </span>
          <span style={{ fontSize: 14, color: active ? WB.primary : WB.textAux, flex: '0 0 auto' }}>{SCOPE_ICON[node.scope] ?? <FolderOutlined />}</span>
          <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: active ? WB.primary : WB.text, fontWeight: active ? 600 : 400 }}>{node.name}</span>
          <span style={scopePillStyle}>{SCOPE_LABEL[node.scope]}</span>
        </div>
        {hasChildren && isOpen && node.children!.map((c) => renderNode(c, level + 1))}
      </div>
    );
  };
  return <div style={{ padding: '2px 0' }}>{nodes.map((n) => renderNode(n, 0))}</div>;
}

function PaneEmpty({ text }: { text: string }) {
  return <div style={{ textAlign: 'center', color: WB.textAux, fontSize: 13, marginTop: 32 }}>{text}</div>;
}

// ── 共享样式 ─────────────────────────────────────────────────────────────

const titleBarStyle: CSSProperties = {
  height: 44, display: 'flex', alignItems: 'center', padding: '0 16px', gap: 8,
  borderBottom: `1px solid ${WB.border}`, flex: '0 0 auto', background: '#fbfbfd',
};

const sidebarStyle: CSSProperties = {
  flex: 2, minWidth: 188, maxWidth: 264, background: WB.sidebar,
  borderRight: `1px solid ${WB.border}`, overflowY: 'auto', padding: '8px 0',
};

const sidebarHeaderStyle: CSSProperties = {
  fontSize: 11, fontWeight: 600, color: WB.textAux, letterSpacing: 0.4,
  textTransform: 'uppercase', padding: '6px 14px 4px',
};

const treeRowStyle = (active: boolean, level: number): CSSProperties => ({
  display: 'flex', alignItems: 'center', gap: 6, height: 30,
  margin: '1px 6px', padding: '0 8px', borderRadius: 6, cursor: 'pointer',
  fontSize: 13, lineHeight: 1, userSelect: 'none',
  paddingLeft: 8 + level * 16,
  background: active ? WB.activeBg : 'transparent',
  color: active ? WB.primary : WB.text,
  fontWeight: active ? 600 : 400,
});

const scopePillStyle: CSSProperties = {
  fontSize: 10, color: WB.textAux, background: 'rgba(0,0,0,0.06)',
  padding: '1px 6px', borderRadius: 8, flex: '0 0 auto', lineHeight: '14px',
};

const toolbarStyle: CSSProperties = {
  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
  padding: '10px 16px', borderBottom: `1px solid ${WB.border}`, flex: '0 0 auto', gap: 8, flexWrap: 'wrap',
  background: '#fbfbfd',
};

const minePillStyle: CSSProperties = {
  fontSize: 10, color: WB.primary, background: `${WB.primary}1A`,
  padding: '1px 6px', borderRadius: 8, flex: '0 0 auto', lineHeight: '14px',
};

const toolBtnStyle: CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12, color: WB.text,
  background: '#eef0f3', border: 'none', cursor: 'pointer', padding: '5px 10px', borderRadius: 6, height: 28,
};

const modalOverlayStyle: CSSProperties = {
  position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.3)', zIndex: 1000,
  display: 'flex', alignItems: 'center', justifyContent: 'center',
};

const modalCardStyle: CSSProperties = {
  maxWidth: 'calc(100vw - 32px)', background: '#fff', borderRadius: 12,
  boxShadow: '0 12px 32px rgba(0,0,0,0.18)', overflow: 'hidden',
};
