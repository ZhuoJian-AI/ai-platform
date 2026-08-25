import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  Alert, Button, Card, Col, Descriptions, Drawer, Empty, Form, Input,
  Modal, Pagination, Progress, Row, Select, Space, Statistic, Table, Tag, Timeline, Typography, Upload, message, Tabs,
} from 'antd';
import {
  ApiOutlined, CheckCircleOutlined, CloudDownloadOutlined, CloudServerOutlined,
  CodeOutlined, DeploymentUnitOutlined, ExclamationCircleOutlined, HistoryOutlined,
  InboxOutlined, LinkOutlined, PlayCircleOutlined, ReloadOutlined, RollbackOutlined,
  SafetyCertificateOutlined, ToolOutlined, SearchOutlined, GithubOutlined, DownloadOutlined,
} from '@ant-design/icons';
import {
  platformExtensions,
  type PlatformExtensionCatalogItem,
  type PlatformExtensionCatalogPage,
  type PlatformExtensionEvent,
  type PlatformExtensionOverview,
  type PlatformExtensionRelease,
  type PlatformExtensionSource,
} from '../../api/client';
import { WB, FS } from '../../components/finder/theme';

export type ExtensionSection = 'overview' | 'runtime' | 'tools' | 'catalog' | 'releases';

const STATUS_LABEL: Record<string, string> = {
  importing: '等待构建', building: '隔离构建中', review_required: '待人工审核', ready: '可创建候选',
  incompatible: '不兼容', failed: '失败', pending: '待审核', approved: '已审核', rejected: '已拒绝',
  draft: '草稿', validating: '候选验证中', publishing: '发布中', active: '当前活动', superseded: '历史版本',
  enabled: '已启用', disabled: '已停用', available: '可选', ok: '健康', unavailable: '不可用',
  not_imported: '未导入', installed: '已安装', candidate: '候选版本',
};

function statusColor(status: string): string {
  if (['active', 'ready', 'approved', 'enabled', 'installed', 'ok'].includes(status)) return 'green';
  if (['building', 'importing', 'validating', 'publishing'].includes(status)) return 'processing';
  if (['failed', 'incompatible', 'rejected', 'unavailable'].includes(status)) return 'red';
  if (status === 'disabled') return 'orange';
  return 'default';
}

function StatusTag({ status }: { status: string }) {
  return <Tag color={statusColor(status)}>{STATUS_LABEL[status] || status}</Tag>;
}

function KindTag({ kind }: { kind: string }) {
  const labels: Record<string, string> = {
    runtime_plugin: 'DSH Runtime 插件', system_tool: '系统工具', library: '运行库',
    adapter_required: '需要适配器', incompatible: '不兼容',
  };
  const colors: Record<string, string> = {
    runtime_plugin: 'purple', system_tool: 'blue', library: 'default', adapter_required: 'orange', incompatible: 'red',
  };
  return <Tag color={colors[kind]}>{labels[kind] || kind}</Tag>;
}

function MetricCard({ title, value, note, icon }: { title: string; value: ReactNode; note: string; icon: ReactNode }) {
  return (
    <Card styles={{ body: { padding: 18 } }} style={{ height: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16 }}>
        <div><Statistic title={title} value={value as any} /><div style={{ color: WB.textAux, fontSize: FS.micro, marginTop: 5 }}>{note}</div></div>
        <div style={{ width: 42, height: 42, borderRadius: 12, display: 'grid', placeItems: 'center', color: WB.primary, background: `${WB.primary}12`, fontSize: 20 }}>{icon}</div>
      </div>
    </Card>
  );
}

export default function PlatformExtensions({ section }: { section: ExtensionSection }) {
  const [overview, setOverview] = useState<PlatformExtensionOverview | null>(null);
  const [catalogPageData, setCatalogPageData] = useState<PlatformExtensionCatalogPage | null>(null);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [sources, setSources] = useState<PlatformExtensionSource[]>([]);
  const [releases, setReleases] = useState<PlatformExtensionRelease[]>([]);
  const [events, setEvents] = useState<PlatformExtensionEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [releaseOpen, setReleaseOpen] = useState(false);
  const [detail, setDetail] = useState<PlatformExtensionSource | null>(null);
  const [catalogDetail, setCatalogDetail] = useState<PlatformExtensionCatalogItem | null>(null);
  const [catalogQuery, setCatalogQuery] = useState('');
  const [catalogSearch, setCatalogSearch] = useState('');
  const [catalogPage, setCatalogPage] = useState(1);
  const [catalogTab, setCatalogTab] = useState<'compatible' | 'adapter' | 'all' | 'installed'>('compatible');
  const [catalogLayer, setCatalogLayer] = useState<string>('');
  const [catalogSource, setCatalogSource] = useState<string>('');
  const [catalogImport, setCatalogImport] = useState<PlatformExtensionCatalogItem | null>(null);
  const [catalogImportSource, setCatalogImportSource] = useState<'npm' | 'github'>('npm');
  const [catalogImportForm] = Form.useForm();
  const [importType, setImportType] = useState<'npm' | 'github' | 'archive'>('npm');
  const [archive, setArchive] = useState<File | null>(null);
  const [importForm] = Form.useForm();
  const [releaseForm] = Form.useForm();

  const refresh = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const [nextOverview, nextSources, nextReleases, nextEvents] = await Promise.all([
        platformExtensions.overview(), platformExtensions.sources(),
        platformExtensions.releases(), platformExtensions.events(),
      ]);
      setOverview(nextOverview); setSources(nextSources); setReleases(nextReleases); setEvents(nextEvents);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '平台扩展数据加载失败');
    } finally { if (!quiet) setLoading(false); }
  }, []);

  const refreshCatalog = useCallback(async (quiet = false) => {
    if (!quiet) setCatalogLoading(true);
    try {
      const pageData = await platformExtensions.catalogPage({
        q: catalogSearch,
        source: catalogSource,
        layer: catalogLayer,
        state: catalogTab,
        page: catalogPage,
        page_size: 48,
      });
      setCatalogPageData(pageData);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '插件目录加载失败');
    } finally {
      if (!quiet) setCatalogLoading(false);
    }
  }, [catalogLayer, catalogPage, catalogSearch, catalogSource, catalogTab]);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => { void refreshCatalog(); }, [refreshCatalog]);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setCatalogPage(1);
      setCatalogSearch(catalogQuery.trim());
    }, 300);
    return () => window.clearTimeout(timer);
  }, [catalogQuery]);
  useEffect(() => {
    if (!sources.some(item => ['importing', 'building'].includes(item.status))) return;
    const timer = window.setInterval(() => {
      void refresh(true);
      void refreshCatalog(true);
    }, 2500);
    return () => window.clearInterval(timer);
  }, [sources, refresh, refreshCatalog]);

  const approvedSources = useMemo(() => sources.filter(item => item.status === 'ready' && item.review_status === 'approved'), [sources]);

  const runAction = async (key: string, action: () => Promise<unknown>, success: string) => {
    setActionLoading(key);
    try { await action(); message.success(success); await Promise.all([refresh(true), refreshCatalog(true)]); }
    catch (error) {
      message.error(error instanceof Error ? error.message : '操作失败');
      await Promise.all([refresh(true), refreshCatalog(true)]);
    }
    finally { setActionLoading(null); }
  };

  const submitImport = async () => {
    const values = await importForm.validateFields();
    if (importType === 'archive' && !archive) { message.warning('请选择 ZIP 插件包'); return; }
    await runAction('import', async () => {
      if (importType === 'npm') return platformExtensions.importNpm(values.package, values.version);
      if (importType === 'github') return platformExtensions.importGithub(values.repository, values.ref);
      return platformExtensions.importArchive(archive!);
    }, '已进入隔离构建，不会自动发布');
    setImportOpen(false); importForm.resetFields(); setArchive(null);
  };

  const syncCatalog = () => runAction('catalog-sync', () => platformExtensions.syncCatalog(), '目录同步完成；远端失败时保留上次快照');

  const openCatalogImport = (item: PlatformExtensionCatalogItem) => {
    const version = item.available_versions?.[0] || item.version || '';
    const source = item.package_name ? 'npm' : 'github';
    setCatalogImportSource(source);
    catalogImportForm.setFieldsValue({ source, version, ref: version && version !== '待选择' ? version : 'main' });
    setCatalogImport(item);
  };

  const submitCatalogImport = async () => {
    if (!catalogImport?.id) return;
    const values = await catalogImportForm.validateFields();
    await runAction(`catalog-import-${catalogImport.id}`, () => platformExtensions.importCatalog(catalogImport.id!, values), '已导入候选并开始隔离构建');
    setCatalogImport(null);
  };

  const downloadAdaptationBrief = async (item: PlatformExtensionCatalogItem) => {
    if (!item.id) return;
    await runAction(`brief-${item.id}`, async () => {
      const markdown = await platformExtensions.adaptationBrief(item.id!);
      const href = URL.createObjectURL(new Blob([markdown], { type: 'text/markdown;charset=utf-8' }));
      const anchor = document.createElement('a');
      anchor.href = href; anchor.download = `adapt-${item.slug}.md`; anchor.click();
      URL.revokeObjectURL(href);
    }, 'Codex 适配任务已生成');
  };

  const submitRelease = async () => {
    const values = await releaseForm.validateFields();
    const sourceIds = values.source_ids || [];
    const selectedSources = approvedSources.filter(item => sourceIds.includes(item.id));
    const replacesCoordinator = selectedSources.some(item => (item.manifest?.provides || []).includes('coordinator'));
    const enabledToolGroups = new Set<string>(values.enabled_tool_groups || []);
    const disabledToolGroups = (overview?.system_tools || [])
      .filter(item => !enabledToolGroups.has(item.slug))
      .map(item => item.slug);
    await runAction('release-create', () => platformExtensions.createRelease(values.name, sourceIds, {
      disabled_plugins: replacesCoordinator ? ['dsh-agent-loop'] : [],
      disabled_tool_groups: disabledToolGroups,
    }), '候选发布已创建');
    setReleaseOpen(false); releaseForm.resetFields();
  };

  const openRelease = (extraSourceId?: string) => {
    const activeExternal = (overview?.active_release?.manifest?.external_extensions || []) as Array<Record<string, unknown>>;
    const activeTools = (overview?.active_release?.manifest?.system_tools || []) as Array<Record<string, unknown>>;
    const selectedSourceIds = activeExternal
      .filter(item => item.enabled !== false && typeof item.source_id === 'string')
      .map(item => item.source_id as string);
    if (extraSourceId && !selectedSourceIds.includes(extraSourceId)) selectedSourceIds.push(extraSourceId);
    releaseForm.setFieldsValue({
      name: `候选发布 ${new Date().toLocaleString()}`,
      source_ids: selectedSourceIds,
      enabled_tool_groups: activeTools
        .filter(item => item.enabled !== false && typeof item.slug === 'string')
        .map(item => item.slug),
    });
    setReleaseOpen(true);
  };

  const header = (
    <div style={{ minHeight: 72, padding: '16px 22px', borderBottom: `1px solid ${WB.border}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16 }}>
      <div>
        <Typography.Title level={3} style={{ margin: 0, fontSize: 20 }}>平台扩展中心</Typography.Title>
        <Typography.Text type="secondary">审核、验证并发布能够改变全平台 Harness 与系统工具的扩展</Typography.Text>
      </div>
      <Space>
        <Button icon={<ReloadOutlined />} onClick={() => void refresh()} loading={loading}>刷新</Button>
        {section === 'catalog' && <Button icon={<ReloadOutlined />} loading={actionLoading === 'catalog-sync'} onClick={() => void syncCatalog()}>同步插件目录</Button>}
        {section === 'catalog' && <Button type="primary" icon={<CloudDownloadOutlined />} onClick={() => setImportOpen(true)}>手工导入</Button>}
        {section === 'releases' && <Button type="primary" icon={<DeploymentUnitOutlined />} onClick={() => openRelease()}>创建候选发布</Button>}
      </Space>
    </div>
  );

  const renderOverview = () => {
    const health = String(overview?.runtime_health?.status || 'unavailable');
    return <>
      <Alert showIcon type="info" style={{ marginBottom: 16 }} message="平台插件与用户 Skill 是两套独立系统" description="这里的扩展会影响全部组织；导入只产生候选来源，必须经过审核、候选 Context 测试和发布确认才会进入 DSH。" />
      <Row gutter={[14, 14]}>
        <Col xs={24} md={12} xl={6}><MetricCard title="Runtime 状态" value={STATUS_LABEL[health] || health} note={`DSH ${overview?.runtime_health?.dsh_version || '—'} · Node ${overview?.runtime_health?.node || '—'}`} icon={<CloudServerOutlined />} /></Col>
        <Col xs={24} md={12} xl={6}><MetricCard title="活动发布" value={overview?.active_release ? `v${overview.active_release.version_no}` : '—'} note={overview?.active_release?.name || '尚未生成平台基线'} icon={<DeploymentUnitOutlined />} /></Col>
        <Col xs={24} md={12} xl={6}><MetricCard title="待审核来源" value={(overview?.source_counts?.review_required || 0)} note="外部代码不会自动进入 Runtime" icon={<SafetyCertificateOutlined />} /></Col>
        <Col xs={24} md={12} xl={6}><MetricCard title="活动任务" value={overview?.runtime_health?.active_runs || 0} note="发布前会先等待任务排空" icon={<PlayCircleOutlined />} /></Col>
      </Row>
      <Card title="当前装配" style={{ marginTop: 16 }}>
        <Descriptions column={{ xs: 1, md: 2, xl: 3 }} size="small">
          <Descriptions.Item label="发布 ID">{overview?.runtime_health?.release_id || 'baseline'}</Descriptions.Item>
          <Descriptions.Item label="发布校验和"><Typography.Text code>{String(overview?.runtime_health?.release_checksum || 'builtin').slice(0, 16)}</Typography.Text></Descriptions.Item>
          <Descriptions.Item label="并行工具调用">{overview?.runtime_health?.max_parallel_tool_calls ?? 1}</Descriptions.Item>
          <Descriptions.Item label="Runtime 重载次数">{overview?.runtime_health?.runtime_restarts ?? 0}</Descriptions.Item>
          <Descriptions.Item label="核心插件">{overview?.core_plugins.length || 0}</Descriptions.Item>
          <Descriptions.Item label="系统工具组">{overview?.system_tools.length || 0}</Descriptions.Item>
        </Descriptions>
      </Card>
    </>;
  };

  const renderRuntime = () => {
    const external = (overview?.active_release?.manifest?.external_extensions || []) as Array<Record<string, any>>;
    const replacementSlots = (overview?.active_release?.manifest?.replacement_slots || {}) as Record<string, string>;
    return <>
      <Card title="当前完整装配" style={{ marginBottom: 16 }}>
        <Descriptions size="small" column={{ xs: 1, md: 2, xl: 3 }}>
          <Descriptions.Item label="活动协调器">{replacementSlots.coordinator || (overview?.core_plugins.find(item => item.layer === 'coordinator' && item.status === 'enabled')?.name ?? 'Agent Loop')}</Descriptions.Item>
          <Descriptions.Item label="外部 Runtime 插件">{external.filter(item => item.enabled !== false && item.type === 'runtime_plugin').length}</Descriptions.Item>
          <Descriptions.Item label="外部系统工具">{external.filter(item => item.enabled !== false && item.type === 'system_tool').length}</Descriptions.Item>
          <Descriptions.Item label="发布校验和"><Typography.Text code>{String(overview?.active_release?.checksum || 'baseline').slice(0, 16)}</Typography.Text></Descriptions.Item>
          <Descriptions.Item label="替换插槽">{Object.keys(replacementSlots).length ? <Space wrap>{Object.entries(replacementSlots).map(([layer, slug]) => <Tag color="purple" key={layer}>{layer} → {slug}</Tag>)}</Space> : '无'}</Descriptions.Item>
        </Descriptions>
      </Card>
      <Row gutter={[14, 14]}>
    {(overview?.core_plugins || []).map(item => <Col xs={24} md={12} xl={8} key={item.slug}>
      <Card style={{ height: '100%' }}>
        <Space align="start" style={{ width: '100%', justifyContent: 'space-between' }}>
          <Space align="start"><CodeOutlined style={{ color: WB.primary, fontSize: 18, marginTop: 3 }} /><div><b>{item.name}</b><div style={{ color: WB.textAux, marginTop: 4 }}>{item.slug} · {item.version}</div></div></Space>
          <StatusTag status={item.status} />
        </Space>
        <div style={{ marginTop: 14 }}><KindTag kind={item.kind} />{!item.removable && <Tag>核心保护</Tag>}</div>
        {item.compatibility_warnings.map(text => <Alert key={text} type="warning" showIcon message={text} style={{ marginTop: 12 }} />)}
      </Card>
    </Col>)}
    {external.filter(item => item.enabled !== false).map(item => <Col xs={24} md={12} xl={8} key={item.slug}>
      <Card style={{ height: '100%', borderColor: `${WB.primary}55` }}>
        <Space align="start" style={{ width: '100%', justifyContent: 'space-between' }}>
          <div><b>{item.name || item.slug}</b><div style={{ color: WB.textAux, marginTop: 4 }}>{item.slug} · {item.version}</div></div>
          <Tag color="cyan">外部审核</Tag>
        </Space>
        <div style={{ marginTop: 14 }}><KindTag kind={item.type} /><Tag>{item.layer || 'runtime'}</Tag>{item.operation === 'replace' && <Tag color="purple">替换插槽</Tag>}</div>
      </Card>
    </Col>)}
      </Row>
    </>;
  };

  const renderTools = () => <Table rowKey="slug" loading={loading} dataSource={overview?.system_tools || []} pagination={false} columns={[
    { title: '工具大类', dataIndex: 'name', render: (_: string, row: PlatformExtensionCatalogItem) => <Space><ToolOutlined style={{ color: WB.primary }} /><div><b>{row.name}</b><div style={{ color: WB.textAux, fontSize: FS.micro }}>{row.description}</div></div></Space> },
    { title: '注册给 DSH 的工具', dataIndex: 'capabilities', render: (values: string[]) => values.length ? <Space wrap>{values.map(value => <Tag key={value}>{value}</Tag>)}</Space> : <Typography.Text type="secondary">运行期动态企业接口</Typography.Text> },
    { title: '状态', dataIndex: 'status', width: 120, render: (value: string) => <StatusTag status={value} /> },
    { title: '作用', width: 160, render: () => <Typography.Text type="secondary">仍经过模式与权限过滤</Typography.Text> },
  ]} />;

  const compatibilityTag = (item: PlatformExtensionCatalogItem) => {
    if (item.compatibility_status === 'compatible') return <Tag color="green">平台兼容</Tag>;
    if (item.compatibility_status === 'needs_adapter') return <Tag color="orange">需要 Codex 适配</Tag>;
    return <Tag color="red">当前不可发布</Tag>;
  };

  const catalogCounts = catalogPageData?.counts || { compatible: 0, adapter: 0, all: 0, installed: 0 };
  const catalogSync = catalogPageData?.sync || {};
  const catalogItems = catalogPageData?.items || [];

  const renderCatalog = () => <>
    <Alert showIcon type="info" style={{ marginBottom: 16 }} message="发现不等于安装" description="社区目录只同步元数据。点击导入后仍会经过隔离构建、人工审核、候选 Context 验证和全局发布；只有正式发布才改变 DSH Runtime。" />
    <Alert
      showIcon
      type={catalogSync.status === 'failed' ? 'error' : catalogSync.stale ? 'warning' : 'success'}
      style={{ marginBottom: 16 }}
      message={catalogSync.status === 'never' ? '尚未同步社区目录' : `目录快照：${catalogSync.status === 'ok' ? '已更新' : catalogSync.status}`}
      description={catalogSync.event_at
        ? `最近同步 ${new Date(catalogSync.event_at).toLocaleString()}；上游 ${Number(catalogSync.upstream_count || 0).toLocaleString()} 项，可用 ${Number(catalogSync.usable_count || catalogSync.community || 0).toLocaleString()} 项，跳过 ${Number(catalogSync.skipped_count || 0).toLocaleString()} 项。`
        : '点击“同步插件目录”获取社区元数据；同步失败时平台会继续使用最近一次成功快照。'}
    />
    <Card style={{ marginBottom: 16 }} styles={{ body: { padding: 16 } }}>
      <Space wrap style={{ width: '100%', justifyContent: 'space-between' }}>
        <Input allowClear prefix={<SearchOutlined />} value={catalogQuery} onChange={event => setCatalogQuery(event.target.value)} placeholder="搜索插件、包名或能力" style={{ width: 320 }} />
        <Space wrap>
          <Select allowClear value={catalogSource || undefined} onChange={value => { setCatalogSource(value || ''); setCatalogPage(1); }} placeholder="来源" style={{ width: 150 }} options={[
            { value: 'official', label: 'DSH 官方' }, { value: 'community', label: '社区目录' }, { value: 'reviewed', label: '平台审核' }, { value: 'external', label: '手工导入' },
          ]} />
          <Select allowClear value={catalogLayer || undefined} onChange={value => { setCatalogLayer(value || ''); setCatalogPage(1); }} placeholder="能力层" style={{ width: 170 }} options={[
            ['coordinator', '协调器'], ['runtime', 'Runtime 基础'], ['memory_context', '记忆/上下文'], ['rag_strategy', 'RAG 策略'], ['system_tool', '系统工具'], ['model_adapter', '模型适配器'], ['hook_guard', 'Hook / Guard'], ['skill_mcp', 'Skill / MCP'], ['ui_plugin', 'UI 插件'], ['library', '运行库'],
          ].map(([value, label]) => ({ value, label }))} />
        </Space>
      </Space>
      <Tabs activeKey={catalogTab} onChange={key => { setCatalogTab(key as typeof catalogTab); setCatalogPage(1); }} style={{ marginTop: 8 }} items={[
        { key: 'compatible', label: `平台兼容 ${catalogCounts.compatible}` },
        { key: 'adapter', label: `待适配 ${catalogCounts.adapter}` },
        { key: 'all', label: `全部社区 ${catalogCounts.all}` },
        { key: 'installed', label: `已安装 ${catalogCounts.installed}` },
      ]} />
    </Card>
    {catalogItems.length ? <>
      <Row gutter={[14, 14]} style={{ marginBottom: 16 }}>
      {catalogItems.map(item => <Col xs={24} md={12} xl={8} key={`${item.source}-${item.id || item.slug}`}>
        <Card loading={catalogLoading} hoverable style={{ height: '100%' }} actions={[
          <Button type="link" key="detail" onClick={() => setCatalogDetail(item)}>查看详情</Button>,
          item.installed
            ? <Typography.Text key="installed" type="success">已安装 {item.installed_version || ''}</Typography.Text>
            : item.id && item.compatibility_status !== 'incompatible'
            ? <Button type="link" icon={<CloudDownloadOutlined />} key="import" onClick={() => openCatalogImport(item)}>{item.compatibility_status === 'compatible' ? '导入候选' : '导入检查'}</Button>
            : <Typography.Text key="readonly" type="secondary">仅供发现</Typography.Text>,
          item.compatibility_status === 'needs_adapter' && item.id
            ? <Button type="link" icon={<DownloadOutlined />} key="adapt" loading={actionLoading === `brief-${item.id}`} onClick={() => void downloadAdaptationBrief(item)}>Codex 适配</Button>
            : null,
        ]}>
          <Space align="start" style={{ width: '100%', justifyContent: 'space-between' }}>
            <div style={{ minWidth: 0 }}><Typography.Text strong ellipsis>{item.name}</Typography.Text><div style={{ color: WB.textAux, fontSize: FS.micro, marginTop: 3 }}>{item.package_name || item.slug} · {item.version || '版本未知'}</div></div>
            {item.source === 'official' ? <Tag color="blue">官方</Tag> : item.source === 'community' ? <Tag>社区</Tag> : <Tag color="cyan">平台审核</Tag>}
          </Space>
          <Typography.Paragraph ellipsis={{ rows: 2 }} style={{ minHeight: 44, margin: '14px 0 10px', color: WB.textAux }}>{item.description || '暂无描述'}</Typography.Paragraph>
          <Space wrap><KindTag kind={item.kind} /><Tag>{item.layer || 'unknown'}</Tag>{item.operation === 'replace' && <Tag color="purple">替换插槽</Tag>}{compatibilityTag(item)}<StatusTag status={item.lifecycle_status} /></Space>
          {!!item.metadata?.stars && <div style={{ marginTop: 12, color: WB.textAux }}>★ {Number(item.metadata.stars).toLocaleString()} · 下载 {Number(item.metadata.downloads || 0).toLocaleString()}</div>}
        </Card>
      </Col>)}
      </Row>
      {catalogPageData && catalogPageData.total > catalogPageData.page_size && <div style={{ display: 'flex', justifyContent: 'center', margin: '4px 0 20px' }}>
        <Pagination current={catalogPageData.page} pageSize={catalogPageData.page_size} total={catalogPageData.total} showSizeChanger={false} onChange={setCatalogPage} showTotal={total => `共 ${total} 项`} />
      </div>}
    </> : <Card loading={catalogLoading} style={{ marginBottom: 16 }}><Empty description="当前筛选下没有插件；首次使用请点击“同步插件目录”" /></Card>}
    <Card title="导入与审核" extra={<Typography.Text type="secondary">Builder 状态 · npm / GitHub / ZIP</Typography.Text>}>
      <Table rowKey="id" loading={loading} dataSource={sources} locale={{ emptyText: <Empty description="尚未导入外部插件" /> }} columns={[
        { title: '来源', render: (_: unknown, row: PlatformExtensionSource) => <div><b>{row.manifest?.name || row.locator}</b><div style={{ color: WB.textAux }}>{row.source_type} · {row.resolved_version || row.requested_version || '待解析'}</div></div> },
        { title: '类型', render: (_: unknown, row: PlatformExtensionSource) => row.manifest?.type ? <KindTag kind={row.manifest.type} /> : '—' },
        { title: '构建', dataIndex: 'status', render: (value: string) => <Space direction="vertical" size={2}><StatusTag status={value} />{value === 'building' && <Progress percent={65} showInfo={false} size="small" status="active" />}</Space> },
        { title: '审核', dataIndex: 'review_status', render: (value: string) => <StatusTag status={value} /> },
        { title: '操作', width: 320, render: (_: unknown, row: PlatformExtensionSource) => <Space wrap>
          <Button size="small" onClick={() => setDetail(row)}>详情</Button>
          {['failed', 'incompatible'].includes(row.status) && <Button size="small" icon={<ReloadOutlined />} loading={actionLoading === `retry-${row.id}`} onClick={() => void runAction(`retry-${row.id}`, () => platformExtensions.retrySource(row.id), '已重新提交隔离构建')}>重试</Button>}
          {row.status === 'review_required' && <Button size="small" type="primary" icon={<CheckCircleOutlined />} loading={actionLoading === `approve-${row.id}`} onClick={() => void runAction(`approve-${row.id}`, () => platformExtensions.approveSource(row.id, true), '已加入审核仓库')}>审核通过</Button>}
          {row.status === 'ready' && row.review_status === 'approved' && <Button size="small" type="primary" icon={<DeploymentUnitOutlined />} onClick={() => openRelease(row.id)}>创建候选</Button>}
        </Space> },
      ]} />
    </Card>
  </>;

  const releaseActions = (_: unknown, row: PlatformExtensionRelease) => <Space wrap>
    {['draft', 'failed'].includes(row.status) && <Button size="small" icon={<SafetyCertificateOutlined />} loading={actionLoading === `validate-${row.id}`} onClick={() => void runAction(`validate-${row.id}`, () => platformExtensions.validateRelease(row.id), '候选验证完成')}>验证</Button>}
    {row.status === 'ready' && <Button size="small" type="primary" icon={<DeploymentUnitOutlined />} loading={actionLoading === `publish-${row.id}`} onClick={() => Modal.confirm({ title: `发布 v${row.version_no}？`, content: '系统会先排空当前任务，再切换 Runtime Context；失败将保留当前版本。', okText: '确认发布', onOk: () => runAction(`publish-${row.id}`, () => platformExtensions.publishRelease(row.id), '发布并健康确认完成') })}>发布</Button>}
    {!row.is_active && ['superseded', 'active'].includes(row.status) && <Button size="small" icon={<RollbackOutlined />} onClick={() => void runAction(`rollback-${row.id}`, () => platformExtensions.rollbackRelease(row.id), '已复制历史快照为新回滚草稿')}>基于此版本回滚</Button>}
  </Space>;

  const releaseDiff = (row: PlatformExtensionRelease) => {
    const current = (overview?.active_release?.manifest?.external_extensions || []) as Array<Record<string, any>>;
    const candidate = (row.manifest?.external_extensions || []) as Array<Record<string, any>>;
    const currentSlugs = new Set(current.filter(item => item.enabled !== false).map(item => String(item.slug)));
    const candidateSlugs = new Set(candidate.filter(item => item.enabled !== false).map(item => String(item.slug)));
    const added = [...candidateSlugs].filter(slug => !currentSlugs.has(slug));
    const removed = [...currentSlugs].filter(slug => !candidateSlugs.has(slug));
    const replacements = Object.entries((row.manifest?.replacement_slots || {}) as Record<string, string>);
    if (!added.length && !removed.length && !replacements.length) return <Typography.Text type="secondary">无扩展差异</Typography.Text>;
    return <Space wrap>{added.map(slug => <Tag color="green" key={`a-${slug}`}>+ {slug}</Tag>)}{removed.map(slug => <Tag color="red" key={`r-${slug}`}>− {slug}</Tag>)}{replacements.map(([layer, slug]) => <Tag color="purple" key={`x-${layer}`}>{layer} → {slug}</Tag>)}</Space>;
  };

  const renderReleases = () => <>
    <Card title="不可变发布版本" style={{ marginBottom: 16 }}>
      <Table rowKey="id" loading={loading} dataSource={releases} columns={[
        { title: '版本', width: 100, render: (_: unknown, row: PlatformExtensionRelease) => <b>v{row.version_no}</b> },
        { title: '名称', dataIndex: 'name' },
        { title: '校验和', dataIndex: 'checksum', render: (value: string) => <Typography.Text code>{value.slice(0, 16)}</Typography.Text> },
        { title: '相对当前版本', render: (_: unknown, row: PlatformExtensionRelease) => releaseDiff(row) },
        { title: '状态', dataIndex: 'status', render: (value: string) => <StatusTag status={value} /> },
        { title: '激活时间', dataIndex: 'activated_at', render: (value: string | null) => value ? new Date(value).toLocaleString() : '—' },
        { title: '操作', width: 230, render: releaseActions },
      ]} />
    </Card>
    <Card title="发布与回滚事件">
      <Timeline items={events.slice(0, 30).map(event => ({
        color: event.status === 'failed' ? 'red' : event.status === 'incompatible' ? 'orange' : 'blue',
        dot: event.event_type.includes('rollback') ? <RollbackOutlined /> : event.event_type.includes('publish') ? <DeploymentUnitOutlined /> : <HistoryOutlined />,
        children: <div><b>{event.event_type}</b> <StatusTag status={event.status} /><div style={{ color: WB.textAux }}>{new Date(event.created_at).toLocaleString()}</div></div>,
      }))} />
    </Card>
  </>;

  return <div style={{ height: '100%', overflow: 'auto', background: '#f7f8fb' }}>
    {header}
    <div style={{ padding: 20, maxWidth: 1500, width: '100%', margin: '0 auto' }}>
      {section === 'overview' && renderOverview()}
      {section === 'runtime' && renderRuntime()}
      {section === 'tools' && renderTools()}
      {section === 'catalog' && renderCatalog()}
      {section === 'releases' && renderReleases()}
    </div>

    <Modal title={`导入候选：${catalogImport?.name || ''}`} open={!!catalogImport} onCancel={() => setCatalogImport(null)} onOk={() => void submitCatalogImport()} confirmLoading={!!catalogImport?.id && actionLoading === `catalog-import-${catalogImport.id}`} okText="导入并隔离构建">
      <Alert type="info" showIcon message="不会立即安装到生产 Runtime" description="该操作只把固定版本导入现有 Builder。构建完成后仍需人工审核、候选验证和正式发布。" style={{ marginBottom: 16 }} />
      <Form form={catalogImportForm} layout="vertical">
        {catalogImport?.package_name && catalogImport?.repository && <Form.Item name="source" label="检查来源" rules={[{ required: true }]}><Select onChange={value => setCatalogImportSource(value)} options={[{ value: 'npm', label: 'npm 精确版本' }, { value: 'github', label: 'GitHub Tag / Commit' }]} /></Form.Item>}
        {catalogImportSource === 'npm' ? <Form.Item name="version" label="精确 npm 版本" rules={[{ required: true, message: '必须固定精确版本' }, { pattern: /^v?\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/, message: '请输入精确语义化版本，不能使用 latest' }]}><Input placeholder="1.2.3" /></Form.Item>
          : <Form.Item name="ref" label="GitHub Tag / Branch / Commit" rules={[{ required: true }]}><Input placeholder="优先使用完整 Commit SHA" /></Form.Item>}
      </Form>
    </Modal>

    <Modal title="导入外部平台插件" open={importOpen} onCancel={() => setImportOpen(false)} onOk={() => void submitImport()} confirmLoading={actionLoading === 'import'} okText="导入并隔离构建" width={640}>
      <Alert type="warning" showIcon message="导入不会自动发布" description="包会在无数据库、OSS长期密钥和模型密钥的 Builder 中构建。只有审核通过的真实 DSH/系统工具插件才能进入候选发布。" style={{ marginBottom: 16 }} />
      <Select value={importType} onChange={value => { setImportType(value); importForm.resetFields(); }} style={{ width: '100%', marginBottom: 16 }} options={[
        { value: 'npm', label: 'npm 包名 + 精确版本' }, { value: 'github', label: 'GitHub 仓库 + Branch/Commit' }, { value: 'archive', label: '上传 ZIP 插件包' },
      ]} />
      <Form form={importForm} layout="vertical">
        {importType === 'npm' && <><Form.Item name="package" label="npm 包名" rules={[{ required: true }]}><Input prefix={<ApiOutlined />} placeholder="@scope/dsh-plugin" /></Form.Item><Form.Item name="version" label="精确版本" rules={[{ required: true }]}><Input placeholder="1.2.3（禁止 latest）" /></Form.Item></>}
        {importType === 'github' && <><Form.Item name="repository" label="GitHub 仓库" rules={[{ required: true }, { type: 'url' }]}><Input prefix={<LinkOutlined />} placeholder="https://github.com/org/repo" /></Form.Item><Form.Item name="ref" label="Branch 或 Commit" rules={[{ required: true }]}><Input placeholder="main 或完整 Commit SHA" /></Form.Item></>}
        {importType === 'archive' && <Upload.Dragger accept=".zip" maxCount={1} beforeUpload={file => { setArchive(file); return false; }} onRemove={() => { setArchive(null); }}><p className="ant-upload-drag-icon"><InboxOutlined /></p><p>点击或拖入 ZIP 插件包</p><p style={{ color: WB.textAux }}>压缩包上限 25MB；解压后限制 250MB / 5000 个条目</p></Upload.Dragger>}
      </Form>
    </Modal>

    <Modal title="创建候选发布" open={releaseOpen} onCancel={() => setReleaseOpen(false)} onOk={() => void submitRelease()} confirmLoading={actionLoading === 'release-create'} okText="创建候选">
      <Form form={releaseForm} layout="vertical">
        <Form.Item name="name" label="发布名称" rules={[{ required: true }]}><Input placeholder="例如：Runtime 稳定版 + 审核工具集" /></Form.Item>
        <Alert type="info" showIcon message="候选版本保存完整快照" description="取消选择已安装插件即表示卸载；选择新的协调器时会自动停用内置 Agent Loop。" style={{ marginBottom: 16 }} />
        <Form.Item name="source_ids" label="启用的已审核外部插件"><Select mode="multiple" placeholder="不选择则只使用平台内置能力" options={approvedSources.map(item => ({ value: item.id, label: `${item.manifest?.name || item.locator} · ${item.resolved_version || ''} · ${item.manifest?.layer || 'runtime'}${item.manifest?.operation === 'replace' ? '（替换）' : ''}` }))} /></Form.Item>
        <Form.Item name="enabled_tool_groups" label="启用的系统工具组"><Select mode="multiple" options={(overview?.system_tools || []).map(item => ({ value: item.slug, label: item.name }))} /></Form.Item>
      </Form>
    </Modal>

    <Drawer width={680} title={detail?.manifest?.name || '插件构建详情'} open={!!detail} onClose={() => setDetail(null)}>
      {detail && <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <Descriptions bordered size="small" column={1}>
          <Descriptions.Item label="来源">{detail.source_type} · {detail.locator}</Descriptions.Item>
          <Descriptions.Item label="构建"><StatusTag status={detail.status} /></Descriptions.Item>
          <Descriptions.Item label="真实类型">{detail.manifest?.type ? <KindTag kind={detail.manifest.type} /> : '未识别'}</Descriptions.Item>
          <Descriptions.Item label="入口">{detail.manifest?.entry || '未确认'}</Descriptions.Item>
          <Descriptions.Item label="SHA-256"><Typography.Text code copyable>{detail.artifact_sha256 || '—'}</Typography.Text></Descriptions.Item>
        </Descriptions>
        {detail.error && <Alert type="error" showIcon icon={<ExclamationCircleOutlined />} message="不能发布" description={detail.error} />}
        {(detail.compatibility?.warnings || []).map((warning: string) => <Alert key={warning} type="warning" showIcon message={warning} />)}
        <Card size="small" title="自动构建报告"><pre style={{ whiteSpace: 'pre-wrap', maxHeight: 360, overflow: 'auto' }}>{JSON.stringify(detail.build_report, null, 2)}</pre></Card>
      </Space>}
    </Drawer>
    <Drawer width={680} title={catalogDetail?.name || '市场插件详情'} open={!!catalogDetail} onClose={() => setCatalogDetail(null)}>
      {catalogDetail && <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <Descriptions bordered size="small" column={1}>
          <Descriptions.Item label="来源">{catalogDetail.source} · {catalogDetail.trust_level}</Descriptions.Item>
          <Descriptions.Item label="包 / 仓库"><Space wrap>{catalogDetail.package_name || '无 npm 包'}{catalogDetail.repository && <Button type="link" size="small" icon={<GithubOutlined />} href={catalogDetail.repository} target="_blank">打开仓库</Button>}</Space></Descriptions.Item>
          <Descriptions.Item label="能力层"><Tag>{catalogDetail.layer}</Tag> {catalogDetail.operation === 'replace' ? <Tag color="purple">替换现有插槽</Tag> : <Tag color="blue">新增能力</Tag>}</Descriptions.Item>
          <Descriptions.Item label="真实类型"><KindTag kind={catalogDetail.kind} /></Descriptions.Item>
          <Descriptions.Item label="兼容性">{compatibilityTag(catalogDetail)}</Descriptions.Item>
          <Descriptions.Item label="安装状态"><StatusTag status={catalogDetail.lifecycle_status} />{catalogDetail.installed_version ? ` · ${catalogDetail.installed_version}` : ''}</Descriptions.Item>
          <Descriptions.Item label="运行要求"><Typography.Text code>{JSON.stringify(catalogDetail.runtime_requirements || {})}</Typography.Text></Descriptions.Item>
        </Descriptions>
        <Typography.Paragraph>{catalogDetail.description || '暂无描述'}</Typography.Paragraph>
        {catalogDetail.compatibility_reasons.map(reason => <Alert key={reason} type={catalogDetail.compatibility_status === 'incompatible' ? 'error' : 'warning'} showIcon message={reason} />)}
        <Space>
          {!catalogDetail.installed && catalogDetail.compatibility_status !== 'incompatible' && catalogDetail.id && <Button type="primary" icon={<CloudDownloadOutlined />} onClick={() => { setCatalogDetail(null); openCatalogImport(catalogDetail); }}>{catalogDetail.compatibility_status === 'compatible' ? '导入候选' : '导入检查'}</Button>}
          {catalogDetail.compatibility_status === 'needs_adapter' && catalogDetail.id && <Button type="primary" icon={<DownloadOutlined />} onClick={() => void downloadAdaptationBrief(catalogDetail)}>生成 Codex 适配任务</Button>}
        </Space>
      </Space>}
    </Drawer>
  </div>;
}
