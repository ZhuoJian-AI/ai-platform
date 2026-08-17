import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import {
  Modal, Form, Input, InputNumber, Space, Select, Switch, Tag, Typography, message,
} from 'antd';
import {
  PlusOutlined, DeleteOutlined, EditOutlined, RobotOutlined,
  BankOutlined, ApartmentOutlined, TeamOutlined, UserOutlined, FolderOutlined,
} from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { agents, rag, skillStore } from '../../api/client';
import type { Agent, AgentScope } from '../../api/client';
import { ApiError } from '../../api/client';
import OrgSelect from '../../components/OrgSelect';
import { useOrgTree } from '../../hooks/useOrgTree';
import {
  FinderShell, TitleBar, Sidebar, MacTree, Toolbar, PathBar, ToolButton,
  FinderEmpty, FinderLoading, type FinderTreeNode,
} from '../../components/finder/primitives';
import ConfirmModal from '../../components/finder/ConfirmModal';
import { WB, FS } from '../../components/finder/theme';

const { TextArea } = Input;

interface ScopeState {
  scope_type: 'organization' | 'department' | 'team' | 'user';
  scope_id?: string | null;
  orgId: string;
  nodeName: string;
}

const SCOPE_PREFIX: Record<ScopeState['scope_type'], string> = {
  organization: 'org', department: 'dept', team: 'team', user: 'user',
};

const NODE_ICON: Record<string, ReactNode> = {
  org: <BankOutlined />, dept: <ApartmentOutlined />, team: <TeamOutlined />, user: <UserOutlined />,
};
const iconForKey = (key: string): ReactNode => NODE_ICON[key.split(':')[0]] ?? <FolderOutlined />;

const SCOPE_LABEL: Record<string, string> = {
  organization: '组织级', department: '部门级', team: '团队级', user: '个人级',
};

export default function Agents() {
  const qc = useQueryClient();
  const { treeData, nodeMap, isLoading: treeLoading } = useOrgTree();

  const [selectedOrgId, setSelectedOrgId] = useState<string | undefined>();
  const [scope, setScope] = useState<ScopeState | null>(null);
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);
  // 右栏编辑表单本地态（与 selectedAgent 同步；保存 = update）
  const [form] = Form.useForm();
  const [dirty, setDirty] = useState(false);
  // 新建弹窗
  const [createModal, setCreateModal] = useState(false);
  const [createForm] = Form.useForm();
  const [confirm, setConfirm] = useState<{ id: string; name: string } | null>(null);

  const orgId = scope?.orgId;

  // 仅展示当前选中组织的子树
  const treeDataScoped = useMemo(() => {
    if (!selectedOrgId) return [];
    return treeData.filter((n) => n.key === `org:${selectedOrgId}`);
  }, [treeData, selectedOrgId]);

  const finderTree = useMemo((): FinderTreeNode[] => {
    const build = (nodes: typeof treeData): FinderTreeNode[] =>
      nodes.map((n) => ({
        key: n.key,
        label: n.title,
        icon: iconForKey(n.key),
        children: n.children?.length ? build(n.children) : undefined,
      }));
    return build(treeDataScoped);
  }, [treeDataScoped]);

  const selectedKey = scope ? `${SCOPE_PREFIX[scope.scope_type]}:${scope.scope_id ?? scope.orgId}` : null;

  // 切换组织 → 默认选组织根节点
  useEffect(() => {
    if (!selectedOrgId || treeLoading) return;
    const info = nodeMap.get(`org:${selectedOrgId}`);
    if (!info) return;
    setSelectedAgent(null);
    setScope({ scope_type: 'organization', scope_id: null, orgId: info.orgId, nodeName: info.name });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedOrgId, treeLoading]);

  // 中栏：当前 scope 下的智能体
  const scopeArg: AgentScope | undefined = scope
    ? { scope_type: scope.scope_type, scope_id: scope.scope_id ?? null }
    : undefined;
  const { data: list, isLoading: listLoading } = useQuery({
    queryKey: ['agents', scope?.orgId, scope?.scope_type, scope?.scope_id],
    queryFn: () => agents.list(scope!.orgId, scopeArg),
    enabled: !!scope,
  });

  // 右栏绑定选项：只载入「所选节点 scope + 组织级」可见的 RAG / 技能
  // （组织级对全员可见；所选节点 scope 覆盖该节点下 agent 常绑的本级资源，使已选项能解析出名称）。
  type ScRef = { scope_type: 'organization' | 'department' | 'team' | 'user'; scope_id: string | null };
  const ORG_SCOPE: ScRef = { scope_type: 'organization', scope_id: null };
  const nodeScope: ScRef | null = scope
    ? { scope_type: scope.scope_type, scope_id: scope.scope_id ?? null }
    : null;
  const nodeIsOrg = !nodeScope || nodeScope.scope_type === 'organization';

  const { data: ragOrg } = useQuery({
    queryKey: ['admin-rag', orgId, 'organization'],
    queryFn: () => rag.listCollections(orgId!, ORG_SCOPE),
    enabled: !!orgId,
  });
  const { data: ragNode } = useQuery({
    queryKey: ['admin-rag', orgId, nodeScope?.scope_type, nodeScope?.scope_id],
    queryFn: () => rag.listCollections(orgId!, nodeScope!),
    enabled: !!orgId && !nodeIsOrg,
  });
  const ragList = useMemo(() => {
    const map = new Map<string, { id: string; name: string }>();
    for (const c of [...(ragOrg ?? []), ...(ragNode ?? [])]) map.set(c.id, { id: c.id, name: c.name });
    return [...map.values()];
  }, [ragOrg, ragNode]);

  const { data: skillOrg } = useQuery({
    queryKey: ['admin-skill-folders', orgId, 'organization'],
    queryFn: () => skillStore.listFolders(orgId!, ORG_SCOPE),
    enabled: !!orgId,
  });
  const { data: skillNode } = useQuery({
    queryKey: ['admin-skill-folders', orgId, nodeScope?.scope_type, nodeScope?.scope_id],
    queryFn: () => skillStore.listFolders(orgId!, nodeScope!),
    enabled: !!orgId && !nodeIsOrg,
  });
  const skillList = useMemo(() => {
    const map = new Map<string, { id: string; name: string; slug: string; scope_type: string }>();
    for (const s of [...(skillOrg ?? []), ...(skillNode ?? [])]) {
      if (!s.is_installed) continue;
      map.set(s.id, s);
    }
    return [...map.values()];
  }, [skillOrg, skillNode]);

  // 选中 agent → 同步表单
  useEffect(() => {
    if (selectedAgent) {
      form.setFieldsValue({
        ...selectedAgent,
        rag_collection_ids: selectedAgent.rag_collection_ids ?? [],
        skill_ids: selectedAgent.skill_ids ?? [],
      });
      setDirty(false);
    } else {
      form.resetFields();
    }
  }, [selectedAgent, form]);

  const save = useMutation({
    mutationFn: (v: Record<string, unknown>) => {
      if (!selectedAgent) return Promise.reject(new Error('no agent'));
      return agents.update(selectedAgent.id, v);
    },
    onSuccess: (updated: Agent) => {
      qc.invalidateQueries({ queryKey: ['agents'] });
      setSelectedAgent(updated);
      setDirty(false);
      message.success('已保存');
    },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '保存失败'),
  });

  const create = useMutation({
    mutationFn: (v: Record<string, unknown>) => {
      if (!scope) return Promise.reject(new Error('no scope'));
      v.scope_type = scope.scope_type;
      v.scope_id = scope.scope_id ?? null;
      return agents.create(scope.orgId, v);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['agents'] });
      setCreateModal(false);
      message.success('已创建');
    },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '创建失败'),
  });

  const del = useMutation({
    mutationFn: (id: string) => agents.delete(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['agents'] });
      setSelectedAgent(null);
      message.success('已删除');
    },
    onError: () => message.error('删除失败'),
  });

  const onSelectNode = (key: string) => {
    const info = nodeMap.get(key);
    if (!info) return;
    setSelectedAgent(null);
    setScope({
      scope_type: info.type,
      scope_id: info.type === 'organization' ? null : info.id,
      orgId: info.orgId,
      nodeName: info.name,
    });
  };

  return (
    <FinderShell style={{ height: 'calc(100vh - 64px)' }}>
      <TitleBar
        icon={<RobotOutlined />}
        title="智能体"
        titleExtra={<OrgSelect value={selectedOrgId} onChange={setSelectedOrgId} />}
        extra={scope && <Tag color="blue" style={{ marginInlineEnd: 0 }}>{scope.nodeName} · {SCOPE_LABEL[scope.scope_type]}</Tag>}
      />

      <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
        {/* 左栏：组织架构树 */}
        <Sidebar header="组织架构" style={{ flex: 2, maxWidth: 240 }}>
          {treeLoading ? <FinderLoading /> : finderTree.length === 0 ? (
            <div style={{ padding: '8px 12px', color: WB.textAux, fontSize: FS.aux }}>暂无组织架构</div>
          ) : (
            <MacTree nodes={finderTree} selectedKey={selectedKey} onSelect={onSelectNode} />
          )}
        </Sidebar>

        {/* 中栏：智能体列表 */}
        <section style={{ flex: 3, minWidth: 0, display: 'flex', flexDirection: 'column', borderRight: `1px solid ${WB.border}` }}>
          <Toolbar
            left={<span style={{ fontSize: FS.body, fontWeight: 600, color: WB.text }}>智能体</span>}
            right={<ToolButton primary icon={<PlusOutlined style={{ fontSize: 13 }} />} onClick={() => { createForm.resetFields(); setCreateModal(true); }} disabled={!scope}>新建</ToolButton>}
          />
          <div style={{ flex: 1, overflowY: 'auto', padding: '4px 0' }} className="wb-scroll-hide">
            {!scope ? (
              <FinderEmpty description="请从左侧选择节点" />
            ) : listLoading ? <FinderLoading /> : (list?.length === 0) ? (
              <div style={{ textAlign: 'center', color: WB.textAux, fontSize: FS.body, marginTop: 40 }}>该节点下暂无智能体</div>
            ) : (
              (list ?? []).map((r) => {
                const active = selectedAgent?.id === r.id;
                return (
                  <div
                    key={r.id}
                    onClick={() => setSelectedAgent(r)}
                    onMouseEnter={(e) => { if (!active) e.currentTarget.style.background = WB.hover; }}
                    onMouseLeave={(e) => { if (!active) e.currentTarget.style.background = 'transparent'; }}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 8, padding: '7px 12px', margin: '1px 6px', borderRadius: 6,
                      cursor: 'pointer', fontSize: FS.body, lineHeight: 1,
                      background: active ? WB.activeBg : 'transparent',
                      color: active ? WB.primary : WB.text, fontWeight: active ? 600 : 400,
                    }}
                  >
                    <RobotOutlined style={{ fontSize: 15, color: active ? WB.primary : '#722ed1', flex: '0 0 auto' }} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.name}</div>
                      <div style={{ fontSize: FS.micro, color: WB.textAux, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.slug} · {r.model_alias}</div>
                    </div>
                    {!r.is_active && <Tag color="red" style={{ marginInlineEnd: 0, fontSize: FS.micro, lineHeight: '16px', padding: '0 4px' }}>停用</Tag>}
                  </div>
                );
              })
            )}
          </div>
        </section>

        {/* 右栏：智能体配置 */}
        <section style={{ flex: 5, minWidth: 0, display: 'flex', flexDirection: 'column', background: '#fff' }}>
          <Toolbar
            left={
              selectedAgent ? (
                <PathBar
                  rootLabel={selectedAgent.name}
                  rootIcon={<RobotOutlined style={{ fontSize: 12 }} />}
                  segs={[selectedAgent.slug, SCOPE_LABEL[selectedAgent.scope_type]]}
                  onSeg={() => {}}
                />
              ) : <span style={{ fontSize: FS.aux, color: WB.textAux }}>智能体配置</span>
            }
            right={selectedAgent && (
              <>
                <ToolButton icon={<DeleteOutlined style={{ fontSize: 13 }} />} danger onClick={() => setConfirm({ id: selectedAgent.id, name: selectedAgent.name })}>删除</ToolButton>
                <ToolButton primary icon={<EditOutlined style={{ fontSize: 13 }} />} onClick={() => form.submit()} disabled={!dirty}>保存</ToolButton>
              </>
            )}
          />
          <div style={{ flex: 1, overflowY: 'auto', padding: 16 }} className="wb-scroll-hide">
            {!selectedAgent ? (
              <FinderEmpty description="请从中栏选择智能体" />
            ) : (
              <Form
                form={form} layout="vertical"
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
                  <Select
                    mode="multiple" allowClear showSearch placeholder="无"
                    optionFilterProp="label"
                    options={ragList?.map((c) => ({ value: c.id, label: c.name })) ?? []}
                  />
                </Form.Item>
                <Form.Item name="skill_ids" label="绑定技能（可多选，仅此智能体可调用）">
                  <Select
                    mode="multiple" allowClear showSearch placeholder="无"
                    optionFilterProp="label"
                    options={skillList.map((s) => ({ value: s.id, label: `${s.name}（${SCOPE_LABEL[s.scope_type] ?? s.scope_type}）` }))}
                  />
                </Form.Item>
                <Space>
                  <Form.Item name="temperature" label="Temperature"><InputNumber min={0} max={2} step={0.1} /></Form.Item>
                  <Form.Item name="max_tokens" label="Max Tokens"><InputNumber min={1} /></Form.Item>
                  <Form.Item name="is_active" label="启用" valuePropName="checked"><Switch /></Form.Item>
                </Space>
              </Form>
            )}
          </div>
        </section>
      </div>

      {/* 新建智能体 */}
      <Modal
        title="新建智能体" open={createModal}
        onCancel={() => setCreateModal(false)} onOk={() => createForm.submit()} confirmLoading={create.isPending} width={820}
        destroyOnClose
      >
        <Form
          form={createForm} layout="vertical"
          onFinish={(v) => create.mutate(v)}
          initialValues={{ is_active: true }}
        >
          <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
            作用域：{scope ? `${scope.nodeName} · ${SCOPE_LABEL[scope.scope_type]}` : '—'}（slug 由系统按名称自动生成）
          </Typography.Text>
          <Form.Item name="description" label="描述"><Input /></Form.Item>
          <Form.Item name="system_prompt" label="系统提示词" rules={[{ required: true }]}>
            <TextArea rows={6} style={{ fontFamily: 'monospace' }} />
          </Form.Item>
          <Form.Item name="rag_collection_ids" label="绑定 RAG 集合（可多选）">
            <Select
              mode="multiple" allowClear showSearch placeholder="无"
              optionFilterProp="label"
              options={ragList?.map((c) => ({ value: c.id, label: c.name })) ?? []}
            />
          </Form.Item>
          <Form.Item name="skill_ids" label="绑定技能（可多选）">
            <Select
              mode="multiple" allowClear showSearch placeholder="无"
              optionFilterProp="label"
              options={skillList.map((s) => ({ value: s.id, label: `${s.name}（${SCOPE_LABEL[s.scope_type] ?? s.scope_type}）` }))}
            />
          </Form.Item>
        </Form>
      </Modal>

      <ConfirmModal
        open={!!confirm}
        title={<>确定删除智能体「{confirm?.name}」？</>}
        okText="删除"
        loading={del.isPending}
        onCancel={() => setConfirm(null)}
        onOk={() => { if (confirm) del.mutate(confirm.id); setConfirm(null); }}
      />
    </FinderShell>
  );
}
