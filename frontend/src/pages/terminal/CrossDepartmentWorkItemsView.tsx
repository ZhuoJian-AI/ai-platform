import { Button, Card, Empty, Space, Spin, Tag, Typography, message } from 'antd';
import { CheckCircleOutlined, ClockCircleOutlined, ReloadOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { terminal, type CrossDepartmentWorkItem } from '../../api/client';

export default function CrossDepartmentWorkItemsView() {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ['cross-department-work-items'],
    queryFn: () => terminal.crossDepartmentWorkItems(),
    refetchInterval: 30_000,
  });
  const update = useMutation({
    mutationFn: ({ id, status }: { id: string; status: 'open' | 'done' }) =>
      terminal.updateCrossDepartmentWorkItem(id, status),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['cross-department-work-items'] }),
    onError: () => message.error('待办状态更新失败'),
  });
  if (query.isLoading) return <div style={{ flex: 1, display: 'grid', placeItems: 'center' }}><Spin tip="正在加载跨部门待办…" /></div>;
  const items = query.data ?? [];
  const open = items.filter((item) => item.status === 'open');
  const done = items.filter((item) => item.status === 'done');
  const renderItem = (item: CrossDepartmentWorkItem) => (
    <Card key={item.id} size="small" style={{ marginBottom: 10 }}>
      <Space align="start" style={{ width: '100%', justifyContent: 'space-between' }}>
        <div>
          <Space><Typography.Text strong>{item.title}</Typography.Text><Tag color={item.status === 'open' ? 'orange' : 'green'}>{item.status === 'open' ? '待处理' : '已完成'}</Tag></Space>
          <div style={{ marginTop: 6 }}>
            <Typography.Text type="secondary">
              {String(item.source_context.module_key || '业务系统')} · {String(item.source_context.event_type || item.source_event_id)} · {new Date(item.created_at).toLocaleString('zh-CN')}
            </Typography.Text>
          </div>
        </div>
        <Button
          size="small" icon={item.status === 'open' ? <CheckCircleOutlined /> : <ClockCircleOutlined />}
          loading={update.isPending} onClick={() => update.mutate({ id: item.id, status: item.status === 'open' ? 'done' : 'open' })}
        >{item.status === 'open' ? '标记完成' : '重新打开'}</Button>
      </Space>
    </Card>
  );
  return (
    <div style={{ flex: 1, overflow: 'auto', padding: 24, background: '#f7f8fc' }}>
      <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 18 }}>
        <div><Typography.Title level={3} style={{ margin: 0 }}>跨部门待办</Typography.Title><Typography.Text type="secondary">来自各部门独立系统的业务事件，经企业管理员规则自动分发。</Typography.Text></div>
        <Button icon={<ReloadOutlined />} onClick={() => query.refetch()}>刷新</Button>
      </Space>
      {!items.length ? <Empty description="暂无跨部门待办；子系统事件同步并命中路由规则后会自动出现。" /> : <>
        <Typography.Title level={5}>待处理（{open.length}）</Typography.Title>
        {open.length ? open.map(renderItem) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前没有待处理事项" />}
        {!!done.length && <><Typography.Title level={5} style={{ marginTop: 24 }}>已完成（{done.length}）</Typography.Title>{done.map(renderItem)}</>}
      </>}
    </div>
  );
}
