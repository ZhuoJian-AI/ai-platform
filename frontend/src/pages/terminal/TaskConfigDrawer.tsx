import { useEffect, useMemo, useState } from 'react';
import { Drawer, Select, Typography, Space, Tag, Empty, Divider } from 'antd';
import type { TaskConfig, TerminalResources, TerminalAgent, TerminalModels } from '../../api/client';

interface Props {
  open: boolean;
  onClose: () => void;
  onApply: (config: TaskConfig) => void;
  resources: TerminalResources | undefined;
  config: TaskConfig;
  models: string[];
  modelCapabilities?: TerminalModels['capabilities'];
  visionFallbackAvailable?: boolean;
  imageGenerationAvailable?: boolean;
  /** 用户可见的活跃智能体（供「选智能体」下拉）。 */
  agents: TerminalAgent[];
  /** 当前选中的智能体 id；null=通用智能体（不绑模板）。逐次运行覆盖，不落库。 */
  agentId: string | null;
  onAgentChange: (id: string | null) => void;
}

/** 任务资源配置抽屉：工作空间 / 模型。

 * RAG 固定绑定在智能体；智能体 Skill 是默认推荐，聊天仍可按当前轮选择其他有权 Skill。
 */
export default function TaskConfigDrawer({ open, onApply, resources, config, models, modelCapabilities, visionFallbackAvailable, imageGenerationAvailable, agents, agentId, onAgentChange }: Props) {
  const [local, setLocal] = useState<TaskConfig>(config);
  const personalWorkspace = useMemo(() => (
    resources?.workspaces.find((workspace) => workspace.id === resources.defaults?.workspace_id)
      ?? resources?.workspaces.find((workspace) => workspace.scope_type === 'user')
  ), [resources]);

  useEffect(() => {
    if (open) {
      setLocal({ ...config, workspace_id: personalWorkspace?.id ?? null });
    }
  }, [open, config, personalWorkspace?.id]);

  const update = (patch: Partial<TaskConfig>) => setLocal((c) => ({ ...c, ...patch }));

  const apply = () => onApply({ ...local, workspace_id: personalWorkspace?.id ?? null });

  // 模型下拉：直接列用户权限范围内 API Key 允许的全部模型（embedding 已在后端过滤）
  const modelOptions = models.map((m) => ({
    value: m,
    label: modelCapabilities?.[m]?.vision ? `${m}（视觉）` : m,
  }));

  return (
    <Drawer
      open={open} onClose={() => { apply(); }} width={520}
      rootClassName="wb-cfg-drawer"
      title="任务资源配置"
      extra={<a onClick={apply}>应用</a>}
      styles={{ body: { padding: '18px 20px', background: '#fafafa' } }}
    >
      <Typography.Text>
        工作空间与模型在这里选择；系统提示词和固定 RAG 由所选智能体决定。Skill 可来自智能体默认推荐，也可在聊天中仅对当前轮明确调用；本体与长期记忆仍按你的权限自动装配。
      </Typography.Text>

      <Divider orientation="left">工作空间</Divider>
      <div style={{ padding: '10px 12px', background: '#fff', border: '1px solid #e5e7eb', borderRadius: 8 }}>
        <Space>
          <span>{personalWorkspace?.name ?? '尚未创建个人工作空间'}</span>
          <Tag color="blue">个人</Tag>
        </Space>
        <Typography.Text type="secondary" style={{ display: 'block', marginTop: 4, fontSize: 12 }}>
          任务和 AI 文件操作固定在个人工作空间；部门与企业资源只能按权限读取，不能在此直接改写。
        </Typography.Text>
      </div>

      <Divider orientation="left">模型</Divider>
      <Select
        style={{ width: '100%' }} allowClear showSearch placeholder="选择模型（留空用默认）"
        value={local.model_alias ?? undefined}
        onChange={(v) => update({ model_alias: v ?? null })}
        options={modelOptions}
        notFoundContent="当前作用域下无可用模型"
      />
      {!modelOptions.length && <Empty description="无可用模型，将使用默认" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ marginTop: 8 }} />}
      {(visionFallbackAvailable || imageGenerationAvailable) && (
        <Space size={6} wrap style={{ marginTop: 8 }}>
          {visionFallbackAvailable && <Tag color="cyan">已配置视觉回退</Tag>}
          {imageGenerationAvailable && <Tag color="magenta">Craft 可生图</Tag>}
        </Space>
      )}

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
          ? '该次执行将使用所选智能体的系统提示词、固定 RAG 与默认推荐 Skill；聊天仍可临时调用其他有权 Skill。'
          : `通用智能体不加载 RAG；仍可从 ${resources?.skills.length ?? 0} 个有权 Skill 中自动匹配或本轮明确调用。`}
      </Typography.Text>
    </Drawer>
  );
}
