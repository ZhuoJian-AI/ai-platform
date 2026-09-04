import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Alert, Card, Typography, Table, Space, Spin, Tag, Row, Col, Statistic, Switch,
  Tabs, Select, DatePicker, Button,
} from 'antd';
import {
  CloudServerOutlined, ThunderboltOutlined, ApartmentOutlined,
  KeyOutlined, SafetyOutlined, ReloadOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import {
  monitor, budget as budgetApi, apiKeys as apiKeysApi,
  organizations, providers as providersApi, dlpRules as dlpRulesApi, auditLogs,
} from '../../api/client';
import type {
  RouterMetrics, BudgetKeyUsage, BudgetProviderUsage, BudgetScopeType, BudgetScopeUsage,
  AuditLogEntry,
} from '../../api/client';
import OrgSelect from '../../components/OrgSelect';
import StatCard from '../../components/StatCard';
import { FinderShell, TitleBar, Toolbar } from '../../components/finder/primitives';
import { WB, FS } from '../../components/finder/theme';

/** 格式化 token 数量：1234567 -> 1.23M */
function fmtTokens(n: number): string {
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(2)}B`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(2)}K`;
  return String(n);
}

function fmtAsOf(value?: string, timezone?: string): string {
  if (!value) return '—';
  try {
    return new Intl.DateTimeFormat('zh-CN', {
      timeZone: timezone || 'UTC',
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
    }).format(new Date(value));
  } catch {
    return value;
  }
}

const SCOPE_LABELS: Record<BudgetScopeType, string> = {
  organization: '企业',
  department: '部门',
  team: '团队',
  api_key: 'API Key',
};

const SCOPE_COLORS: Record<BudgetScopeType, string> = {
  organization: 'purple',
  department: 'blue',
  team: 'cyan',
  api_key: 'gold',
};

interface BudgetScopeTreeNode extends BudgetScopeUsage {
  children?: BudgetScopeTreeNode[];
}

function buildScopeTree(scopes: BudgetScopeUsage[]): BudgetScopeTreeNode[] {
  const nodes = new Map(scopes.map((scope) => [
    `${scope.scope_type}:${scope.scope_id}`,
    { ...scope, children: [] } as BudgetScopeTreeNode,
  ]));
  const roots: BudgetScopeTreeNode[] = [];

  for (const node of nodes.values()) {
    const parentKey = node.parent_scope_type && node.parent_scope_id
      ? `${node.parent_scope_type}:${node.parent_scope_id}`
      : null;
    const parent = parentKey ? nodes.get(parentKey) : undefined;
    if (parent) parent.children?.push(node);
    else roots.push(node);
  }

  const sortNodes = (items: BudgetScopeTreeNode[]) => {
    items.sort((a, b) => a.scope_name.localeCompare(b.scope_name, 'zh-CN'));
    items.forEach((item) => {
      if (item.children?.length) sortNodes(item.children);
      else delete item.children;
    });
  };
  sortNodes(roots);
  return roots;
}

function renderDirectCap(value: number | null, scopeType: BudgetScopeType, token = false) {
  if (value == null) return <Tag>{scopeType === 'organization' ? '无限' : '继承'}</Tag>;
  return token ? fmtTokens(value) : value.toLocaleString();
}

function renderEffectiveRemaining(value: number | null, token = false) {
  if (value == null) return <Tag>无限</Tag>;
  return token ? fmtTokens(value) : value.toLocaleString();
}

const EVENT_TYPE_COLORS: Record<string, string> = {
  proxy_request: 'blue',
  dlp_violation: 'red',
  rate_limited: 'orange',
  budget_exceeded: 'volcano',
  auth_failure: 'magenta',
};

export default function RouterMonitor() {
  const [orgId, setOrgId] = useState<string | undefined>();
  const [tab, setTab] = useState('overview');

  // ── 概览（原仪表盘） ──
  const { data: orgs } = useQuery({ queryKey: ['orgs'], queryFn: organizations.list });
  const { data: providerList } = useQuery({
    queryKey: ['providers', orgId],
    queryFn: () => orgId ? providersApi.list(orgId) : Promise.resolve([]),
    enabled: !!orgId,
  });
  const { data: keyList } = useQuery({
    queryKey: ['apiKeys', orgId],
    queryFn: () => orgId ? apiKeysApi.list(orgId) : Promise.resolve([]),
    enabled: !!orgId,
  });
  const { data: ruleList } = useQuery({
    queryKey: ['dlpRules', orgId],
    queryFn: () => orgId ? dlpRulesApi.list(orgId) : Promise.resolve([]),
    enabled: !!orgId,
  });

  // ── 路由指标 ──
  const { data: routerData, isLoading: routerLoading } = useQuery<RouterMetrics>({
    queryKey: ['monitor-router', orgId],
    queryFn: () => orgId ? monitor.router(orgId) : Promise.resolve(null as unknown as RouterMetrics),
    enabled: !!orgId,
  });

  // ── 预算消耗 ──
  const [showRevoked, setShowRevoked] = useState(false);
  const { data: usage, isLoading: budgetLoading } = useQuery({
    queryKey: ['budget-usage', orgId, showRevoked],
    queryFn: () => (orgId ? budgetApi.usage(orgId, { include_revoked: showRevoked }) : Promise.resolve(null)),
    enabled: !!orgId && tab === 'budget',
  });

  // ── 审计日志 ──
  const [eventType, setEventType] = useState<string | undefined>();
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs | null, dayjs.Dayjs | null] | null>(null);
  const [page, setPage] = useState(0);
  const { data: logData, isLoading: logsLoading, refetch: refetchLogs } = useQuery({
    queryKey: ['auditLogs', orgId, eventType, dateRange, page],
    queryFn: () => {
      if (!orgId) return Promise.resolve({ total: 0, offset: 0, limit: 50, data: [] });
      return auditLogs.list(orgId, {
        event_type: eventType,
        start_time: dateRange?.[0]?.toISOString(),
        end_time: dateRange?.[1]?.toISOString(),
        limit: 50,
        offset: page * 50,
      });
    },
    enabled: !!orgId && tab === 'audit',
  });

  // ── 预算表列定义 ──
  const budgetKeys: BudgetKeyUsage[] = usage?.api_keys ?? [];
  const budgetScopes = buildScopeTree(usage?.scopes ?? []);
  const reportedTokens = Math.max(0, (usage?.total_tokens ?? 0) - (usage?.retained_unknown_tokens ?? 0));

  const scopeColumns = [
    {
      title: '额度作用域', dataIndex: 'scope_name', width: 260, fixed: 'left' as const,
      render: (name: string, row: BudgetScopeUsage) => (
        <Space size={6}>
          <Tag color={SCOPE_COLORS[row.scope_type]}>{SCOPE_LABELS[row.scope_type]}</Tag>
          <Typography.Text>{name}</Typography.Text>
          {row.is_inactive && <Tag color="default">已停用</Tag>}
        </Space>
      ),
    },
    { title: '直接 RPM', width: 115, align: 'right' as const, render: (_: unknown, row: BudgetScopeUsage) => renderDirectCap(row.direct_caps.rpm, row.scope_type) },
    { title: '直接 TPM', width: 115, align: 'right' as const, render: (_: unknown, row: BudgetScopeUsage) => renderDirectCap(row.direct_caps.tpm, row.scope_type, true) },
    { title: '直接 Token/月', width: 145, align: 'right' as const, render: (_: unknown, row: BudgetScopeUsage) => renderDirectCap(row.direct_caps.monthly_tokens, row.scope_type, true) },
    { title: '直接调用额度/月', width: 155, align: 'right' as const, render: (_: unknown, row: BudgetScopeUsage) => renderDirectCap(row.direct_caps.monthly_credits, row.scope_type) },
    { title: '已回报 Token', width: 140, align: 'right' as const, render: (_: unknown, row: BudgetScopeUsage) => fmtTokens(row.usage.actual_tokens) },
    {
      title: '保守占用/尚未回报', width: 180, align: 'right' as const,
      render: (_: unknown, row: BudgetScopeUsage) => row.usage.held_unknown_tokens
        ? <Tag color="gold">{fmtTokens(row.usage.held_unknown_tokens)}</Tag>
        : '0',
    },
    { title: '已扣调用额度', width: 140, align: 'right' as const, render: (_: unknown, row: BudgetScopeUsage) => row.usage.credits.toLocaleString() },
    { title: '请求数', width: 105, align: 'right' as const, render: (_: unknown, row: BudgetScopeUsage) => row.usage.requests.toLocaleString() },
    {
      title: '有效 Token 余额', width: 155, align: 'right' as const,
      render: (_: unknown, row: BudgetScopeUsage) => renderEffectiveRemaining(row.effective_remaining.monthly_tokens, true),
    },
    {
      title: '有效调用额度余额', width: 175, align: 'right' as const,
      render: (_: unknown, row: BudgetScopeUsage) => renderEffectiveRemaining(row.effective_remaining.monthly_credits),
    },
  ];

  const providerColumns = [
    {
      title: 'Provider', dataIndex: 'provider_name', width: 200,
      render: (_v: string, r: BudgetProviderUsage) => (
        <span>
          {r.provider_name}
          {r.provider_type && <Tag style={{ marginLeft: 8 }}>{r.provider_type}</Tag>}
        </span>
      ),
    },
    { title: '输入 token', dataIndex: 'input_tokens', width: 140, align: 'right' as const, render: (v: number) => fmtTokens(v) },
    { title: '输出 token', dataIndex: 'output_tokens', width: 140, align: 'right' as const, render: (v: number) => fmtTokens(v) },
    { title: '已回报 token', width: 140, align: 'right' as const, render: (_v: unknown, r: BudgetProviderUsage) => <strong>{fmtTokens(Math.max(0, r.total_tokens - (r.retained_unknown_tokens ?? 0)))}</strong> },
    { title: '保守占用/尚未回报', dataIndex: 'retained_unknown_tokens', width: 180, align: 'right' as const, render: (v: number) => v ? <Tag color="gold">{fmtTokens(v)}</Tag> : '0' },
    { title: '扣减额度', dataIndex: 'credits', width: 120, align: 'right' as const, render: (v: number) => v.toLocaleString() },
    { title: '请求数', dataIndex: 'request_count', width: 120, align: 'right' as const },
  ];

  const mainColumns = [
    {
      title: 'Key 名称', dataIndex: 'key_name', width: 220,
      render: (v: string, r: BudgetKeyUsage) => (
        <span>
          {v}
          {r.is_revoked && <Tag color="red" style={{ marginLeft: 8 }}>已删除</Tag>}
        </span>
      ),
    },
    { title: '输入 token', dataIndex: 'input_tokens', width: 130, align: 'right' as const, render: (v: number) => fmtTokens(v) },
    { title: '输出 token', dataIndex: 'output_tokens', width: 130, align: 'right' as const, render: (v: number) => fmtTokens(v) },
    {
      title: '已回报 token', width: 140, align: 'right' as const,
      render: (_v: unknown, r: BudgetKeyUsage) => <strong>{fmtTokens(Math.max(0, r.total_tokens - (r.retained_unknown_tokens ?? 0)))}</strong>,
    },
    {
      title: '保守占用/尚未回报', dataIndex: 'retained_unknown_tokens', width: 180, align: 'right' as const,
      render: (v: number) => v ? <Tag color="gold">{fmtTokens(v)}</Tag> : '0',
    },
    {
      title: '已扣调用额度', dataIndex: 'credits', width: 140, align: 'right' as const,
      render: (v: number) => <strong>{v.toLocaleString()}</strong>,
    },
    { title: 'Provider 数', width: 110, align: 'center' as const, render: (_v: unknown, r: BudgetKeyUsage) => r.providers.length },
  ];

  return (
    <FinderShell>
      <TitleBar
        icon={<CloudServerOutlined />}
        title="路由器监控"
        titleExtra={<OrgSelect value={orgId} onChange={(v) => { setOrgId(v); setPage(0); }} />}
      />

      <Tabs
        activeKey={tab}
        onChange={setTab}
        size="small"
        className="rm-tabs"
        tabBarStyle={{ marginBottom: 0 }}
        items={[
          {
            key: 'overview',
            label: '概览',
            children: (
              <div className="rm-tab-body">
                <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
                  {!orgId ? <Typography.Text type="secondary">请选择组织。</Typography.Text> : (
                    <>
                      <Row gutter={[16, 16]}>
                        <Col xs={24} sm={12} lg={6}>
                          <Card>
                            <Statistic title="组织数量" value={orgs?.length ?? 0}
                              prefix={<ApartmentOutlined style={{ color: WB.primary }} />}
                              valueStyle={{ color: WB.primary }} />
                          </Card>
                        </Col>
                        <Col xs={24} sm={12} lg={6}>
                          <Card>
                            <Statistic title="LLM 提供商" value={providerList?.length ?? 0}
                              prefix={<CloudServerOutlined style={{ color: '#52c41a' }} />}
                              valueStyle={{ color: '#52c41a' }} />
                          </Card>
                        </Col>
                        <Col xs={24} sm={12} lg={6}>
                          <Card>
                            <Statistic title="活跃 API Key" value={keyList?.filter(k => k.is_active).length ?? 0}
                              prefix={<KeyOutlined style={{ color: '#faad14' }} />}
                              valueStyle={{ color: '#faad14' }} />
                          </Card>
                        </Col>
                        <Col xs={24} sm={12} lg={6}>
                          <Card>
                            <Statistic title="DLP 规则" value={ruleList?.filter(r => r.is_active).length ?? 0}
                              prefix={<SafetyOutlined style={{ color: '#ff4d4f' }} />}
                              valueStyle={{ color: '#ff4d4f' }} />
                          </Card>
                        </Col>
                      </Row>

                      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
                        <Col xs={24} lg={14}>
                          <Card title="活跃提供商" size="small">
                            {providerList && providerList.length > 0 ? (
                              providerList.map(p => (
                                <div key={p.id} style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: `1px solid ${WB.border}` }}>
                                  <span>{p.name}</span>
                                  <span style={{ color: WB.textAux }}>{p.provider_type}</span>
                                </div>
                              ))
                            ) : (
                              <Typography.Text type="secondary">暂无提供商，请先注册 LLM 提供商</Typography.Text>
                            )}
                          </Card>
                        </Col>
                        <Col xs={24} lg={10}>
                          <Card title="快速入门" size="small">
                            <Typography.Paragraph><Typography.Text strong>1.</Typography.Text> 创建组织并注册 LLM 提供商</Typography.Paragraph>
                            <Typography.Paragraph><Typography.Text strong>2.</Typography.Text> 配置 DLP 安全围栏规则</Typography.Paragraph>
                            <Typography.Paragraph><Typography.Text strong>3.</Typography.Text> 为团队生成 API Key</Typography.Paragraph>
                            <Typography.Paragraph><Typography.Text strong>4.</Typography.Text> 客户端设置 <code>base_url</code> 指向本平台</Typography.Paragraph>
                          </Card>
                        </Col>
                      </Row>
                    </>
                  )}
                </div>
              </div>
            ),
          },
          {
            key: 'metrics',
            label: '路由指标',
            children: (
              <div className="rm-tab-body">
                <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
                  {!orgId ? <Typography.Text type="secondary">请选择组织。</Typography.Text> :
                    routerLoading || !routerData ? <Spin /> : (
                      <>
                        <Space style={{ display: 'flex', marginBottom: 16, flexWrap: 'wrap' }}>
                          <StatCard title="总请求" value={routerData.requests} />
                          <StatCard title="输入 token" value={routerData.input_tokens} />
                          <StatCard title="输出 token" value={routerData.output_tokens} />
                          <StatCard title="平均延迟" value={routerData.avg_latency_ms} suffix="ms" precision={1} />
                          <StatCard title="错误数" value={routerData.error_count} color="#cf1322" />
                          <StatCard title="DLP 违规" value={routerData.dlp_violation_count} color="#fa8c16" />
                        </Space>
                        <Card title="按提供商明细">
                          <Table rowKey={(r) => r.provider_id ?? 'none'} dataSource={routerData.by_provider} pagination={{ pageSize: 20 }}
                            columns={[
                              { title: '提供商', dataIndex: 'provider_name' },
                              { title: '请求数', dataIndex: 'requests', width: 120 },
                              { title: '输入 token', dataIndex: 'input_tokens', width: 140 },
                              { title: '输出 token', dataIndex: 'output_tokens', width: 140 },
                              { title: '状态', width: 100, render: (_: unknown, r) => <Tag color={r.requests > 0 ? 'green' : 'default'}>{r.requests > 0 ? '活跃' : '空闲'}</Tag> },
                            ]} />
                        </Card>
                      </>
                    )}
                </div>
              </div>
            ),
          },
          {
            key: 'budget',
            label: '预算消耗',
            children: (
              <div className="rm-tab-body">
                <Toolbar
                  left={
                    <Space size={4}>
                      <Switch size="small" checked={showRevoked} onChange={setShowRevoked} />
                      <Typography.Text type="secondary" style={{ fontSize: 13 }}>显示已删除 Key</Typography.Text>
                    </Space>
                  }
                  right={
                    <span style={{ color: WB.textAux, fontSize: FS.aux }}>
                      统计周期：{usage?.period_start ?? '—'} ~ {usage?.period_end ?? '—'}
                      {' · '}数据截至：{fmtAsOf(usage?.as_of, usage?.timezone)} {usage?.timezone ?? ''}
                    </span>
                  }
                />
                <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
                  {!orgId ? <Typography.Text type="secondary">请选择组织。</Typography.Text> : (
                    <>
                      <Alert
                        showIcon
                        type="info"
                        message="一次平台 AI 操作准入扣 1 次调用额度；失败不退；供应商重试或故障转移不重复扣"
                        description="下表的有效余额由服务端沿企业、部门、团队和 API Key 额度链计算后直接返回；页面不自行推算。企业未设置直接额度显示为“无限”，其他层显示为“继承”；有效余额为“无限”表示整条链均未设置上限。历史 USD 预算只读且不再执行。"
                        style={{ marginBottom: 16 }}
                      />
                      <Row gutter={[16, 16]}>
                        <Col xs={24} sm={12} lg={6}>
                          <Card>
                            <Statistic title="本月已回报 token" value={fmtTokens(reportedTokens)}
                              prefix={<ThunderboltOutlined />} valueStyle={{ color: WB.primary }} />
                          </Card>
                        </Col>
                        <Col xs={24} sm={12} lg={6}>
                          <Card>
                            <Statistic title="保守占用/尚未回报" value={fmtTokens(usage?.retained_unknown_tokens ?? 0)}
                              prefix={<ThunderboltOutlined />} valueStyle={{ color: '#d97706' }} />
                          </Card>
                        </Col>
                        <Col xs={24} sm={12} lg={6}>
                          <Card>
                            <Statistic title="本月已扣调用额度" value={(usage?.credits ?? 0).toLocaleString()}
                              prefix={<ThunderboltOutlined />} valueStyle={{ color: WB.primary }} />
                          </Card>
                        </Col>
                        <Col xs={24} sm={12} lg={6}>
                          <Card>
                            <Statistic title="活跃 Key 数量" value={keyList?.filter(k => k.is_active).length ?? 0}
                              prefix={<ThunderboltOutlined />} />
                          </Card>
                        </Col>
                      </Row>
                      <Card title="企业 / 部门 / 团队 / API Key 四级额度" style={{ marginTop: 16 }}>
                        <Table<BudgetScopeTreeNode>
                          dataSource={budgetScopes}
                          rowKey={(row) => `${row.scope_type}:${row.scope_id}`}
                          loading={budgetLoading}
                          pagination={false}
                          scroll={{ x: 1700 }}
                          columns={scopeColumns}
                        />
                      </Card>
                      <Card title="API Key / Provider 用量明细（展开查看 Provider）" style={{ marginTop: 16 }}>
                        <Table<BudgetKeyUsage>
                          dataSource={budgetKeys}
                          rowKey={(r) => r.api_key_id ?? '__unassigned__'}
                          loading={budgetLoading}
                          pagination={{ pageSize: 15 }}
                          scroll={{ x: 1200 }}
                          columns={mainColumns}
                          expandable={{
                            rowExpandable: (r) => r.providers.length > 0,
                            expandedRowRender: (r) => (
                              <Table<BudgetProviderUsage>
                                dataSource={r.providers}
                                rowKey={(p) => p.provider_id ?? '__unknown__'}
                                pagination={false}
                                size="small"
                                columns={providerColumns}
                              />
                            ),
                          }}
                        />
                      </Card>
                    </>
                  )}
                </div>
              </div>
            ),
          },
          {
            key: 'audit',
            label: '审计日志',
            children: (
              <div className="rm-tab-body">
                <Toolbar
                  left={
                    <Space wrap>
                      <Select
                        allowClear
                        placeholder="事件类型"
                        style={{ width: 160 }}
                        value={eventType}
                        onChange={(v) => { setEventType(v); setPage(0); }}
                        options={[
                          { value: 'proxy_request', label: '代理请求' },
                          { value: 'dlp_violation', label: 'DLP 违规' },
                          { value: 'rate_limited', label: '速率限制' },
                          { value: 'budget_exceeded', label: '预算超额' },
                          { value: 'auth_failure', label: '认证失败' },
                        ]}
                      />
                      <DatePicker.RangePicker
                        showTime
                        value={dateRange}
                        onChange={(v) => { setDateRange(v); setPage(0); }}
                      />
                    </Space>
                  }
                  right={<Button icon={<ReloadOutlined />} onClick={() => refetchLogs()}>刷新</Button>}
                />
                <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
                  {!orgId ? <Typography.Text type="secondary">请选择组织。</Typography.Text> : (
                    <Table<AuditLogEntry>
                      dataSource={logData?.data ?? []}
                      rowKey="id"
                      loading={logsLoading}
                      pagination={{
                        total: logData?.total ?? 0,
                        pageSize: 50,
                        current: page + 1,
                        onChange: (p) => setPage(p - 1),
                        showTotal: (t) => `共 ${t} 条`,
                      }}
                      scroll={{ x: 1400 }}
                      columns={[
                        { title: '时间', dataIndex: 'created_at', width: 180, render: (v: string) => new Date(v).toLocaleString('zh-CN') },
                        { title: '事件', dataIndex: 'event_type', width: 130, render: (v: string) => <Tag color={EVENT_TYPE_COLORS[v] || 'default'}>{v}</Tag> },
                        { title: '方向', dataIndex: 'direction', width: 80, render: (v: string) => v === 'inbound' ? '⬅ 入站' : '➡ 出站' },
                        { title: '请求模型', dataIndex: 'model_requested', width: 170, ellipsis: true },
                        { title: '实际模型', dataIndex: 'model_served', width: 170, ellipsis: true },
                        { title: '输入Token', dataIndex: 'input_tokens', width: 100, render: (v: number | null) => v?.toLocaleString() ?? '-' },
                        { title: '输出Token', dataIndex: 'output_tokens', width: 100, render: (v: number | null) => v?.toLocaleString() ?? '-' },
                        { title: '延迟', dataIndex: 'latency_ms', width: 90, render: (v: number | null) => v ? `${v}ms` : '-' },
                        { title: 'DLP违规', dataIndex: 'dlp_violations', width: 100, render: (v: unknown[]) => v?.length > 0 ? <Tag color="red">{v.length}</Tag> : '-' },
                        { title: '状态码', dataIndex: 'status_code', width: 80, render: (v: number | null) => v ?? '-' },
                      ]}
                    />
                  )}
                </div>
              </div>
            ),
          },
        ]}
      />
    </FinderShell>
  );
}
