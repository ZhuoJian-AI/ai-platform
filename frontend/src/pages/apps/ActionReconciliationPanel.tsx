import { useState } from 'react';
import { Alert, Button, Card, Form, Input, Modal, Select, Table, Tag } from 'antd';
import { useMutation, useQuery } from '@tanstack/react-query';
import { ApiError, enterpriseApplications, type ActionReconciliation } from '../../api/client';

export default function ActionReconciliationPanel({ appId }: { appId: string }) {
  const [selected, setSelected] = useState<ActionReconciliation | null>(null);
  const [form] = Form.useForm();
  const query = useQuery({ queryKey: ['action-reconciliations', appId], queryFn: () => enterpriseApplications.reconciliations(appId) });
  const mutation = useMutation({
    mutationFn: (values: { decision: 'executed' | 'not_executed'; evidence: string }) =>
      enterpriseApplications.reconcile(appId, selected!.id, values.decision, values.evidence),
    onSuccess: () => { setSelected(null); void query.refetch(); },
  });
  return <Card title="结果未知的业务写入核实" extra={<Button onClick={() => void query.refetch()}>刷新</Button>}>
    <Alert type="warning" showIcon message="先在业务系统核对回执或实际记录，再提交证据"
      description="这里不会执行业务操作。确认已执行后禁止重复写入；确认未执行后需重新生成用户确认卡片。无法确定时请保持待核实。执行中的请求不允许人工覆盖。" />
    {query.isError && <Alert type="error" message={query.error instanceof ApiError ? query.error.message : '核实记录加载失败'} />}
    <Table<ActionReconciliation> rowKey="id" loading={query.isLoading} dataSource={query.data ?? []} pagination={{ pageSize: 10 }}
      expandable={{ expandedRowRender: row => <div>操作标识：{row.request_id}<br />员工标识：{row.user_id}<br />
        {row.reconciliation ? <>证据：{row.reconciliation.evidence}<br />核实管理员：{row.reconciliation.admin_id}；时间：{row.reconciliation.verified_at}</> : '尚无核实结论'}</div> }}
      columns={[
        { title: '操作', dataIndex: 'action_name' }, { title: '模块', dataIndex: 'module_key' },
        { title: '发起时间', render: (_, row) => new Date(row.created_at).toLocaleString('zh-CN') },
        { title: '状态', render: (_, row) => <Tag>{row.reconciliation ? (row.reconciliation.decision === 'executed' ? '人工核实已执行' : '人工核实未执行') : row.status === 'executing' ? '执行中／待回执' : '待核实'}</Tag> },
        { title: '核实', render: (_, row) => <Button disabled={row.status !== 'failed' || !!row.reconciliation} onClick={() => { mutation.reset(); form.resetFields(); setSelected(row); }}>提交证据</Button> },
      ]} />
    <Modal title={`核实：${selected?.action_name ?? ''}`} open={!!selected} onCancel={() => setSelected(null)}
      confirmLoading={mutation.isPending} onOk={() => form.submit()} okText="记录核实结论" cancelText="保持待核实">
      <Alert type="info" message="请填写回执编号、业务记录标识、核查时间及依据，不要填写密码或密钥。此结论不能覆盖修改。" />
      <Form form={form} layout="vertical" onFinish={values => mutation.mutate(values)}>
        <Form.Item name="decision" label="核实结论" rules={[{ required: true, message: '请选择有证据支持的结论' }]}>
          <Select options={[{ value: 'executed', label: '已核实执行成功' }, { value: 'not_executed', label: '已核实没有执行' }]} />
        </Form.Item>
        <Form.Item name="evidence" label="核查证据" rules={[{ required: true, whitespace: true, message: '请填写核查证据' }]}>
          <Input.TextArea rows={4} maxLength={4000} />
        </Form.Item>
      </Form>
      {mutation.isError && <Alert type="error" message={mutation.error instanceof ApiError ? mutation.error.message : '核实失败，请刷新后检查状态'} />}
    </Modal>
  </Card>;
}
