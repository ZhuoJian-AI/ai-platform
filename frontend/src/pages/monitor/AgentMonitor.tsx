import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Card, Typography, Table, Space, Spin, Statistic, Tag } from 'antd';
import { RobotOutlined } from '@ant-design/icons';
import { monitor } from '../../api/client';
import type { AgentMetrics } from '../../api/client';
import OrgSelect from '../../components/OrgSelect';
import StatCard from '../../components/StatCard';
import { FinderShell, TitleBar } from '../../components/finder/primitives';

export default function AgentMonitor() {
  const [orgId, setOrgId] = useState<string | undefined>();
  const { data, isLoading } = useQuery<AgentMetrics>({
    queryKey: ['monitor-agent', orgId],
    queryFn: () => orgId ? monitor.agents(orgId) : Promise.resolve(null as unknown as AgentMetrics),
    enabled: !!orgId,
  });

  const components = data?.components;

  return (
    <FinderShell>
      <TitleBar icon={<RobotOutlined />} title="智能体监控" titleExtra={<OrgSelect value={orgId} onChange={setOrgId} />} />

      <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
        {!orgId ? <Typography.Text type="secondary">请选择组织。</Typography.Text> :
          isLoading || !data ? <Spin /> : (
            <>
              <Space style={{ display: 'flex', marginBottom: 16, flexWrap: 'wrap' }}>
                <StatCard title="总运行" value={data.runs} color="#52c41a" />
                <StatCard title="成功次数" value={data.success_count} color="#52c41a" />
                <StatCard title="成功率" value={data.success_rate * 100} suffix="%" precision={2} />
                <StatCard title="输入 token" value={data.input_tokens} />
                <StatCard title="输出 token" value={data.output_tokens} />
                <StatCard title="平均延迟" value={data.avg_latency_ms} suffix="ms" precision={1} />
              </Space>

              <Card title="按智能体明细" style={{ marginBottom: 16 }}>
                <Table
                  rowKey={(r) => r.agent_id ?? `general-${r.exec_mode}`}
                  dataSource={data.by_agent}
                  pagination={{ pageSize: 20 }}
                  columns={[
                    {
                      title: '智能体', dataIndex: 'agent_name',
                      render: (_, r) => (
                        <Space>
                          <span>{r.agent_name}</span>
                          {r.type === 'general'
                            ? <Tag color="blue">通用</Tag>
                            : <Tag color="purple">具名智能体</Tag>}
                        </Space>
                      ),
                    },
                    { title: '运行数', dataIndex: 'runs', width: 120 },
                    { title: '输入 token', dataIndex: 'input_tokens', width: 140 },
                    { title: '输出 token', dataIndex: 'output_tokens', width: 140 },
                  ]}
                />
              </Card>

              {components && (
                <Card title="组件使用（工作空间 / RAG知识库 / 长期记忆）">
                  <Space size="large" align="start" style={{ flexWrap: 'wrap' }}>
                    <Card size="small" title="工作空间" style={{ minWidth: 220 }}>
                      <Space direction="vertical" size="small" style={{ width: '100%' }}>
                        <Statistic title="使用运行数" value={components.workspace.runs} />
                        <Statistic title="文件操作次数" value={components.workspace.ops} />
                      </Space>
                    </Card>
                    <Card size="small" title="RAG 知识库" style={{ minWidth: 220 }}>
                      <Space direction="vertical" size="small" style={{ width: '100%' }}>
                        <Statistic title="检索运行数" value={components.rag.runs} />
                        <Statistic title="命中片段数" value={components.rag.hits} />
                      </Space>
                    </Card>
                    <Card size="small" title="长期记忆" style={{ minWidth: 220 }}>
                      <Space direction="vertical" size="small" style={{ width: '100%' }}>
                        <Statistic title="载入运行数" value={components.memory.load_runs} />
                        <Statistic title="载入事实数" value={components.memory.facts_loaded} />
                        <Statistic title="沉淀运行数" value={components.memory.extract_runs} />
                        <Statistic title="沉淀事实数" value={components.memory.facts_saved} />
                      </Space>
                    </Card>
                  </Space>
                </Card>
              )}
            </>
          )}
      </div>
    </FinderShell>
  );
}
