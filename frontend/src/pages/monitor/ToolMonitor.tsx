import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Card, Empty, Space, Spin, Table, Typography } from 'antd';
import { ToolOutlined } from '@ant-design/icons';
import { monitor, type ToolMetrics } from '../../api/client';
import OrgSelect from '../../components/OrgSelect';
import StatCard from '../../components/StatCard';
import { FinderShell, TitleBar } from '../../components/finder/primitives';

export default function ToolMonitor() {
  const [orgId, setOrgId] = useState<string | undefined>();
  const { data, isLoading } = useQuery<ToolMetrics>({
    queryKey: ['monitor-tool', orgId],
    queryFn: () => orgId ? monitor.tools(orgId) : Promise.resolve(null as unknown as ToolMetrics),
    enabled: !!orgId,
  });

  return (
    <FinderShell>
      <TitleBar icon={<ToolOutlined />} title="工具监控" titleExtra={<OrgSelect value={orgId} onChange={setOrgId} />} />
      <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
        {!orgId ? <Typography.Text type="secondary">请选择组织。</Typography.Text> :
          isLoading || !data ? <Spin /> : (
            <>
              <Space style={{ display: 'flex', marginBottom: 16, flexWrap: 'wrap' }}>
                <StatCard title="总调用" value={data.calls} color="#722ed1" />
                <StatCard title="成功" value={data.success_count} color="#52c41a" />
                <StatCard title="错误数" value={data.error_count} color="#cf1322" />
                <StatCard title="错误率" value={data.error_rate * 100} suffix="%" precision={2} color="#cf1322" />
                <StatCard title="平均延迟" value={data.avg_latency_ms} suffix="ms" precision={1} />
              </Space>

              <Card title="业务应用 Action 调用明细" style={{ marginBottom: 16 }}>
                <Table
                  rowKey="action_id"
                  dataSource={data.by_action}
                  pagination={{ pageSize: 20 }}
                  size="small"
                  locale={{ emptyText: <Empty description="近 24h 无业务 Action 调用" /> }}
                  columns={[
                    { title: 'Action', dataIndex: 'action_name' },
                    { title: '标识', dataIndex: 'action_key' },
                    { title: '模块', dataIndex: 'module_key', width: 150, render: (value: string | null) => value || '-' },
                    { title: '操作', dataIndex: 'operation', width: 90, render: (value: string | null) => value || '-' },
                    { title: '调用数', dataIndex: 'calls', width: 90 },
                    { title: '错误数', dataIndex: 'error_count', width: 90 },
                    {
                      title: '错误率', dataIndex: 'error_rate', width: 100,
                      render: (value: number) => `${(value * 100).toFixed(2)}%`,
                    },
                    {
                      title: '平均延迟', dataIndex: 'avg_latency_ms', width: 110,
                      render: (value: number) => `${value} ms`,
                    },
                  ]}
                />
              </Card>

            </>
          )}
      </div>
    </FinderShell>
  );
}
