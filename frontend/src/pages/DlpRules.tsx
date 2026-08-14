import { useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import {
  Button, Modal, Table, Tag, Form, Input, Select, InputNumber,
  Space, message, Switch, Alert, Row, Col, Tooltip, Typography, Descriptions,
} from 'antd';
import {
  PlusOutlined, DeleteOutlined, ExperimentOutlined, EditOutlined, SafetyOutlined,
  BankOutlined, ApartmentOutlined, TeamOutlined,
} from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { dlpRules, departments, teams } from '../api/client';
import type { DlpRule, DlpRuleLibraryEntry } from '../api/client';
import { ApiError } from '../api/client';
import { useOrgTree } from '../hooks/useOrgTree';
import OrgSelect from '../components/OrgSelect';
import {
  FinderShell, TitleBar, Sidebar, MacTree, Toolbar,
  FinderEmpty, type FinderTreeNode,
} from '../components/finder/primitives';
import ConfirmModal from '../components/finder/ConfirmModal';
import { WB, FS } from '../components/finder/theme';

const SEVERITY_COLORS: Record<string, string> = {
  low: 'default',
  medium: 'blue',
  high: 'orange',
  critical: 'red',
};

const ACTION_COLORS: Record<string, string> = {
  block: 'red',
  redact: 'orange',
  warn: 'gold',
  log: 'default',
};

const DIRECTION_LABELS: Record<string, string> = {
  request: '仅请求',
  response: '仅响应',
  both: '请求+响应',
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

interface DlpEditForm {
  severity: DlpRule['severity'];
  action: DlpRule['action'];
  direction: DlpRule['direction'];
  scope_type: DlpRule['scope_type'];
  scope_dept?: string | null;
  scope_team?: string | null;
  is_active: boolean;
  priority: number;
}

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

export default function DlpRules() {
  const qc = useQueryClient();
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [testModalOpen, setTestModalOpen] = useState(false);
  const [testRuleId, setTestRuleId] = useState<string>('');
  const [testText, setTestText] = useState('');
  const [testResult, setTestResult] = useState<{ matched: boolean; violations: unknown[]; redacted_text: string | null } | null>(null);
  const [form] = Form.useForm();

  const [editModalOpen, setEditModalOpen] = useState(false);
  const [editingRule, setEditingRule] = useState<DlpRule | null>(null);
  const [editForm] = Form.useForm<DlpEditForm>();
  const [confirm, setConfirm] = useState<{ id: string; name: string } | null>(null);

  const [selectedOrgId, setSelectedOrgId] = useState<string | undefined>();
  const [selectedNodeKey, setSelectedNodeKey] = useState<string | null>(null);

  const { treeData, nodeMap, isLoading: treeLoading } = useOrgTree();
  const orgId = selectedOrgId;

  const { data: library } = useQuery({
    queryKey: ['dlpRuleLibrary'],
    queryFn: () => dlpRules.library(),
    staleTime: 5 * 60 * 1000,
  });

  const finderTree = useMemo(
    () => buildFinderTree(treeData as unknown as RawTreeNode[], orgId, nodeMap as unknown as Map<string, { type: string; id: string; name: string }>),
    [treeData, nodeMap, orgId],
  );
  const selectedNode = selectedNodeKey ? nodeMap.get(selectedNodeKey) : undefined;

  const { data: ruleList, isLoading } = useQuery({
    queryKey: ['dlpRules', orgId],
    queryFn: () => orgId ? dlpRules.list(orgId) : Promise.resolve([]),
    enabled: !!orgId,
  });

  // 按选中节点过滤：组织节点 = 组织级；部门节点 = 该部门；团队节点 = 该团队
  const scopedRules: DlpRule[] = useMemo(() => {
    const all = ruleList ?? [];
    if (!selectedNode) return [];
    if (selectedNode.type === 'organization') {
      return all.filter((r) => r.scope_type === 'organization');
    }
    if (selectedNode.type === 'department') {
      return all.filter((r) => r.scope_type === 'department' && r.scope_id === selectedNode.id);
    }
    if (selectedNode.type === 'team') {
      return all.filter((r) => r.scope_type === 'team' && r.scope_id === selectedNode.id);
    }
    return [];
  }, [ruleList, selectedNode]);

  // 当前选中 scope 已添加的规则名（用于添加 Modal 下拉去重）
  const addedNamesInScope = useMemo(() => new Set(scopedRules.map((r) => r.name)), [scopedRules]);

  // ── 配置范围所需的部门/团队下拉数据 ──
  const editScopeType = Form.useWatch('scope_type', editForm);
  const editDeptId = Form.useWatch('scope_dept', editForm);
  const { data: editDepts } = useQuery({
    queryKey: ['depts', orgId],
    queryFn: () => orgId ? departments.list(orgId) : Promise.resolve([]),
    enabled: !!orgId && editModalOpen,
  });
  const { data: editTeams } = useQuery({
    queryKey: ['teams', editDeptId],
    queryFn: () => editDeptId ? teams.list(editDeptId) : Promise.resolve([]),
    enabled: !!editDeptId && editScopeType === 'team',
  });

  const createRule = useMutation({
    mutationFn: (data: { library_name: string } & Partial<DlpRule>) => {
      if (!orgId) {
        message.error('请先创建组织');
        return Promise.reject(new Error('No organization'));
      }
      return dlpRules.create(orgId, data);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['dlpRules'] });
      setCreateModalOpen(false);
      form.resetFields();
      message.success('规则添加成功');
    },
    onError: (err: unknown) => {
      const msg = err instanceof ApiError ? err.message : '添加失败，请检查输入';
      message.error(msg);
    },
  });

  const deleteRule = useMutation({
    mutationFn: (id: string) => dlpRules.delete(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['dlpRules'] }); message.success('规则已删除'); },
    onError: () => { message.error('删除失败'); },
  });

  const updateRule = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<DlpRule> }) => dlpRules.update(id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['dlpRules'] });
      setEditModalOpen(false);
      setEditingRule(null);
      message.success('规则已配置');
    },
    onError: (err: unknown) => {
      const msg = err instanceof ApiError ? err.message : '配置失败，请检查输入';
      message.error(msg);
    },
  });

  // 启动开关：仅切换 is_active。组织级规则组织管理员可启停。
  const toggleActive = useMutation({
    mutationFn: ({ id, is_active }: { id: string; is_active: boolean }) => dlpRules.update(id, { is_active }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['dlpRules'] }); },
    onError: () => { message.error('切换失败'); },
  });

  // 选中节点决定的 scope（添加 Modal 用）
  const createScopeType: DlpRule['scope_type'] = (selectedNode?.type as DlpRule['scope_type']) ?? 'organization';
  const createScopeId: string | null = createScopeType === 'organization'
    ? null
    : (selectedNode?.id ?? null);

  const openCreate = () => {
    form.resetFields();
    setCreateModalOpen(true);
  };

  const openEdit = async (r: DlpRule) => {
    setEditingRule(r);
    setEditModalOpen(true);
    editForm.setFieldsValue({
      severity: r.severity,
      action: r.action,
      direction: r.direction,
      scope_type: r.scope_type,
      scope_dept: r.scope_type === 'department' ? r.scope_id : undefined,
      scope_team: undefined,
      is_active: r.is_active,
      priority: r.priority,
    });
    if (r.scope_type === 'team' && r.scope_id) {
      try {
        const team = await teams.get(r.scope_id);
        editForm.setFieldValue('scope_dept', team.department_id);
        editForm.setFieldValue('scope_team', r.scope_id);
      } catch {
        // 取不到父部门时仅清空，用户可重新选择
      }
    }
  };

  const submitCreate = (v: {
    library_name: string;
    severity: string; action: string; direction: string; priority: number; is_active: boolean;
  }) => {
    if (!selectedNode) {
      message.error('请先在左侧选择节点');
      return;
    }
    createRule.mutate({
      library_name: v.library_name,
      severity: v.severity as DlpRule['severity'],
      action: v.action as DlpRule['action'],
      direction: v.direction as DlpRule['direction'],
      scope_type: createScopeType,
      scope_id: createScopeId,
      is_active: v.is_active,
      priority: v.priority,
    });
  };

  const submitEdit = (v: DlpEditForm) => {
    if (!editingRule) return;
    const scopeType = v.scope_type;
    let scopeId: string | null = null;
    if (scopeType === 'department') scopeId = v.scope_dept ?? null;
    else if (scopeType === 'team') scopeId = v.scope_team ?? null;
    const orgIdForScope = orgId ?? null;
    updateRule.mutate({
      id: editingRule.id,
      data: {
        severity: v.severity,
        action: v.action,
        direction: v.direction,
        scope_type: scopeType,
        scope_id: scopeId,
        organization_id: orgIdForScope,
        is_active: v.is_active,
        priority: v.priority,
      },
    });
  };

  const testRuleMutation = useMutation({
    mutationFn: ({ id, text }: { id: string; text: string }) => dlpRules.test(id, text, 'request'),
    onSuccess: (data) => { setTestResult(data); },
    onError: () => { message.error('测试失败'); },
  });

  const createBtn = (
    <Tooltip title={!selectedNode ? '请先在左侧选择组织/部门/团队节点' : ''}>
      <Button type="primary" icon={<PlusOutlined />} disabled={!selectedNode} onClick={openCreate}>添加规则</Button>
    </Tooltip>
  );

  return (
    <FinderShell>
      <TitleBar
        icon={<SafetyOutlined />}
        title="安全围栏"
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
                      {selectedNode.name}
                    </Typography.Text>
                  </Space>
                }
              />
              <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
                <Table
                  dataSource={scopedRules}
                  rowKey="id"
                  loading={isLoading}
                  pagination={{ pageSize: 20 }}
                  columns={[
                    { title: '规则名称', dataIndex: 'name', width: 180 },
                    { title: '类型', dataIndex: 'rule_type', width: 100, render: (v: string) => <Tag>{v}</Tag> },
                    { title: '严重级别', dataIndex: 'severity', width: 100, render: (v: string) => <Tag color={SEVERITY_COLORS[v]}>{v}</Tag> },
                    { title: '动作', dataIndex: 'action', width: 90, render: (v: string) => <Tag color={ACTION_COLORS[v]}>{v}</Tag> },
                    { title: '方向', dataIndex: 'direction', width: 110, render: (v: string) => DIRECTION_LABELS[v] || v },
                    {
                      title: '范围', dataIndex: 'scope_type', width: 100,
                      render: (v: string) => <Tag color={SCOPE_COLORS[v] ?? 'default'}>{SCOPE_LABELS[v] ?? v}</Tag>,
                    },
                    {
                      title: '启动', dataIndex: 'is_active', width: 80,
                      render: (v: boolean, r: DlpRule) => (
                        <Switch
                          size="small"
                          checked={v}
                          onChange={(checked) => toggleActive.mutate({ id: r.id, is_active: checked })}
                        />
                      ),
                    },
                    { title: '优先级', dataIndex: 'priority', width: 80, sorter: (a: DlpRule, b: DlpRule) => a.priority - b.priority },
                    {
                      title: '操作', width: 200,
                      render: (_: unknown, r: DlpRule) => (
                        <Space>
                          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(r)}>配置</Button>
                          <Button size="small" icon={<ExperimentOutlined />} onClick={() => { setTestRuleId(r.id); setTestModalOpen(true); setTestResult(null); }}>测试</Button>
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

      {/* 添加规则 Modal：从规则库下拉选一条，配置 6 项 */}
      <Modal
        title="添加规则"
        open={createModalOpen}
        onCancel={() => { setCreateModalOpen(false); }}
        onOk={() => form.submit()}
        width={640}
      >
        <Form form={form} layout="vertical" onFinish={submitCreate} initialValues={{ severity: 'high', action: 'block', direction: 'both', priority: 0, is_active: true }}>
          {selectedNode && (
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
              message={
                <span>
                  添加到：
                  <Tag color={SCOPE_COLORS[selectedNode.type]} style={{ marginInlineStart: 8 }}>
                    {SCOPE_LABELS[selectedNode.type]}
                  </Tag>
                  {selectedNode.name}
                </span>
              }
            />
          )}
          <Form.Item name="library_name" label="选择规则（规则库）" rules={[{ required: true, message: '请选择一条规则' }]}>
            <Select
              showSearch
              placeholder="从规则库选择一条规则"
              optionFilterProp="label"
              notFoundContent="规则库为空或已全部添加"
              options={(library ?? [])
                .filter((e) => !addedNamesInScope.has(e.name))
                .map((e: DlpRuleLibraryEntry) => ({ value: e.name, label: e.name }))}
              onChange={(name) => {
                const entry = (library ?? []).find((e) => e.name === name);
                if (entry) {
                  form.setFieldsValue({ severity: entry.severity, action: entry.action, direction: entry.direction });
                }
              }}
            />
          </Form.Item>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item name="severity" label="严重级别" rules={[{ required: true }]}>
                <Select options={[
                  { value: 'low', label: '低' },
                  { value: 'medium', label: '中' },
                  { value: 'high', label: '高' },
                  { value: 'critical', label: '严重' },
                ]} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="action" label="执行动作" rules={[{ required: true }]}>
                <Select options={[
                  { value: 'block', label: '拦截' },
                  { value: 'redact', label: '脱敏' },
                  { value: 'warn', label: '警告' },
                  { value: 'log', label: '记录' },
                ]} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="direction" label="检测方向" rules={[{ required: true }]}>
                <Select options={[
                  { value: 'request', label: '仅请求' },
                  { value: 'response', label: '仅响应' },
                  { value: 'both', label: '请求+响应' },
                ]} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="priority" label="优先级" rules={[{ required: true }]}>
                <InputNumber min={0} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="is_active" label="启用状态" valuePropName="checked">
                <Switch checkedChildren="启用" unCheckedChildren="停用" />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>

      {/* 测试规则 Modal */}
      <Modal
        title="测试 DLP 规则"
        open={testModalOpen}
        onCancel={() => setTestModalOpen(false)}
        onOk={() => testRuleMutation.mutate({ id: testRuleId, text: testText })}
        okText="测试"
      >
        <Input.TextArea
          rows={4}
          value={testText}
          onChange={e => setTestText(e.target.value)}
          placeholder="输入要测试的文本，如：我的身份证号是 110101199003077718"
          style={{ marginBottom: 16 }}
        />
        {testResult && (
          <Alert
            type={testResult.matched ? 'error' : 'success'}
            showIcon
            message={testResult.matched ? '⚠️ 检测到敏感信息' : '✅ 未检测到敏感信息'}
            description={testResult.redacted_text ? `脱敏结果: ${testResult.redacted_text}` : undefined}
          />
        )}
      </Modal>

      {/* 配置规则 Modal：name/rule_type/pattern 只读，仅配置 6 项 */}
      <Modal
        title="配置规则"
        open={editModalOpen}
        onCancel={() => { setEditModalOpen(false); setEditingRule(null); }}
        onOk={() => editForm.submit()}
        confirmLoading={updateRule.isPending}
        width={640}
      >
        {editingRule && (
          <Descriptions column={1} size="small" style={{ marginBottom: 16 }} bordered>
            <Descriptions.Item label="规则名称">{editingRule.name}</Descriptions.Item>
          </Descriptions>
        )}
        <Form form={editForm} layout="vertical" onFinish={submitEdit}>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item name="severity" label="严重级别" rules={[{ required: true }]}>
                <Select options={[
                  { value: 'low', label: '低' },
                  { value: 'medium', label: '中' },
                  { value: 'high', label: '高' },
                  { value: 'critical', label: '严重' },
                ]} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="action" label="执行动作" rules={[{ required: true }]}>
                <Select options={[
                  { value: 'block', label: '拦截' },
                  { value: 'redact', label: '脱敏' },
                  { value: 'warn', label: '警告' },
                  { value: 'log', label: '记录' },
                ]} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="direction" label="检测方向" rules={[{ required: true }]}>
                <Select options={[
                  { value: 'request', label: '仅请求' },
                  { value: 'response', label: '仅响应' },
                  { value: 'both', label: '请求+响应' },
                ]} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="scope_type" label="范围" rules={[{ required: true }]}>
            <Select
              options={[
                { value: 'organization', label: '组织 — 当前组织' },
                { value: 'department', label: '部门 — 指定部门' },
                { value: 'team', label: '团队 — 指定团队' },
              ]}
            />
          </Form.Item>
          {editScopeType === 'department' && (
            <Form.Item name="scope_dept" label="目标部门" rules={[{ required: true, message: '请选择部门' }]}>
              <Select
                placeholder="选择部门"
                options={editDepts?.map(d => ({ value: d.id, label: d.name })) ?? []}
                notFoundContent="该组织下暂无部门"
              />
            </Form.Item>
          )}
          {editScopeType === 'team' && (
            <Row gutter={16}>
              <Col span={12}>
                <Form.Item name="scope_dept" label="所属部门" rules={[{ required: true, message: '请选择部门' }]}>
                  <Select
                    placeholder="选择部门"
                    options={editDepts?.map(d => ({ value: d.id, label: d.name })) ?? []}
                    notFoundContent="该组织下暂无部门"
                    onChange={() => editForm.setFieldValue('scope_team', undefined)}
                  />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item name="scope_team" label="目标团队" rules={[{ required: true, message: '请选择团队' }]}>
                  <Select
                    placeholder="选择团队"
                    options={editTeams?.map(t => ({ value: t.id, label: t.name })) ?? []}
                    notFoundContent={editDeptId ? '该部门下暂无团队' : '请先选择部门'}
                  />
                </Form.Item>
              </Col>
            </Row>
          )}
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="priority" label="优先级" rules={[{ required: true }]}>
                <InputNumber min={0} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="is_active" label="启用状态" valuePropName="checked">
                <Switch checkedChildren="启用" unCheckedChildren="停用" />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>

      <ConfirmModal
        open={!!confirm}
        title={<>确定删除规则「{confirm?.name}」？</>}
        okText="删除"
        loading={deleteRule.isPending}
        onCancel={() => setConfirm(null)}
        onOk={() => { if (confirm) deleteRule.mutate(confirm.id); setConfirm(null); }}
      />
    </FinderShell>
  );
}
