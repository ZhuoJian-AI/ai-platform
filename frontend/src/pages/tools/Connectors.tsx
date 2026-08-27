import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Button, Card, Modal, Table, Tag, Form, Input, Select, Typography, Space,
  message, Switch, Alert,
} from 'antd';
import {
  PlusOutlined, DeleteOutlined, EditOutlined, ImportOutlined,
  ThunderboltOutlined, ApiOutlined, RocketOutlined,
} from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { connectors } from '../../api/client';
import type { ToolConnector, ToolEndpoint, ToolTestResult } from '../../api/client';
import { ApiError } from '../../api/client';
import OrgSelect from '../../components/OrgSelect';
import JsonEditor from '../../components/JsonEditor';
import { FinderShell, TitleBar } from '../../components/finder/primitives';
import ConfirmModal from '../../components/finder/ConfirmModal';
import ConnectorOnboardingWizard from './ConnectorOnboardingWizard';

const TYPE_LABELS: Record<string, string> = {
  erp: 'ERP', mes: 'MES', crm: 'CRM', hrm: 'HRM', scm: 'SCM', other: '其他',
};

const slugify = (value: string) => value
  .toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 100);

export default function Connectors() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [orgId, setOrgId] = useState<string | undefined>();
  const [onboardingOpen, setOnboardingOpen] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<ToolConnector | null>(null);
  const [form] = Form.useForm();

  const [endpointsConn, setEndpointsConn] = useState<ToolConnector | null>(null);
  const [editingEndpoint, setEditingEndpoint] = useState<ToolEndpoint | null>(null);
  const [endpointModalOpen, setEndpointModalOpen] = useState(false);
  const [selectedEndpointIds, setSelectedEndpointIds] = useState<string[]>([]);
  const [publishOpen, setPublishOpen] = useState(false);
  const [testEp, setTestEp] = useState<ToolEndpoint | null>(null);
  const [testParams, setTestParams] = useState<unknown>({});
  const [testResult, setTestResult] = useState<ToolTestResult | null>(null);
  const [confirm, setConfirm] = useState<{ id: string; name: string } | null>(null);
  const [endpointConfirm, setEndpointConfirm] = useState<{ id: string; name: string } | null>(null);
  const [endpointForm] = Form.useForm();
  const [publishForm] = Form.useForm();
  const authConfig = Form.useWatch('auth_config', form);
  const connectorSpec = Form.useWatch('spec', form);
  const endpointParamsSchema = Form.useWatch('params_schema', endpointForm);
  const endpointResponseSchema = Form.useWatch('response_schema', endpointForm);

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
  const openCreate = () => { setEditing(null); setModalOpen(true); };
  const openEdit = (r: ToolConnector) => { setEditing(r); setModalOpen(true); };
  useEffect(() => {
    if (!modalOpen) return;
    if (editing) {
      form.setFieldsValue({ ...editing, auth_config: undefined, spec: editing.spec });
    } else {
      form.resetFields();
      form.setFieldsValue({ type: 'other', auth_type: 'none', is_active: true, spec: {} });
    }
  }, [modalOpen, editing, form]);

  const openCreateEndpoint = () => {
    setEditingEndpoint(null);
    setEndpointModalOpen(true);
  };
  const openEditEndpoint = (endpoint: ToolEndpoint) => {
    setEditingEndpoint(endpoint);
    setEndpointModalOpen(true);
  };
  useEffect(() => {
    if (!endpointModalOpen) return;
    if (editingEndpoint) {
      endpointForm.setFieldsValue(editingEndpoint);
    } else {
      endpointForm.resetFields();
      endpointForm.setFieldsValue({ method: 'GET', params_schema: {}, response_schema: {}, is_active: true });
    }
  }, [endpointModalOpen, editingEndpoint, endpointForm]);

  const save = useMutation({
    mutationFn: (v: Record<string, unknown>) => {
      if (!orgId) return Promise.reject(new Error('no org'));
      const payload = { ...v };
      if (isEdit && (!payload.auth_config || Object.keys(payload.auth_config as object).length === 0)) {
        delete payload.auth_config;
      }
      return isEdit && editing ? connectors.update(editing.id, payload) : connectors.create(orgId, payload);
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

  const saveEndpoint = useMutation({
    mutationFn: (values: Record<string, unknown>) => {
      if (!endpointsConn) return Promise.reject(new Error('no connector'));
      return editingEndpoint
        ? connectors.updateEndpoint(editingEndpoint.id, values)
        : connectors.createEndpoint(endpointsConn.id, values);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['connector-endpoints', endpointsConn?.id] });
      setEndpointModalOpen(false);
      message.success('端点已保存');
    },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '端点保存失败'),
  });
  const deleteEndpoint = useMutation({
    mutationFn: (id: string) => connectors.deleteEndpoint(id),
    onSuccess: (_data, deletedId) => {
      qc.invalidateQueries({ queryKey: ['connector-endpoints', endpointsConn?.id] });
      setSelectedEndpointIds((ids) => ids.filter((id) => id !== deletedId));
      message.success('端点已删除');
    },
    onError: () => message.error('端点删除失败'),
  });
  const publishSkill = useMutation({
    mutationFn: (values: { name: string; slug: string; description?: string }) => {
      if (!endpointsConn) return Promise.reject(new Error('no connector'));
      return connectors.publishSkill(endpointsConn.id, { ...values, endpoint_ids: selectedEndpointIds });
    },
    onSuccess: (folder) => {
      setPublishOpen(false);
      setSelectedEndpointIds([]);
      message.success(`技能“${folder.name}”已发布，组织成员可在聊天中调用`);
    },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '技能发布失败'),
  });

  const openPublish = () => {
    if (!endpointsConn || selectedEndpointIds.length === 0) return;
    setPublishOpen(true);
  };
  useEffect(() => {
    if (!publishOpen || !endpointsConn) return;
    publishForm.setFieldsValue({
      name: `${endpointsConn.name}助手`,
      slug: slugify(`${endpointsConn.slug}-api`),
      description: `查询和操作${endpointsConn.name}中的企业数据`,
    });
  }, [publishOpen, endpointsConn, publishForm]);

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
        extra={<Space>
          <Button icon={<PlusOutlined />} onClick={openCreate} disabled={!orgId}>高级新建</Button>
          <Button type="primary" icon={<RocketOutlined />} onClick={() => setOnboardingOpen(true)} disabled={!orgId}>接入业务系统</Button>
        </Space>}
      />

      <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message="用“接入业务系统”向导一次完成页面入口、REST API、部门权限和 AI Skill。"
          description="连接器负责真实调用企业 API；数据接口页面只展示接口说明，不会发起请求。熟悉接口配置的管理员仍可使用“高级新建”。"
        />
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
        forceRender>
        <Form form={form} layout="vertical" onFinish={(v) => save.mutate(v)} initialValues={{ type: 'other', auth_type: 'none', is_active: true, spec: {} }}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item
            name="slug" label="Slug"
            rules={[{ required: true }, { pattern: /^[a-z0-9]+(?:-[a-z0-9]+)*$/, message: '只能使用小写字母、数字和连字符' }]}
          >
            <Input disabled={isEdit} placeholder="company-erp" />
          </Form.Item>
          <Form.Item name="description" label="系统说明"><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="type" label="类型" rules={[{ required: true }]}>
            <Select options={[
              { value: 'erp', label: 'ERP' }, { value: 'mes', label: 'MES' },
              { value: 'crm', label: 'CRM' }, { value: 'hrm', label: 'HRM' },
              { value: 'scm', label: 'SCM' }, { value: 'other', label: '其他' },
            ]} />
          </Form.Item>
          <Form.Item name="base_url" label="Base URL" rules={[{ required: true }]}><Input placeholder="https://erp.example.com" /></Form.Item>
          <Form.Item name="auth_type" label="鉴权方式">
            <Select options={['none', 'basic', 'bearer', 'apikey', 'oauth'].map((v) => ({ value: v, label: v }))} />
          </Form.Item>
          <Form.Item name="auth_config" label={isEdit ? '鉴权配置（JSON，留空则保持原配置）' : '鉴权配置（JSON，加密落库）'}>
            <JsonEditor value={authConfig} onChange={(v) => form.setFieldValue('auth_config', v)} rows={3} />
          </Form.Item>
          <Form.Item name="spec" label="OpenAPI Spec（JSON，可后导入端点）">
            <JsonEditor value={connectorSpec} onChange={(v) => form.setFieldValue('spec', v)} rows={5} placeholder="{}" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title={`端点 · ${endpointsConn?.name ?? ''}`} open={!!endpointsConn}
        onCancel={() => { setEndpointsConn(null); setSelectedEndpointIds([]); }} footer={null} width={980}>
        <Space style={{ marginBottom: 12 }}>
          <Button icon={<ImportOutlined />} onClick={() => endpointsConn && importSpec.mutate(endpointsConn.id)} loading={importSpec.isPending}>
            从 Spec 导入端点
          </Button>
          <Button icon={<PlusOutlined />} onClick={openCreateEndpoint}>手工添加端点</Button>
          <Button type="primary" icon={<RocketOutlined />} disabled={selectedEndpointIds.length === 0} onClick={openPublish}>
            发布为 Skill{selectedEndpointIds.length ? `（${selectedEndpointIds.length}）` : ''}
          </Button>
        </Space>
        <Table
          dataSource={endpoints ?? []} rowKey="id" size="small" pagination={{ pageSize: 10 }}
          rowSelection={{
            selectedRowKeys: selectedEndpointIds,
            onChange: (keys) => setSelectedEndpointIds(keys.map(String)),
            getCheckboxProps: (record) => ({ disabled: !record.is_active }),
          }}
          columns={[
            { title: '名称', dataIndex: 'name' },
            { title: '方法', dataIndex: 'method', width: 70, render: (v: string) => <Tag color="blue">{v}</Tag> },
            { title: '路径', dataIndex: 'path', ellipsis: true },
            { title: '状态', dataIndex: 'is_active', width: 70, render: (v: boolean) => <Tag color={v ? 'green' : 'default'}>{v ? '启用' : '停用'}</Tag> },
            { title: '操作', width: 190, render: (_: unknown, ep: ToolEndpoint) => (
              <Space size="small">
                <Button size="small" icon={<ThunderboltOutlined />} onClick={() => { setTestEp(ep); setTestParams({}); setTestResult(null); }}>测试</Button>
                <Button size="small" icon={<EditOutlined />} onClick={() => openEditEndpoint(ep)}>编辑</Button>
                <Button size="small" danger icon={<DeleteOutlined />} onClick={() => setEndpointConfirm({ id: ep.id, name: ep.name })} />
              </Space>
            )},
          ]}
        />
      </Modal>

      <Modal
        title={editingEndpoint ? '编辑端点' : '手工添加端点'}
        open={endpointModalOpen}
        onCancel={() => setEndpointModalOpen(false)}
        onOk={() => endpointForm.submit()}
        confirmLoading={saveEndpoint.isPending}
        width={760}
        forceRender
      >
        <Form form={endpointForm} layout="vertical" onFinish={(values) => saveEndpoint.mutate(values)}>
          <Space.Compact block>
            <Form.Item name="method" label="方法" rules={[{ required: true }]} style={{ width: 130 }}>
              <Select options={['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].map((value) => ({ value, label: value }))} />
            </Form.Item>
            <Form.Item name="path" label="路径" rules={[{ required: true }]} style={{ flex: 1 }}>
              <Input placeholder="/api/v1/inventory/{sku}" />
            </Form.Item>
          </Space.Compact>
          <Form.Item name="name" label="端点名称" rules={[{ required: true }]}>
            <Input placeholder="query_inventory" />
          </Form.Item>
          <Form.Item name="description" label="用途说明">
            <Input.TextArea rows={2} placeholder="按 SKU 和仓库查询可用库存" />
          </Form.Item>
          <Form.Item name="params_schema" label="输入参数 JSON Schema">
            <JsonEditor value={endpointParamsSchema} onChange={(v) => endpointForm.setFieldValue('params_schema', v)} rows={6} />
          </Form.Item>
          <Form.Item name="response_schema" label="返回 JSON Schema（可选）">
            <JsonEditor value={endpointResponseSchema} onChange={(v) => endpointForm.setFieldValue('response_schema', v)} rows={4} />
          </Form.Item>
          <Form.Item name="is_active" label="启用" valuePropName="checked"><Switch /></Form.Item>
        </Form>
      </Modal>

      <Modal
        title="发布企业接口 Skill"
        open={publishOpen}
        onCancel={() => setPublishOpen(false)}
        onOk={() => publishForm.submit()}
        confirmLoading={publishSkill.isPending}
        forceRender
      >
        <Alert
          type="info" showIcon style={{ marginBottom: 16 }}
          message={`将 ${selectedEndpointIds.length} 个端点发布为组织级 Skill`}
          description="Skill 只保存端点引用，不包含连接器密钥。组织成员可在聊天中自动匹配或本轮明确调用。"
        />
        <Form
          form={publishForm}
          layout="vertical"
          onFinish={(values) => publishSkill.mutate(values)}
          onValuesChange={(changed) => {
            if ('name' in changed && !publishForm.isFieldTouched('slug')) {
              publishForm.setFieldValue('slug', slugify(String(changed.name)));
            }
          }}
        >
          <Form.Item name="name" label="Skill 名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item
            name="slug" label="Skill Slug"
            rules={[{ required: true }, { pattern: /^[a-z0-9]+(?:-[a-z0-9]+)*$/, message: '只能使用小写字母、数字和连字符' }]}
          ><Input /></Form.Item>
          <Form.Item name="description" label="给智能体看的用途说明" rules={[{ required: true }]}>
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
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
      {orgId && (
        <ConnectorOnboardingWizard
          open={onboardingOpen}
          orgId={orgId}
          onClose={() => setOnboardingOpen(false)}
          onCompleted={(applicationId) => {
            setOnboardingOpen(false);
            qc.invalidateQueries({ queryKey: ['connectors', orgId] });
            qc.invalidateQueries({ queryKey: ['enterprise-applications', orgId] });
            navigate(`/enterprise-apps/${applicationId}`);
          }}
        />
      )}
      <ConfirmModal
        open={!!endpointConfirm}
        title={<>确定删除端点「{endpointConfirm?.name}」？</>}
        okText="删除"
        loading={deleteEndpoint.isPending}
        onCancel={() => setEndpointConfirm(null)}
        onOk={() => {
          if (endpointConfirm) deleteEndpoint.mutate(endpointConfirm.id);
          setEndpointConfirm(null);
        }}
      />
    </FinderShell>
  );
}
