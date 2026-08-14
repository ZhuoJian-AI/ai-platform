import { useQuery } from '@tanstack/react-query';
import { Card, Typography, Space, Spin } from 'antd';
import { BarChartOutlined } from '@ant-design/icons';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';
import { monitor } from '../../api/client';
import type { OverviewMetrics } from '../../api/client';
import OrgSelect from '../../components/OrgSelect';
import StatCard from '../../components/StatCard';
import { FinderShell, TitleBar } from '../../components/finder/primitives';
import { WB } from '../../components/finder/theme';
import { useState } from 'react';

export default function MonitorOverview() {
  const [orgId, setOrgId] = useState<string | undefined>();
  const { data, isLoading } = useQuery<OverviewMetrics>({
    queryKey: ['monitor-overview', orgId],
    queryFn: () => orgId ? monitor.overview(orgId) : Promise.resolve(null as unknown as OverviewMetrics),
    enabled: !!orgId,
  });

  const chartData = data ? [
    { name: '路由器', 请求数: data.router.requests, token: data.router.input_tokens + data.router.output_tokens },
    { name: '智能体', 运行数: data.agent.runs, token: data.agent.input_tokens + data.agent.output_tokens },
    { name: '工具', 调用数: data.tool.calls, token: 0 },
  ] : [];

  return (
    <FinderShell>
      <TitleBar icon={<BarChartOutlined />} title="监控总览" titleExtra={<OrgSelect value={orgId} onChange={setOrgId} />} />

      <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
        {!orgId ? <Typography.Text type="secondary">请选择组织。</Typography.Text> :
          isLoading || !data ? <Spin /> : (
            <>
              <Space style={{ display: 'flex', marginBottom: 16, flexWrap: 'wrap' }}>
                <StatCard title="路由器请求" value={data.router.requests} color={WB.primary} />
                <StatCard title="路由器错误率" value={data.router.error_rate * 100} suffix="%" precision={2} color="#cf1322" />
                <StatCard title="DLP 违规" value={data.router.dlp_violation_count} color="#fa8c16" />
                <StatCard title="智能体运行" value={data.agent.runs} color="#52c41a" />
                <StatCard title="智能体成功率" value={data.agent.success_rate * 100} suffix="%" precision={2} color="#52c41a" />
                <StatCard title="工具调用" value={data.tool.calls} color="#722ed1" />
                <StatCard title="工具错误率" value={data.tool.error_rate * 100} suffix="%" precision={2} color="#cf1322" />
              </Space>

              <Card title="调用量对比">
                <ResponsiveContainer width="100%" height={280}>
                  <BarChart data={chartData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" />
                    <YAxis />
                    <Tooltip />
                    <Bar dataKey="请求数" fill={WB.primary} />
                    <Bar dataKey="运行数" fill="#52c41a" />
                    <Bar dataKey="调用数" fill="#722ed1" />
                  </BarChart>
                </ResponsiveContainer>
              </Card>
            </>
          )}
      </div>
    </FinderShell>
  );
}
