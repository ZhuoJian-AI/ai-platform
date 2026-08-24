import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  Alert, Button, Card, Col, Descriptions, Drawer, Empty, Form, Input,
  Modal, Progress, Row, Select, Space, Statistic, Table, Tag, Timeline, Typography, Upload, message,
} from 'antd';
import {
  ApiOutlined, CheckCircleOutlined, CloudDownloadOutlined, CloudServerOutlined,
  CodeOutlined, DeploymentUnitOutlined, ExclamationCircleOutlined, HistoryOutlined,
  InboxOutlined, LinkOutlined, PlayCircleOutlined, ReloadOutlined, RollbackOutlined,
  SafetyCertificateOutlined, ToolOutlined,
} from '@ant-design/icons';
import {
  platformExtensions,
  type PlatformExtensionCatalogItem,
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
};

function statusColor(status: string): string {
  if (['active', 'ready', 'approved', 'enabled', 'ok'].includes(status)) return 'green';
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
  const [catalog, setCatalog] = useState<PlatformExtensionCatalogItem[]>([]);
  const [sources, setSources] = useState<PlatformExtensionSource[]>([]);
  const [releases, setReleases] = useState<PlatformExtensionRelease[]>([]);
  const [events, setEvents] = useState<PlatformExtensionEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [releaseOpen, setReleaseOpen] = useState(false);
  const [detail, setDetail] = useState<PlatformExtensionSource | null>(null);
  const [importType, setImportType] = useState<'npm' | 'github' | 'archive'>('npm');
  const [archive, setArchive] = useState<File | null>(null);
  const [importForm] = Form.useForm();
  const [releaseForm] = Form.useForm();

  const refresh = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const [nextOverview, nextCatalog, nextSources, nextReleases, nextEvents] = await Promise.all([
        platformExtensions.overview(), platformExtensions.catalog(), platformExtensions.sources(),
        platformExtensions.releases(), platformExtensions.events(),
      ]);
      setOverview(nextOverview); setCatalog(nextCatalog); setSources(nextSources); setReleases(nextReleases); setEvents(nextEvents);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '平台扩展数据加载失败');
    } finally { if (!quiet) setLoading(false); }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    if (!sources.some(item => ['importing', 'building'].includes(item.status))) return;
    const timer = window.setInterval(() => void refresh(true), 2500);
    return () => window.clearInterval(timer);
  }, [sources, refresh]);

  const approvedSources = useMemo(() => sources.filter(item => item.status === 'ready' && item.review_status === 'approved'), [sources]);

  const runAction = async (key: string, action: () => Promise<unknown>, success: string) => {
    setActionLoading(key);
    try { await action(); message.success(success); await refresh(true); }
    catch (error) {
      message.error(error instanceof Error ? error.message : '操作失败');
      await refresh(true);
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
        {section === 'catalog' && <Button type="primary" icon={<CloudDownloadOutlined />} onClick={() => setImportOpen(true)}>导入外部插件</Button>}
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

  const renderRuntime = () => <Row gutter={[14, 14]}>
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
  </Row>;

  const renderTools = () => <Table rowKey="slug" loading={loading} dataSource={overview?.system_tools || []} pagination={false} columns={[
    { title: '工具大类', dataIndex: 'name', render: (_: string, row: PlatformExtensionCatalogItem) => <Space><ToolOutlined style={{ color: WB.primary }} /><div><b>{row.name}</b><div style={{ color: WB.textAux, fontSize: FS.micro }}>{row.description}</div></div></Space> },
    { title: '注册给 DSH 的工具', dataIndex: 'capabilities', render: (values: string[]) => values.length ? <Space wrap>{values.map(value => <Tag key={value}>{value}</Tag>)}</Space> : <Typography.Text type="secondary">运行期动态企业接口</Typography.Text> },
    { title: '状态', dataIndex: 'status', width: 120, render: (value: string) => <StatusTag status={value} /> },
    { title: '作用', width: 160, render: () => <Typography.Text type="secondary">仍经过模式与权限过滤</Typography.Text> },
  ]} />;

  const renderCatalog = () => <>
    <Card title="平台审核仓库" extra={<Tag color="blue">当前基线能力</Tag>} style={{ marginBottom: 16 }}>
      <Table rowKey={(row) => `${row.source}-${row.slug}`} size="small" pagination={false} dataSource={catalog.filter(item => item.source !== 'external')} columns={[
        { title: '扩展', render: (_: unknown, row: PlatformExtensionCatalogItem) => <div><b>{row.name}</b><div style={{ color: WB.textAux }}>{row.slug} · {row.version}</div></div> },
        { title: '真实类型', dataIndex: 'kind', render: (value: string) => <KindTag kind={value} /> },
        { title: '状态', dataIndex: 'status', render: (value: string) => <StatusTag status={value} /> },
      ]} />
    </Card>
    <Card title="外部导入" extra={<Typography.Text type="secondary">npm / GitHub / ZIP</Typography.Text>}>
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

  const renderReleases = () => <>
    <Card title="不可变发布版本" style={{ marginBottom: 16 }}>
      <Table rowKey="id" loading={loading} dataSource={releases} columns={[
        { title: '版本', width: 100, render: (_: unknown, row: PlatformExtensionRelease) => <b>v{row.version_no}</b> },
        { title: '名称', dataIndex: 'name' },
        { title: '校验和', dataIndex: 'checksum', render: (value: string) => <Typography.Text code>{value.slice(0, 16)}</Typography.Text> },
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
        <Form.Item name="source_ids" label="启用的已审核外部插件"><Select mode="multiple" placeholder="不选择则只使用平台内置能力" options={approvedSources.map(item => ({ value: item.id, label: `${item.manifest?.name || item.locator} · ${item.resolved_version || ''}` }))} /></Form.Item>
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
  </div>;
}
