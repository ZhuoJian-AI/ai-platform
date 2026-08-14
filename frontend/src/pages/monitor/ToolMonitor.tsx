import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Card, Typography, Table, Space, Spin, Tabs, Tag, Empty } from 'antd';
import { ToolOutlined } from '@ant-design/icons';
import { monitor } from '../../api/client';
import type { ToolMetrics } from '../../api/client';
import OrgSelect from '../../components/OrgSelect';
import StatCard from '../../components/StatCard';
import { FinderShell, TitleBar } from '../../components/finder/primitives';

const SCOPE_LABEL: Record<string, string> = {
  organization: '组织', department: '部门', team: '团队', user: '用户',
};

const HEALTH_COLOR: Record<string, string> = {
  healthy: 'green', degraded: 'orange', down: 'red', unknown: 'default',
};

function healthTag(status: string) {
  return <Tag color={HEALTH_COLOR[status] ?? 'default'}>{status}</Tag>;
}

export default function ToolMonitor() {
  const [orgId, setOrgId] = useState<string | undefined>();
  const { data, isLoading } = useQuery<ToolMetrics>({
    queryKey: ['monitor-tool', orgId],
    queryFn: () => orgId ? monitor.tools(orgId) : Promise.resolve(null as unknown as ToolMetrics),
    enabled: !!orgId,
  });

  const inv = data?.inventory;

  return (
    <FinderShell>
      <TitleBar icon={<ToolOutlined />} title="工具监控" titleExtra={<OrgSelect value={orgId} onChange={setOrgId} />} />

      <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
        {!orgId ? <Typography.Text type="secondary">请选择组织。</Typography.Text> :
          isLoading || !data ? <Spin /> : (
            <>
              {/* 调用概览 */}
              <Space style={{ display: 'flex', marginBottom: 16, flexWrap: 'wrap' }}>
                <StatCard title="总调用" value={data.calls} color="#722ed1" />
                <StatCard title="成功" value={data.success_count} color="#52c41a" />
                <StatCard title="错误数" value={data.error_count} color="#cf1322" />
                <StatCard title="错误率" value={data.error_rate * 100} suffix="%" precision={2} color="#cf1322" />
                <StatCard title="平均延迟" value={data.avg_latency_ms} suffix="ms" precision={1} />
              </Space>

              {/* 四组件资源盘点 */}
              {inv && (
                <Space style={{ display: 'flex', marginBottom: 16, flexWrap: 'wrap', alignItems: 'stretch' }}>
                  <Card size="small" style={{ flex: 1, minWidth: 200 }} title="工具连接器">
                    <Space direction="vertical" size={0}>
                      <Typography.Text>总数 {inv.connectors.total} · 启用 {inv.connectors.active} · 停用 {inv.connectors.inactive}</Typography.Text>
                      <Space size={4} wrap>
                        {Object.entries(inv.connectors.by_health).map(([k, v]) => (
                          <span key={k}>{healthTag(k)} {v}</span>
                        ))}
                      </Space>
                    </Space>
                  </Card>
                  <Card size="small" style={{ flex: 1, minWidth: 200 }} title="数据接口">
                    <Typography.Text>
                      系统 {inv.data_interfaces.systems_total} · 接口 {inv.data_interfaces.interfaces_total}
                    </Typography.Text><br />
                    <Typography.Text>启用 {inv.data_interfaces.active} · 停用 {inv.data_interfaces.inactive}</Typography.Text>
                  </Card>
                  <Card size="small" style={{ flex: 1, minWidth: 200 }} title="技能">
                    <Typography.Text>技能文件夹 {inv.skills.folders_total} · 文件 {inv.skills.files_total}</Typography.Text>
                  </Card>
                  <Card size="small" style={{ flex: 1, minWidth: 200 }} title="本体">
                    <Typography.Text>文件夹 {inv.ontology.folders_total} · 文件 {inv.ontology.files_total}</Typography.Text>
                  </Card>
                </Space>
              )}

              {/* 明细表 */}
              <Card title="调用明细">
                <Tabs
                  items={[
                    {
                      key: 'connector',
                      label: `按连接器 (${data.by_connector.length})`,
                      children: (
                        <Table rowKey={(r) => r.connector_id ?? 'none'} dataSource={data.by_connector}
                          pagination={{ pageSize: 20 }} size="small"
                          locale={{ emptyText: <Empty description="近 24h 无工具调用" /> }}
                          columns={[
                            { title: '连接器', dataIndex: 'connector_name' },
                            { title: '类型', dataIndex: 'type', width: 90 },
                            { title: '健康', dataIndex: 'health_status', width: 90, render: healthTag },
                            { title: '启用', dataIndex: 'is_active', width: 70, render: (v) => v === null ? '-' : <Tag color={v ? 'green' : 'default'}>{v ? '是' : '否'}</Tag> },
                            { title: '调用数', dataIndex: 'calls', width: 100 },
                            { title: '错误数', dataIndex: 'error_count', width: 90 },
                            { title: '错误率', dataIndex: 'error_rate', width: 90, render: (v: number) => `${(v * 100).toFixed(2)}%` },
                            { title: '平均延迟', dataIndex: 'avg_latency_ms', width: 100, render: (v: number) => `${v} ms` },
                            { title: '最近调用', dataIndex: 'last_called_at', width: 180, render: (v: string | null) => v ?? '-' },
                          ]}
                        />
                      ),
                    },
                    {
                      key: 'skill',
                      label: `按技能 (${data.by_skill.length})`,
                      children: (
                        <Table rowKey="skill_id" dataSource={data.by_skill} pagination={{ pageSize: 20 }} size="small"
                          locale={{ emptyText: <Empty description="近 24h 无技能调用" /> }}
                          columns={[
                            { title: '技能', dataIndex: 'skill_name' },
                            { title: '作用域', dataIndex: 'scope_type', width: 100, render: (v: string | null) => v ? (SCOPE_LABEL[v] ?? v) : '-' },
                            { title: '调用数', dataIndex: 'calls', width: 120 },
                            { title: '错误数', dataIndex: 'error_count', width: 100 },
                            { title: '错误率', dataIndex: 'error_rate', width: 100, render: (v: number) => `${(v * 100).toFixed(2)}%` },
                            { title: '平均延迟', dataIndex: 'avg_latency_ms', width: 110, render: (v: number) => `${v} ms` },
                          ]}
                        />
                      ),
                    },
                    {
                      key: 'endpoint',
                      label: `按端点 (${data.by_endpoint.length})`,
                      children: (
                        <Table rowKey="endpoint_id" dataSource={data.by_endpoint} pagination={{ pageSize: 20 }} size="small"
                          locale={{ emptyText: <Empty description="近 24h 无端点调用" /> }}
                          columns={[
                            { title: '端点', dataIndex: 'endpoint_name' },
                            { title: '所属连接器', dataIndex: 'connector_name', width: 160 },
                            { title: '方法', dataIndex: 'method', width: 80 },
                            { title: '路径', dataIndex: 'path' },
                            { title: '调用数', dataIndex: 'calls', width: 100 },
                            { title: '错误数', dataIndex: 'error_count', width: 90 },
                            { title: '错误率', dataIndex: 'error_rate', width: 90, render: (v: number) => `${(v * 100).toFixed(2)}%` },
                            { title: '平均延迟', dataIndex: 'avg_latency_ms', width: 100, render: (v: number) => `${v} ms` },
                          ]}
                        />
                      ),
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
