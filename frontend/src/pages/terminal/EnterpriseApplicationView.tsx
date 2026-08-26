import { useEffect, useState } from 'react';
import { Alert, Button, Drawer, Empty, Input, Result, Space, Spin, Tag, Tooltip, Typography } from 'antd';
import { ExportOutlined, ReloadOutlined, RobotOutlined, SendOutlined } from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { ApiError, terminal, type TerminalEnterpriseApplication } from '../../api/client';

export default function EnterpriseApplicationView({
  application,
  onAskAI,
}: {
  application: TerminalEnterpriseApplication;
  onAskAI: (prompt: string, pageContext: Record<string, unknown>) => void;
}) {
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [prompt, setPrompt] = useState('');
  const [frameKey, setFrameKey] = useState(0);
  const [frameLoaded, setFrameLoaded] = useState(false);
  const [frameSlow, setFrameSlow] = useState(false);
  const { data: launch, isLoading, error, refetch } = useQuery({
    queryKey: ['terminal-application-launch', application.id],
    queryFn: () => terminal.launchApplication(application.id),
    retry: false,
  });

  useEffect(() => {
    setFrameLoaded(false); setFrameSlow(false);
    const timer = window.setTimeout(() => setFrameSlow(true), 8000);
    return () => window.clearTimeout(timer);
  }, [application.id, frameKey]);

  const submit = () => {
    const value = prompt.trim();
    if (!value) return;
    onAskAI(value, {
      application_id: application.id,
      application_slug: application.slug,
      application_name: application.name,
      page_url: launch?.url,
      source: 'business_assistant',
    });
    setPrompt(''); setAssistantOpen(false);
  };

  if (isLoading) return <div style={{ flex: 1, display: 'grid', placeItems: 'center' }}><Spin tip="正在校验应用权限…" /></div>;
  if (error) {
    const forbidden = error instanceof ApiError && error.status === 403;
    return <Result status={forbidden ? '403' : 'error'} title={forbidden ? '无权访问该应用' : '应用加载失败'} subTitle={forbidden ? '当前账号没有此企业模块的 view 权限。' : (error as Error).message} extra={<Button onClick={() => refetch()}>重试</Button>} />;
  }
  if (!launch) return <Empty description="应用入口不可用" />;

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', background: '#f6f7fb' }}>
      <div style={{ height: 54, flex: '0 0 auto', display: 'flex', alignItems: 'center', gap: 10, padding: '0 16px', background: '#fff', borderBottom: '1px solid #e5e7eb' }}>
        <div style={{ width: 30, height: 30, borderRadius: 9, background: '#eef2ff', color: '#6366f1', display: 'grid', placeItems: 'center', overflow: 'hidden' }}>
          {application.icon_url ? <img src={application.icon_url} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} /> : application.name.slice(0, 1)}
        </div>
        <div style={{ minWidth: 0 }}><Typography.Text strong>{application.name}</Typography.Text><div style={{ fontSize: 11, color: '#9ca3af' }}>{application.description || '企业业务应用'}</div></div>
        <Tag color="blue" style={{ marginLeft: 4 }}>{launch.display_mode === 'embedded' ? '平台内嵌' : '独立应用'}</Tag>
        <div style={{ flex: 1 }} />
        {launch.display_mode === 'embedded' && <Tooltip title="重新加载模块"><Button icon={<ReloadOutlined />} onClick={() => setFrameKey((value) => value + 1)} /></Tooltip>}
        <Button icon={<ExportOutlined />} onClick={() => window.open(launch.url, '_blank', 'noopener,noreferrer')}>备用打开</Button>
        {application.assistant_enabled && <Button type="primary" icon={<RobotOutlined />} onClick={() => setAssistantOpen(true)}>业务小助手</Button>}
      </div>

      {launch.display_mode === 'embedded' ? (
        <div style={{ flex: 1, minHeight: 0, position: 'relative', padding: 10 }}>
          {!frameLoaded && <div style={{ position: 'absolute', inset: 10, zIndex: 1, display: 'grid', placeItems: 'center', background: '#fff' }}><Spin tip={frameSlow ? '应用响应较慢，可尝试“备用打开”' : '正在加载业务应用…'} /></div>}
          <iframe key={frameKey} src={launch.url} title={application.name} onLoad={() => setFrameLoaded(true)} style={{ width: '100%', height: '100%', border: '1px solid #e5e7eb', borderRadius: 12, background: '#fff', boxShadow: '0 8px 30px rgba(15,23,42,.06)' }} />
          {frameSlow && !frameLoaded && <Alert showIcon type="warning" message="该项目可能禁止 iframe 嵌入" description="可使用右上角“备用打开”。若希望内嵌，需要独立项目允许 AI Platform 域名的 frame-ancestors。" style={{ position: 'absolute', left: 30, right: 30, bottom: 30, zIndex: 2 }} />}
        </div>
      ) : (
        <div style={{ flex: 1, display: 'grid', placeItems: 'center' }}><Result icon={<ExportOutlined style={{ color: '#6366f1' }} />} title={`${application.name} 配置为独立打开`} subTitle="应用仍由原项目独立部署和迭代；AI Platform 负责权限、导航和业务助手。" extra={<Button type="primary" onClick={() => window.open(launch.url, '_blank', 'noopener,noreferrer')}>打开应用</Button>} /></div>
      )}

      <Drawer title={<Space><RobotOutlined style={{ color: '#6366f1' }} />{application.name} · 业务小助手</Space>} open={assistantOpen} onClose={() => setAssistantOpen(false)} width={400}>
        <Alert showIcon type="info" message="助手会携带当前应用上下文" description="只会注册你在该应用中获准的查询、新增、更新、删除工具。" style={{ marginBottom: 18 }} />
        <Typography.Paragraph type="secondary">你可以问：</Typography.Paragraph>
        <Space direction="vertical" style={{ width: '100%', marginBottom: 16 }}>
          {['汇总当前页面异常并给出处理建议', '查询今天待处理的业务记录', '根据当前业务数据生成一份 Excel'].map((item) => <Button key={item} block style={{ textAlign: 'left' }} onClick={() => setPrompt(item)}>{item}</Button>)}
        </Space>
        <Input.TextArea value={prompt} onChange={(event) => setPrompt(event.target.value)} rows={6} placeholder="描述你要查询或执行的业务任务…" onPressEnter={(event) => { if (!event.shiftKey) { event.preventDefault(); submit(); } }} />
        <Button type="primary" block icon={<SendOutlined />} disabled={!prompt.trim()} onClick={submit} style={{ marginTop: 12 }}>交给业务小助手</Button>
      </Drawer>
    </div>
  );
}
