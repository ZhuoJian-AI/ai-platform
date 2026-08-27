import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert, Button, Card, Checkbox, Divider, Form, Input, Modal, Radio, Result,
  Select, Space, Steps, Table, Tag, TreeSelect, Typography, Upload, message,
} from 'antd';
import {
  ApiOutlined, ArrowLeftOutlined, ArrowRightOutlined, CheckCircleOutlined,
  CloudServerOutlined, FileSearchOutlined, LockOutlined, RocketOutlined,
  SafetyCertificateOutlined, UploadOutlined, WarningOutlined,
} from '@ant-design/icons';
import type { UploadProps } from 'antd';
import {
  ApiError, connectors, enterpriseApplications,
  type EnterpriseApplication,
  type EnterpriseApplicationOperation,
  type EnterpriseApplicationPermission,
  type OpenApiInspection,
  type OpenApiPreviewEndpoint,
  type ToolConnector,
  type ToolEndpoint,
} from '../../api/client';
import { useOrgTree } from '../../hooks/useOrgTree';
import './ConnectorOnboardingWizard.css';

interface Props {
  open: boolean;
  orgId: string;
  onClose: () => void;
  onCompleted: (applicationId: string) => void;
}

type SpecSource = 'url' | 'file' | 'paste';
type AuthType = 'none' | 'bearer' | 'apikey' | 'basic' | 'oauth';

type WizardValues = {
  name: string;
  slug: string;
  description?: string;
  type: string;
  base_url: string;
  entry_url: string;
  display_mode: 'embedded' | 'external';
  auth_type: AuthType;
  bearer_token?: string;
  api_key_header?: string;
  api_key?: string;
  username?: string;
  password?: string;
  oauth_access_token?: string;
  spec_url?: string;
  spec_content?: string;
  visible_scopes: string[];
  permissions: EnterpriseApplicationPermission[];
  skill_name: string;
  skill_slug: string;
  skill_description: string;
};

type PublishProgress = {
  connector?: ToolConnector;
  endpoints?: ToolEndpoint[];
  application?: EnterpriseApplication;
  grantsSaved?: boolean;
  bindingsSaved?: boolean;
  skillPublished?: boolean;
};

const TYPE_OPTIONS = [
  { value: 'erp', label: 'ERP · 企业资源计划' },
  { value: 'mes', label: 'MES · 生产执行' },
  { value: 'crm', label: 'CRM · 客户管理' },
  { value: 'hrm', label: 'HRM · 人力资源' },
  { value: 'scm', label: 'SCM · 供应链' },
  { value: 'other', label: '其他业务系统' },
];

const AUTH_OPTIONS = [
  { value: 'none', label: '无需鉴权' },
  { value: 'bearer', label: 'Bearer Token' },
  { value: 'apikey', label: 'API Key' },
  { value: 'basic', label: 'Basic Auth' },
  { value: 'oauth', label: 'OAuth Access Token' },
];

const PERMISSION_OPTIONS: Array<{ value: EnterpriseApplicationPermission; label: string }> = [
  { value: 'view', label: '访问应用' },
  { value: 'ai_query', label: 'AI 查询' },
  { value: 'ai_create', label: 'AI 新增' },
  { value: 'ai_update', label: 'AI 更新' },
  { value: 'ai_delete', label: 'AI 删除' },
  { value: 'export', label: '导出' },
];

const STEP_FIELDS: Array<Array<keyof WizardValues>> = [
  ['name', 'slug', 'type', 'base_url', 'entry_url', 'display_mode'],
  ['auth_type'],
  [],
  ['visible_scopes', 'permissions', 'skill_name', 'skill_slug', 'skill_description'],
];

const slugify = (value: string) => value
  .toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 100);

const endpointKey = (endpoint: Pick<OpenApiPreviewEndpoint, 'method' | 'path'>) =>
  `${endpoint.method.toUpperCase()} ${endpoint.path}`;

function operationForMethod(method: string): EnterpriseApplicationOperation {
  if (method === 'GET') return 'query';
  if (method === 'POST') return 'create';
  if (method === 'DELETE') return 'delete';
  return 'update';
}

function requiredPermissions(operations: EnterpriseApplicationOperation[]) {
  const values = new Set<EnterpriseApplicationPermission>(['view']);
  operations.forEach((operation) => {
    if (operation === 'query') values.add('ai_query');
    if (operation === 'create') values.add('ai_create');
    if (operation === 'update') values.add('ai_update');
    if (operation === 'delete') values.add('ai_delete');
    if (operation === 'export') values.add('export');
  });
  return [...values];
}

function authConfig(values: WizardValues) {
  if (values.auth_type === 'bearer') return { token: values.bearer_token };
  if (values.auth_type === 'apikey') {
    return { header_key: values.api_key_header || 'X-API-Key', api_key: values.api_key };
  }
  if (values.auth_type === 'basic') return { username: values.username, password: values.password };
  if (values.auth_type === 'oauth') return { access_token: values.oauth_access_token };
  return {};
}

function riskTag(method: string) {
  if (method === 'GET') return <Tag color="blue">只读</Tag>;
  if (method === 'DELETE') return <Tag color="red" icon={<WarningOutlined />}>高风险</Tag>;
  if (method === 'POST') return <Tag color="green">新增</Tag>;
  return <Tag color="orange">修改</Tag>;
}

function errorText(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : error instanceof Error ? error.message : fallback;
}

export default function ConnectorOnboardingWizard({ open, orgId, onClose, onCompleted }: Props) {
  const [form] = Form.useForm<WizardValues>();
  const authType = Form.useWatch('auth_type', form);
  const systemName = Form.useWatch('name', form);
  const [step, setStep] = useState(0);
  const [specSource, setSpecSource] = useState<SpecSource>('url');
  const [inspection, setInspection] = useState<OpenApiInspection>();
  const [selectedKeys, setSelectedKeys] = useState<string[]>([]);
  const [operations, setOperations] = useState<Record<string, EnterpriseApplicationOperation>>({});
  const [inspecting, setInspecting] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [publishError, setPublishError] = useState<string>();
  const [publishLog, setPublishLog] = useState<string[]>([]);
  const [completedAppId, setCompletedAppId] = useState<string>();
  const progressRef = useRef<PublishProgress>({});
  const { treeData, nodeMap, isLoading: treeLoading } = useOrgTree();

  const orgTree = useMemo(
    () => treeData.filter((node) => node.value === `org:${orgId}`),
    [orgId, treeData],
  );
  const rows = useMemo(() => (inspection?.endpoints ?? []).map((endpoint) => ({
    ...endpoint, key: endpointKey(endpoint), operation: operations[endpointKey(endpoint)] ?? operationForMethod(endpoint.method),
  })), [inspection, operations]);
  const selectedRows = rows.filter((row) => selectedKeys.includes(row.key));
  const hasWriteAction = selectedRows.some((row) => row.operation !== 'query');

  useEffect(() => {
    if (!open) return;
    setStep(0);
    setSpecSource('url');
    setInspection(undefined);
    setSelectedKeys([]);
    setOperations({});
    setPublishError(undefined);
    setPublishLog([]);
    setCompletedAppId(undefined);
    progressRef.current = {};
    form.resetFields();
    form.setFieldsValue({
      type: 'other', display_mode: 'embedded', auth_type: 'bearer',
      api_key_header: 'X-API-Key', permissions: ['view', 'ai_query'], visible_scopes: [],
    });
  }, [form, open]);

  const validateAuth = async () => {
    const fields: Array<keyof WizardValues> = ['auth_type'];
    if (authType === 'bearer') fields.push('bearer_token');
    if (authType === 'apikey') fields.push('api_key_header', 'api_key');
    if (authType === 'basic') fields.push('username', 'password');
    if (authType === 'oauth') fields.push('oauth_access_token');
    await form.validateFields(fields);
  };

  const inspectDocument = async () => {
    await validateAuth();
    const sourceField = specSource === 'url' ? 'spec_url' : 'spec_content';
    await form.validateFields([sourceField]);
    const values = form.getFieldsValue();
    setInspecting(true);
    try {
      const result = await connectors.inspectSpec(orgId, specSource === 'url'
        ? { url: values.spec_url }
        : { content: values.spec_content });
      const nextOperations = Object.fromEntries(
        result.endpoints.map((endpoint) => [endpointKey(endpoint), operationForMethod(endpoint.method)]),
      );
      const safeDefaults = result.endpoints
        .filter((endpoint) => endpoint.method.toUpperCase() === 'GET')
        .map(endpointKey);
      setInspection(result);
      setOperations(nextOperations);
      setSelectedKeys(safeDefaults.length ? safeDefaults : result.endpoints.slice(0, 1).map(endpointKey));
      setStep(2);
    } catch (error) {
      message.error(errorText(error, 'OpenAPI 预检失败'));
    } finally {
      setInspecting(false);
    }
  };

  const continueFromCapabilities = () => {
    if (!selectedKeys.length) {
      message.warning('请至少选择一个允许 AI 调用的接口');
      return;
    }
    const permissions = requiredPermissions(selectedRows.map((row) => row.operation));
    const name = form.getFieldValue('name');
    const slug = form.getFieldValue('slug');
    form.setFieldsValue({
      permissions,
      skill_name: `${name}助手`,
      skill_slug: slugify(`${slug}-api`),
      skill_description: `查询和操作${name}中的企业数据`,
    });
    setStep(3);
  };

  const uploadProps: UploadProps = {
    accept: '.json,.yaml,.yml,application/json,application/yaml,text/yaml',
    maxCount: 1,
    beforeUpload: async (file) => {
      const content = await file.text();
      form.setFieldValue('spec_content', content);
      message.success(`已读取 ${file.name}`);
      return Upload.LIST_IGNORE;
    },
  };

  const appendLog = (value: string) => setPublishLog((current) => [...current, value]);

  const publish = async () => {
    const values = await form.validateFields();
    if (!inspection) return;
    setPublishing(true);
    setPublishError(undefined);
    let progress = progressRef.current;
    try {
      if (!progress.connector) {
        appendLog('正在创建安全连接…');
        progress.connector = await connectors.create(orgId, {
          name: values.name,
          slug: values.slug,
          description: values.description,
          type: values.type,
          base_url: values.base_url,
          auth_type: values.auth_type,
          auth_config: authConfig(values),
          spec: inspection.spec,
          is_active: true,
        });
        progressRef.current = { ...progress };
        appendLog('连接器已创建，鉴权信息已加密保存');
      }

      if (!progress.endpoints) {
        appendLog('正在导入已选择的 REST 接口…');
        progress.endpoints = await connectors.importSpec(progress.connector.id);
        progressRef.current = { ...progress };
        appendLog(`已识别 ${progress.endpoints.length} 个接口`);
      }

      const endpointByKey = new Map(progress.endpoints.map((endpoint) => [endpointKey(endpoint), endpoint]));
      const chosenEndpoints = selectedKeys.map((key) => endpointByKey.get(key)).filter(Boolean) as ToolEndpoint[];
      if (chosenEndpoints.length !== selectedKeys.length) throw new Error('部分 OpenAPI 接口未能导入，请返回检查接口定义');

      if (!progress.application) {
        appendLog('正在登记企业应用入口…');
        progress.application = await enterpriseApplications.create(orgId, {
          name: values.name,
          slug: values.slug,
          description: values.description,
          entry_url: values.entry_url,
          display_mode: values.display_mode,
          sort_order: 0,
          is_active: true,
          assistant_enabled: true,
          assistant_prompt: `你是${values.name}业务助手，只使用当前应用授权的接口处理业务请求。`,
        });
        progressRef.current = { ...progress };
        appendLog('企业应用入口已登记');
      }

      if (!progress.grantsSaved) {
        const grants = values.visible_scopes.map((scope) => {
          const node = nodeMap.get(scope);
          if (!node || node.orgId !== orgId) throw new Error(`无法识别授权范围：${scope}`);
          return {
            scope_type: node.type,
            scope_id: node.type === 'organization' ? null : node.id,
            permissions: values.permissions,
          };
        });
        await enterpriseApplications.replaceGrants(progress.application.id, grants);
        progress.grantsSaved = true;
        progressRef.current = { ...progress };
        appendLog('部门与 AI 操作权限已生效');
      }

      if (!progress.bindingsSaved) {
        await enterpriseApplications.replaceToolBindings(
          progress.application.id,
          chosenEndpoints.map((endpoint) => ({
            target_type: 'tool_endpoint' as const,
            target_id: endpoint.id,
            operation: operations[endpointKey(endpoint)] ?? operationForMethod(endpoint.method),
            is_active: true,
          })),
        );
        progress.bindingsSaved = true;
        progressRef.current = { ...progress };
        appendLog('REST 接口已绑定到业务助手');
      }

      if (!progress.skillPublished) {
        await connectors.publishSkill(progress.connector.id, {
          name: values.skill_name,
          slug: values.skill_slug,
          description: values.skill_description,
          endpoint_ids: chosenEndpoints.map((endpoint) => endpoint.id),
        });
        progress.skillPublished = true;
        progressRef.current = { ...progress };
        appendLog('AI Skill 已发布');
      }

      setCompletedAppId(progress.application.id);
    } catch (error) {
      const detail = errorText(error, '发布失败');
      setPublishError(detail);
      appendLog(`暂停：${detail}`);
    } finally {
      setPublishing(false);
    }
  };

  const close = () => {
    if (publishing) return;
    onClose();
  };

  const renderSystemStep = () => (
    <div className="connector-onboarding-grid">
      <div>
        <Typography.Title level={4}>先说明这是哪个业务系统</Typography.Title>
        <Typography.Paragraph type="secondary">页面入口供员工使用，API 地址供 AI 调用；两者可以是不同域名。</Typography.Paragraph>
        <Space.Compact block>
          <Form.Item name="name" label="系统名称" rules={[{ required: true }]} style={{ flex: 1 }}>
            <Input placeholder="采购管理系统" onChange={(event) => {
              if (!form.isFieldTouched('slug')) form.setFieldValue('slug', slugify(event.target.value));
            }} />
          </Form.Item>
          <Form.Item name="slug" label="系统标识" rules={[{ required: true }, { pattern: /^[a-z0-9]+(?:-[a-z0-9]+)*$/, message: '仅小写字母、数字和连字符' }]} style={{ flex: 1 }}>
            <Input placeholder="purchase-system" />
          </Form.Item>
        </Space.Compact>
        <Form.Item name="type" label="业务类型" rules={[{ required: true }]}><Select options={TYPE_OPTIONS} /></Form.Item>
        <Form.Item name="description" label="系统说明"><Input.TextArea rows={2} placeholder="管理采购申请、订单和供应商协同" /></Form.Item>
        <Form.Item name="entry_url" label="员工使用的页面入口" rules={[{ required: true }, { type: 'url' }]}>
          <Input prefix={<CloudServerOutlined />} placeholder="https://purchase.example.com" />
        </Form.Item>
        <Form.Item name="base_url" label="REST API Base URL" rules={[{ required: true }, { type: 'url' }]}>
          <Input prefix={<ApiOutlined />} placeholder="https://purchase.example.com/api/v1" />
        </Form.Item>
        <Form.Item name="display_mode" label="员工打开方式" rules={[{ required: true }]}>
          <Radio.Group optionType="button" buttonStyle="solid" options={[{ value: 'embedded', label: '平台内嵌' }, { value: 'external', label: '新窗口打开' }]} />
        </Form.Item>
      </div>
      <Card className="connector-onboarding-explainer" bordered={false}>
        <div className="connector-onboarding-icon"><CloudServerOutlined /></div>
        <Typography.Title level={5}>页面与 API 各司其职</Typography.Title>
        <div className="connector-onboarding-flow"><span>员工</span><b>打开页面</b><span>{systemName || '业务系统'}</span></div>
        <div className="connector-onboarding-flow"><span>AI</span><b>调用 REST</b><span>业务系统 API</span></div>
        <Typography.Paragraph type="secondary">平台不会接管对方数据库，只登记页面入口并通过授权接口完成查询和操作。</Typography.Paragraph>
      </Card>
    </div>
  );

  const authFields = () => {
    if (authType === 'bearer') return <Form.Item name="bearer_token" label="Bearer Token" rules={[{ required: true }]}><Input.Password autoComplete="new-password" /></Form.Item>;
    if (authType === 'apikey') return <Space.Compact block><Form.Item name="api_key_header" label="Header 名称" rules={[{ required: true }]} style={{ width: '38%' }}><Input /></Form.Item><Form.Item name="api_key" label="API Key" rules={[{ required: true }]} style={{ flex: 1 }}><Input.Password autoComplete="new-password" /></Form.Item></Space.Compact>;
    if (authType === 'basic') return <Space.Compact block><Form.Item name="username" label="用户名" rules={[{ required: true }]} style={{ width: '50%' }}><Input /></Form.Item><Form.Item name="password" label="密码" rules={[{ required: true }]} style={{ flex: 1 }}><Input.Password autoComplete="new-password" /></Form.Item></Space.Compact>;
    if (authType === 'oauth') return <><Alert showIcon type="warning" message="当前版本保存已有 Access Token，尚未自动刷新 OAuth 令牌。" style={{ marginBottom: 14 }} /><Form.Item name="oauth_access_token" label="Access Token" rules={[{ required: true }]}><Input.Password autoComplete="new-password" /></Form.Item></>;
    return <Alert showIcon type="info" message="系统接口不需要鉴权，仅建议用于受控内网或公开只读 API。" />;
  };

  const renderApiStep = () => (
    <div className="connector-onboarding-api-grid">
      <Card title={<Space><LockOutlined />接口鉴权</Space>}>
        <Form.Item name="auth_type" label="鉴权方式" rules={[{ required: true }]}><Select options={AUTH_OPTIONS} /></Form.Item>
        {authFields()}
        <Alert showIcon type="success" message="密钥只在服务端加密保存，不会写入 Skill 或返回给用户。" />
      </Card>
      <Card title={<Space><FileSearchOutlined />OpenAPI 说明书</Space>}>
        <Radio.Group value={specSource} onChange={(event) => setSpecSource(event.target.value)} optionType="button" buttonStyle="solid" options={[
          { value: 'url', label: '输入 URL' }, { value: 'file', label: '上传文件' }, { value: 'paste', label: '粘贴内容' },
        ]} />
        <Divider />
        {specSource === 'url' && <Form.Item name="spec_url" label="OpenAPI 地址" rules={[{ required: true }, { type: 'url' }]}><Input placeholder="https://purchase.example.com/openapi.json" /></Form.Item>}
        {specSource === 'file' && <><Upload.Dragger {...uploadProps}><p className="ant-upload-drag-icon"><UploadOutlined /></p><p>拖入 openapi.json / yaml</p><p className="ant-upload-hint">最大 2 MB，只用于预检，确认发布前不会保存</p></Upload.Dragger><Form.Item name="spec_content" hidden rules={[{ required: true, message: '请上传 OpenAPI 文件' }]}><Input.TextArea /></Form.Item></>}
        {specSource === 'paste' && <Form.Item name="spec_content" label="JSON 或 YAML" rules={[{ required: true }]}><Input.TextArea rows={10} className="connector-onboarding-code" placeholder={'openapi: 3.0.0\npaths:\n  /orders:\n    get: ...'} /></Form.Item>}
      </Card>
    </div>
  );

  const renderCapabilitiesStep = () => (
    <div className="connector-onboarding-capabilities">
      <div className="connector-onboarding-section-heading">
        <div><Typography.Title level={4}>选择允许 AI 调用的 REST 接口</Typography.Title><Typography.Text type="secondary">默认只勾选 GET 查询接口；写入和删除必须由管理员主动开放。</Typography.Text></div>
        <Space><Tag color="green">{inspection?.title || 'OpenAPI'}</Tag>{inspection?.version && <Tag>{inspection.version}</Tag>}<Tag>{rows.length} 个接口</Tag></Space>
      </div>
      {hasWriteAction && <Alert showIcon type="warning" message="已选择写操作" description="发布后仍会执行部门权限校验；建议只开放确有业务必要的新增、修改或删除接口。" />}
      <Table
        className="connector-onboarding-table"
        size="small"
        pagination={{ pageSize: 8 }}
        rowKey="key"
        dataSource={rows}
        rowSelection={{ selectedRowKeys: selectedKeys, onChange: (keys) => setSelectedKeys(keys.map(String)) }}
        columns={[
          { title: '能力名称', dataIndex: 'name', render: (name: string, row) => <div><Typography.Text strong>{name}</Typography.Text><div><Typography.Text type="secondary">{row.description || '未提供说明'}</Typography.Text></div></div> },
          { title: 'REST API', width: 330, render: (_: unknown, row) => <Space><Tag>{row.method}</Tag><Typography.Text code>{row.path}</Typography.Text></Space> },
          { title: '风险', width: 105, render: (_: unknown, row) => riskTag(row.method) },
          { title: 'AI 动作', width: 130, render: (_: unknown, row) => <Select value={row.operation} style={{ width: 105 }} options={[{ value: 'query', label: '查询' }, { value: 'create', label: '新增' }, { value: 'update', label: '更新' }, { value: 'delete', label: '删除' }, { value: 'export', label: '导出' }]} onChange={(operation) => setOperations((current) => ({ ...current, [row.key]: operation }))} /> },
        ]}
      />
    </div>
  );

  const renderReleaseStep = () => (
    <div className="connector-onboarding-release-grid">
      <Card title={<Space><SafetyCertificateOutlined />谁可以使用</Space>}>
        <Form.Item name="visible_scopes" label="部门、团队或用户" rules={[{ required: true, message: '请至少选择一个授权范围' }]}>
          <TreeSelect multiple allowClear treeData={orgTree} treeDefaultExpandAll showSearch treeNodeFilterProp="title" loading={treeLoading} placeholder="选择采购部、财务部或指定人员" />
        </Form.Item>
        <Form.Item name="permissions" label="授予的应用与 AI 权限" rules={[{ required: true }]}>
          <Checkbox.Group options={PERMISSION_OPTIONS} />
        </Form.Item>
        {hasWriteAction && <Alert showIcon type="warning" message="只有同时拥有对应 AI 权限的用户，才能执行写操作。" />}
      </Card>
      <Card title={<Space><RocketOutlined />发布为 AI 能力</Space>}>
        <Form.Item name="skill_name" label="能力名称" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="skill_slug" label="能力标识" rules={[{ required: true }, { pattern: /^[a-z0-9]+(?:-[a-z0-9]+)*$/, message: '仅小写字母、数字和连字符' }]}><Input /></Form.Item>
        <Form.Item name="skill_description" label="给 AI 看的用途说明" rules={[{ required: true }]}><Input.TextArea rows={3} /></Form.Item>
        <div className="connector-onboarding-release-summary">
          <div><span>页面入口</span><b>1 个</b></div>
          <div><span>AI 接口</span><b>{selectedKeys.length} 个</b></div>
          <div><span>写操作</span><b>{selectedRows.filter((row) => row.operation !== 'query').length} 个</b></div>
        </div>
      </Card>
    </div>
  );

  const stepContent = [renderSystemStep(), renderApiStep(), renderCapabilitiesStep(), renderReleaseStep()][step];

  const next = async () => {
    try {
      await form.validateFields(STEP_FIELDS[step]);
      if (step === 0) setStep(1);
      else if (step === 1) await inspectDocument();
      else if (step === 2) continueFromCapabilities();
      else await publish();
    } catch {
      // Ant Design displays field-level validation messages.
    }
  };

  return (
    <Modal
      open={open}
      onCancel={close}
      width={1120}
      closable={!publishing}
      maskClosable={false}
      className="connector-onboarding-modal"
      title={null}
      footer={completedAppId ? null : (
        <div className="connector-onboarding-footer">
          <Button onClick={step === 0 ? close : () => setStep((value) => value - 1)} disabled={publishing} icon={step > 0 ? <ArrowLeftOutlined /> : undefined}>{step === 0 ? '取消' : '上一步'}</Button>
          <div className="connector-onboarding-footer-status">{publishError ? <Typography.Text type="danger">已保留完成的步骤，可直接重试</Typography.Text> : step === 3 ? `即将接入 ${selectedKeys.length} 个接口` : '配置在最终发布前不会写入系统'}</div>
          <Button type="primary" onClick={next} loading={inspecting || publishing} icon={step === 3 ? <RocketOutlined /> : <ArrowRightOutlined />}>
            {step === 1 ? '预检 OpenAPI' : step === 3 ? (publishError ? '继续发布' : '确认接入') : '继续'}
          </Button>
        </div>
      )}
    >
      <div className="connector-onboarding-shell">
        <div className="connector-onboarding-header">
          <div><div className="connector-onboarding-eyebrow">BUSINESS SYSTEM ONBOARDING</div><Typography.Title level={3}>接入业务系统</Typography.Title><Typography.Text type="secondary">页面给员工使用，REST API 给 AI 使用，权限由平台统一控制。</Typography.Text></div>
          {!completedAppId && <Steps current={step} responsive={false} items={[{ title: '系统' }, { title: 'API' }, { title: '能力' }, { title: '权限与发布' }]} />}
        </div>
        <Form form={form} layout="vertical" requiredMark="optional">
          <div className="connector-onboarding-body">
            {completedAppId ? (
              <Result
                status="success"
                icon={<CheckCircleOutlined />}
                title="业务系统已接通"
                subTitle="页面入口、REST 接口、部门权限和 AI Skill 已完成绑定。"
                extra={[
                  <Button key="close" onClick={close}>关闭</Button>,
                  <Button key="detail" type="primary" onClick={() => onCompleted(completedAppId)}>查看应用控制中心</Button>,
                ]}
              >
                <div className="connector-onboarding-log">{publishLog.map((item, index) => <div key={`${item}-${index}`}><CheckCircleOutlined />{item}</div>)}</div>
              </Result>
            ) : (
              <>
                {stepContent}
                {(publishing || publishError) && <Card className="connector-onboarding-progress" size="small" title="接入进度">{publishLog.map((item, index) => <div key={`${item}-${index}`}>{item}</div>)}{publishError && <Alert type="error" showIcon message={publishError} />}</Card>}
              </>
            )}
          </div>
        </Form>
      </div>
    </Modal>
  );
}
