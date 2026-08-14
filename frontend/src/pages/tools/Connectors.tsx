import { useState, useEffect } from 'react';
import {
  Button, Card, Modal, Table, Tag, Form, Input, Select, Typography, Space,
  message,
} from 'antd';
import { PlusOutlined, DeleteOutlined, EditOutlined, ImportOutlined, ThunderboltOutlined, ApiOutlined } from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { connectors } from '../../api/client';
import type { ToolConnector, ToolEndpoint, ToolTestResult } from '../../api/client';
import { ApiError } from '../../api/client';
import BoundNodeSlugSelect from '../../components/BoundNodeSlugSelect';
import OrgSelect from '../../components/OrgSelect';
import JsonEditor from '../../components/JsonEditor';
import { FinderShell, TitleBar } from '../../components/finder/primitives';
import ConfirmModal from '../../components/finder/ConfirmModal';

const TYPE_LABELS: Record<string, string> = { erp: 'ERP', crm: 'CRM', hrm: 'HRM', other: '其他' };

export default function Connectors() {
  const qc = useQueryClient();
  const [orgId, setOrgId] = useState<string | undefined>();
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<ToolConnector | null>(null);
  const [form] = Form.useForm();

  const [endpointsConn, setEndpointsConn] = useState<ToolConnector | null>(null);
  const [testEp, setTestEp] = useState<ToolEndpoint | null>(null);
  const [testParams, setTestParams] = useState<unknown>({});
  const [testResult, setTestResult] = useState<ToolTestResult | null>(null);
  const [confirm, setConfirm] = useState<{ id: string; name: string } | null>(null);

  const { data: list, isLoading } = useQuery({
    queryKey: ['connectors', orgId],
    queryFn: () => orgId ? connectors.list(orgId) : Promise.resolve([]),
    enabled: !!orgId,
  });

  const { data: endpoints } = useQuery({
    queryKey: ['connector-endpoints', endpointsConn?.id],
    queryFn: () => endpointsConn ? connectors.listEndpoints(endpointsConn.id) : Promise.resolve([]),
    enabled: !!endpointsConn,
  });

  const isEdit = !!editing;
  const openCreate = () => { setEditing(null); form.resetFields(); setModalOpen(true); };
  const openEdit = (r: ToolConnector) => { setEditing(r); setModalOpen(true); };
  useEffect(() => {
    if (modalOpen && editing) form.setFieldsValue({ ...editing, auth_config: {}, spec: editing.spec });
  }, [modalOpen, editing, form]);

  const save = useMutation({
    mutationFn: (v: Record<string, unknown>) => {
      if (!orgId) return Promise.reject(new Error('no org'));
      return isEdit && editing ? connectors.update(editing.id, v) : connectors.create(orgId, v);
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['connectors'] }); setModalOpen(false); message.success('已保存'); },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '保存失败'),
  });
  const del = useMutation({
    mutationFn: (id: string) => connectors.delete(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['connectors'] }); message.success('已删除'); },
    onError: () => message.error('删除失败'),
  });
  const importSpec = useMutation({
    mutationFn: (id: string) => connectors.importSpec(id),
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ['connector-endpoints'] }); message.success(`已导入 ${r.length} 个端点`); },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '导入失败'),
  });

  const runTest = useMutation({
    mutationFn: () => testEp ? connectors.testEndpoint(testEp.id, testParams as Record<string, unknown>) : Promise.reject(new Error('no ep')),
    onSuccess: (r) => setTestResult(r),
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '调用失败'),
  });

  return (
    <FinderShell>
      <TitleBar
        icon={<ApiOutlined />}
        title="连接器"
        titleExtra={<OrgSelect value={orgId} onChange={setOrgId} />}
        extra={<Button type="primary" icon={<PlusOutlined />} onClick={openCreate} disabled={!orgId}>新建连接器</Button>}
      />

      <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
        <Table
          dataSource={list ?? []} rowKey="id" loading={isLoading} pagination={{ pageSize: 20 }}
          columns={[
            { title: '名称', dataIndex: 'name', width: 180 },
            { title: '类型', dataIndex: 'type', width: 90, render: (v: string) => <Tag>{TYPE_LABELS[v] || v}</Tag> },
            { title: 'Base URL', dataIndex: 'base_url', ellipsis: true },
            { title: '鉴权', dataIndex: 'auth_type', width: 90 },
            { title: '健康', dataIndex: 'health_status', width: 90, render: (v: string) => <Tag>{v}</Tag> },
            { title: '操作', width: 280, fixed: 'right', render: (_: unknown, r: ToolConnector) => (
              <Space size="small">
                <Button size="small" onClick={() => setEndpointsConn(r)}>端点</Button>
                <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(r)}>编辑</Button>
                <Button size="small" danger icon={<DeleteOutlined />} onClick={() => setConfirm({ id: r.id, name: r.name })}>删除</Button>
              </Space>
            )},
          ]}
        />
      </div>

      <Modal title={isEdit ? '编辑连接器' : '新建连接器'} open={modalOpen}
        onCancel={() => setModalOpen(false)} onOk={() => form.submit()} confirmLoading={save.isPending} width={720}
        destroyOnClose>
        <Form form={form} layout="vertical" onFinish={(v) => save.mutate(v)} initialValues={{ type: 'other', auth_type: 'none', is_active: true, spec: {} }}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="slug" label="Slug（绑定节点）" rules={[{ required: true, message: '请选择绑定节点' }]}>
            {isEdit ? <Input disabled /> : <BoundNodeSlugSelect orgId={orgId} />}
          </Form.Item>
          <Form.Item name="type" label="类型" rules={[{ required: true }]}>
            <Select options={[{ value: 'erp', label: 'ERP' }, { value: 'crm', label: 'CRM' }, { value: 'hrm', label: 'HRM' }, { value: 'other', label: '其他' }]} />
          </Form.Item>
          <Form.Item name="base_url" label="Base URL" rules={[{ required: true }]}><Input placeholder="https://erp.example.com" /></Form.Item>
          <Form.Item name="auth_type" label="鉴权方式">
            <Select options={['none', 'basic', 'bearer', 'apikey', 'oauth'].map((v) => ({ value: v, label: v }))} />
          </Form.Item>
          <Form.Item name="auth_config" label="鉴权配置（JSON，加密落库）">
            <JsonEditor value={{}} onChange={(v) => form.setFieldValue('auth_config', v)} rows={3} />
          </Form.Item>
          <Form.Item name="spec" label="OpenAPI Spec（JSON，可后导入端点）">
            <JsonEditor value={{}} onChange={(v) => form.setFieldValue('spec', v)} rows={5} placeholder="{}" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title={`端点 · ${endpointsConn?.name ?? ''}`} open={!!endpointsConn}
        onCancel={() => setEndpointsConn(null)} footer={null} width={820}>
        <Space style={{ marginBottom: 12 }}>
          <Button icon={<ImportOutlined />} onClick={() => endpointsConn && importSpec.mutate(endpointsConn.id)} loading={importSpec.isPending}>
            从 Spec 导入端点
          </Button>
        </Space>
        <Table
          dataSource={endpoints ?? []} rowKey="id" size="small" pagination={{ pageSize: 10 }}
          columns={[
            { title: '名称', dataIndex: 'name' },
            { title: '方法', dataIndex: 'method', width: 70, render: (v: string) => <Tag color="blue">{v}</Tag> },
            { title: '路径', dataIndex: 'path', ellipsis: true },
            { title: '操作', width: 100, render: (_: unknown, ep: ToolEndpoint) => (
              <Button size="small" icon={<ThunderboltOutlined />} onClick={() => { setTestEp(ep); setTestParams({}); setTestResult(null); }}>测试</Button>
            )},
          ]}
        />
      </Modal>

      <Modal title={`端点测试 · ${testEp?.name ?? ''}`} open={!!testEp}
        onCancel={() => setTestEp(null)} footer={null} width={680}>
        <Typography.Text type="secondary">参数（JSON）</Typography.Text>
        <div style={{ marginTop: 8 }}>
          <JsonEditor value={testParams} onChange={setTestParams} rows={4} placeholder="{}" />
        </div>
        <Button type="primary" style={{ marginTop: 12 }} icon={<ThunderboltOutlined />} loading={runTest.isPending} onClick={() => runTest.mutate()}>
          调用
        </Button>
        {testResult && (
          <Card size="small" title="结果" style={{ marginTop: 12 }}>
            <Space style={{ marginBottom: 8 }}>
              <Tag color={testResult.error ? 'red' : (testResult.status_code && testResult.status_code < 400 ? 'green' : 'orange')}>
                {testResult.status_code ?? 'ERR'}
              </Tag>
              <Tag>{testResult.latency_ms} ms</Tag>
              {testResult.error && <Typography.Text type="danger">{testResult.error}</Typography.Text>}
            </Space>
            <pre style={{ maxHeight: 300, overflow: 'auto', fontSize: 12, background: '#f5f5f5', padding: 8 }}>
              {JSON.stringify(testResult.body, null, 2)}
            </pre>
          </Card>
        )}
      </Modal>

      <ConfirmModal
        open={!!confirm}
        title={<>确定删除连接器「{confirm?.name}」？</>}
        okText="删除"
        loading={del.isPending}
        onCancel={() => setConfirm(null)}
        onOk={() => { if (confirm) del.mutate(confirm.id); setConfirm(null); }}
      />
    </FinderShell>
  );
}
