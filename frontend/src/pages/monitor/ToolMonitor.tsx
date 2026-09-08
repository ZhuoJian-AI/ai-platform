import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Card, Empty, Space, Spin, Table, Typography } from 'antd';
import { ToolOutlined } from '@ant-design/icons';
import { monitor, type ToolMetrics } from '../../api/client';
import OrgSelect from '../../components/OrgSelect';
import StatCard from '../../components/StatCard';
import { FinderShell, TitleBar } from '../../components/finder/primitives';

const SCOPE_LABEL: Record<string, string> = {
  organization: '企业', department: '部门', role: '角色', user: '用户',
};

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

              <Card size="small" style={{ marginBottom: 16 }} title="用户上传 Skill">
                <Typography.Text>
                  技能文件夹 {data.inventory.skills.folders_total} · 文件 {data.inventory.skills.files_total}
                </Typography.Text>
              </Card>

              <Card title="Skill 调用明细">
                <Table
                  rowKey="skill_id"
                  dataSource={data.by_skill}
                  pagination={{ pageSize: 20 }}
                  size="small"
                  locale={{ emptyText: <Empty description="近 24h 无 Skill 调用" /> }}
                  columns={[
                    { title: '技能', dataIndex: 'skill_name' },
                    {
                      title: '作用域', dataIndex: 'scope_type', width: 100,
                      render: (value: string | null) => value ? (SCOPE_LABEL[value] ?? value) : '-',
                    },
                    { title: '调用数', dataIndex: 'calls', width: 120 },
                    { title: '错误数', dataIndex: 'error_count', width: 100 },
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
