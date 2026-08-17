import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { Drawer, Select, Typography, Space, Tag, Empty, TreeSelect, Divider } from 'antd';
import type { TaskConfig, TerminalResources, TerminalAgent, Workspace } from '../../api/client';

interface Props {
  open: boolean;
  onClose: () => void;
  onApply: (config: TaskConfig) => void;
  resources: TerminalResources | undefined;
  config: TaskConfig;
  models: string[];
  /** 用户可见的活跃智能体（供「选智能体」下拉）。 */
  agents: TerminalAgent[];
  /** 当前选中的智能体 id；null=通用智能体（不绑模板）。逐次运行覆盖，不落库。 */
  agentId: string | null;
  onAgentChange: (id: string | null) => void;
}

const SCOPE_OPTIONS = [
  { label: '组织级', value: 'organization' },
  { label: '部门级', value: 'department' },
  { label: '团队级', value: 'team' },
  { label: '个人级', value: 'user' },
];

const SCOPE_LABEL: Record<string, string> = Object.fromEntries(
  SCOPE_OPTIONS.map((o) => [o.value, o.label]),
);

/** 任务资源配置抽屉：工作空间 / 模型。

 * Skill / RAG 在智能体页面绑定；本体与长期记忆按用户权限自动装配。
 */
export default function TaskConfigDrawer({ open, onApply, resources, config, models, agents, agentId, onAgentChange }: Props) {
  const [local, setLocal] = useState<TaskConfig>(config);

  useEffect(() => {
    if (open) {
      setLocal(config);
    }
  }, [open, config]);

  const update = (patch: Partial<TaskConfig>) => setLocal((c) => ({ ...c, ...patch }));

  const apply = () => onApply(local);

  // 模型下拉：直接列用户权限范围内 API Key 允许的全部模型（embedding 已在后端过滤）
  const modelOptions = models.map((m) => ({ value: m, label: m }));

  // 工作空间树：用户权限可见的工作空间按 scope 层级（组织→部门→团队→个人）嵌套成单链。
  // 用户至多见每层一个工作空间，构成一条路径；value = workspace.id。
  const wsTreeData = useMemo(() => {
    const rank: Record<string, number> = { organization: 0, department: 1, team: 2, user: 3 };
    const items = (resources?.workspaces ?? [])
      .slice()
      .sort((a, b) => (rank[a.scope_type] ?? 9) - (rank[b.scope_type] ?? 9));
    const labelOf = (w: Workspace): ReactNode => (
      <Space size="small">
        <span>{w.name}</span>
        <Tag color="blue">{SCOPE_LABEL[w.scope_type] ?? w.scope_type}</Tag>
      </Space>
    );
    interface WsTreeNode { value: string; title: ReactNode; children?: WsTreeNode[] }
    let root: WsTreeNode | null = null;
    let cursor: WsTreeNode | null = null;
    for (const w of items) {
      const node: WsTreeNode = { value: w.id, title: labelOf(w) };
      if (!root || !cursor) { root = node; cursor = node; }
      else { cursor.children = [node]; cursor = node; }
    }
    return root ? [root] : [];
  }, [resources?.workspaces]);

  return (
    <Drawer
      open={open} onClose={() => { apply(); }} width={520}
      rootClassName="wb-cfg-drawer"
      title="任务资源配置"
      extra={<a onClick={apply}>应用</a>}
      styles={{ body: { padding: '18px 20px', background: '#fafafa' } }}
    >
      <Typography.Text>
        工作空间与模型在这里选择；系统提示词、RAG 和 Skill 由所选智能体决定。未选择智能体时不会加载任何 Skill 或 RAG；本体与长期记忆仍按你的权限自动装配。
      </Typography.Text>

      <Divider orientation="left">工作空间</Divider>
      <TreeSelect
        style={{ width: '100%' }} allowClear showSearch treeNodeFilterProp="title"
        treeDefaultExpandAll
        placeholder="选择工作空间（可读写其中文件）"
        value={local.workspace_id ?? undefined}
        onChange={(v) => update({ workspace_id: (v as string) ?? null })}
        treeData={wsTreeData}
        notFoundContent="当前作用域下无可用工作空间"
      />

      <Divider orientation="left">模型</Divider>
      <Select
        style={{ width: '100%' }} allowClear showSearch placeholder="选择模型（留空用默认）"
        value={local.model_alias ?? undefined}
        onChange={(v) => update({ model_alias: v ?? null })}
        options={modelOptions}
        notFoundContent="当前作用域下无可用模型"
      />
      {!modelOptions.length && <Empty description="无可用模型，将使用默认" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ marginTop: 8 }} />}

      <Divider orientation="left">智能体</Divider>
      <Select
        style={{ width: '100%' }} allowClear showSearch optionFilterProp="label"
        placeholder="不绑定（通用智能体）"
        value={agentId ?? undefined}
        onChange={(v) => onAgentChange((v as string) ?? null)}
        options={agents.map((a) => ({ value: a.id, label: `${a.name}（${a.slug}）` }))}
        notFoundContent="当前作用域下无可用智能体"
      />
      <Typography.Text type="secondary" style={{ display: 'block', marginTop: 8, fontSize: 12 }}>
        {agentId
          ? '该次执行将使用所选智能体的系统提示词、RAG 与已绑定 Skill（逐次覆盖，不写入任务配置）。'
          : '不绑定智能体 → 走通用智能体（系统默认提示词 + 本体/记忆，不加载 Skill 或 RAG）。'}
      </Typography.Text>
    </Drawer>
  );
}
