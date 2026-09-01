import { useMemo, useState } from 'react';
import { Button, Checkbox, Form, Input, Modal, Select, Space, Table, Tag, Typography, message } from 'antd';
import { DeleteOutlined, EditOutlined, PlusOutlined, SafetyCertificateOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError, organizations, roles, type Role, type RoleDataScope } from '../../api/client';
import OrgSelect from '../../components/OrgSelect';
import { FinderShell, TitleBar } from '../../components/finder/primitives';
import { useOrgTree } from '../../hooks/useOrgTree';

const DATA_SCOPE_OPTIONS: { value: RoleDataScope; label: string }[] = [
  { value: 'all', label: '全部数据' },
  { value: 'custom_departments', label: '指定部门' },
  { value: 'department', label: '本部门' },
  { value: 'department_and_children', label: '本部门及下级' },
  { value: 'self', label: '仅本人' },
];

const PERMISSION_GROUPS = [
  { label: '企业应用', options: [
    { label: '查看企业应用', value: 'enterprise_application.view' },
    { label: '使用 AI 查询', value: 'enterprise_application.ai_query' },
    { label: '使用 AI 新增', value: 'enterprise_application.ai_create' },
    { label: '使用 AI 更新', value: 'enterprise_application.ai_update' },
    { label: '使用 AI 删除', value: 'enterprise_application.ai_delete' },
    { label: '使用 AI 审批', value: 'enterprise_application.ai_approve' },
  ] },
  { label: '语音与全模态', options: [
    { label: '音频转写', value: 'multimodal.audio.transcribe' },
    { label: '音频理解', value: 'multimodal.audio.understand' },
    { label: '使用朗读音色', value: 'multimodal.speech.use' },
    { label: '设计音色', value: 'multimodal.voice.design' },
    { label: '克隆音色', value: 'multimodal.voice.clone' },
    { label: '管理音色', value: 'multimodal.voice.manage' },
  ] },
];

function slugify(value: string) {
  return value.toLowerCase().trim().replace(/[^a-z0-9_.:-]+/g, '_').replace(/^_+|_+$/g, '');
}

export default function RolesPage() {
  const qc = useQueryClient();
  const [form] = Form.useForm();
  const [selectedOrgId, setSelectedOrgId] = useState<string>();
  const [editing, setEditing] = useState<Role | null>(null);
  const [open, setOpen] = useState(false);
  const dataScope = Form.useWatch('data_scope', form) as RoleDataScope | undefined;
  const { data: orgs = [] } = useQuery({ queryKey: ['orgs'], queryFn: organizations.list });
  const orgId = selectedOrgId ?? orgs.find(org => org.is_default)?.id ?? orgs[0]?.id;
  const { data: roleList = [], isLoading } = useQuery({
    queryKey: ['roles', orgId],
    queryFn: () => orgId ? roles.list(orgId) : Promise.resolve([]),
    enabled: !!orgId,
  });
  const { nodeMap } = useOrgTree();
  const departmentOptions = useMemo(() => Array.from(nodeMap.values())
    .filter(node => node.type === 'department' && node.orgId === orgId)
    .map(node => ({ value: node.id, label: node.name })), [nodeMap, orgId]);

  const close = () => { setOpen(false); setEditing(null); form.resetFields(); };
  const save = useMutation({
    mutationFn: async (values: {
      name: string; code: string; description?: string; data_scope: RoleDataScope;
      department_ids?: string[]; permission_codes?: string[]; is_active: boolean;
    }) => {
      if (!orgId) throw new Error('请先选择企业');
      const role = editing
        ? await roles.update(editing.id, {
            name: values.name, description: values.description, is_active: values.is_active,
          })
        : await roles.create(orgId, {
            name: values.name, code: values.code, description: values.description,
            data_scope: values.data_scope, is_active: values.is_active,
          });
      await roles.replacePermissions(role.id, values.permission_codes ?? []);
      return roles.replaceDataScope(
        role.id,
        values.data_scope,
        values.data_scope === 'custom_departments' ? values.department_ids ?? [] : [],
      );
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['roles', orgId] });
      qc.invalidateQueries({ queryKey: ['users', orgId] });
      close();
      message.success('角色已保存');
    },
    onError: (error) => message.error(error instanceof ApiError ? error.message : '角色保存失败'),
  });
  const remove = useMutation({
    mutationFn: (id: string) => roles.delete(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['roles', orgId] }); message.success('角色已删除'); },
    onError: (error) => message.error(error instanceof ApiError ? error.message : '角色删除失败'),
  });

  const edit = (role: Role) => {
    setEditing(role);
    form.setFieldsValue({
      name: role.name,
      code: role.code,
      description: role.description,
      data_scope: role.data_scope,
      department_ids: role.department_ids,
      permission_codes: role.permission_codes,
      is_active: role.is_active,
    });
    setOpen(true);
  };

  return <FinderShell>
    <TitleBar
      icon={<SafetyCertificateOutlined />}
      title="角色与数据范围"
      titleExtra={<OrgSelect value={orgId} onChange={setSelectedOrgId} />}
      extra={<Button type="primary" icon={<PlusOutlined />} disabled={!orgId} onClick={() => {
        setEditing(null);
        form.resetFields();
        form.setFieldsValue({ data_scope: 'self', is_active: true, permission_codes: [] });
        setOpen(true);
      }}>新建角色</Button>}
    />
    <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
      <Typography.Paragraph type="secondary">
        用户只归属一个部门，但可拥有多个角色；角色权限和数据范围会取并集，且始终受企业边界限制。
      </Typography.Paragraph>
      <Table dataSource={roleList} rowKey="id" loading={isLoading} columns={[
        { title: '角色', render: (_: unknown, role: Role) => <Space>
          <Typography.Text strong>{role.name}</Typography.Text>
          {role.is_builtin && <Tag color="blue">内置</Tag>}
        </Space> },
        { title: '标识', dataIndex: 'code' },
        { title: '数据范围', dataIndex: 'data_scope', render: (value: RoleDataScope) => (
          <Tag>{DATA_SCOPE_OPTIONS.find(item => item.value === value)?.label ?? value}</Tag>
        ) },
        { title: '权限数', render: (_: unknown, role: Role) => role.permission_codes.includes('*')
          ? <Tag color="red">全部权限</Tag> : `${role.permission_codes.length} 项` },
        { title: '状态', dataIndex: 'is_active', render: (value: boolean) => (
          <Tag color={value ? 'green' : 'default'}>{value ? '启用' : '停用'}</Tag>
        ) },
        { title: '操作', width: 180, render: (_: unknown, role: Role) => <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => edit(role)}>编辑</Button>
          {!role.is_builtin && <Button size="small" danger icon={<DeleteOutlined />} onClick={() => remove.mutate(role.id)}>删除</Button>}
        </Space> },
      ]} />
    </div>
    <Modal
      open={open}
      title={editing ? `编辑角色：${editing.name}` : '新建角色'}
      width={720}
      onCancel={close}
      onOk={() => form.submit()}
      confirmLoading={save.isPending}
      forceRender
    >
      <Form form={form} layout="vertical" onFinish={values => save.mutate(values)}>
        <Space align="start" style={{ display: 'flex' }}>
          <Form.Item name="name" label="角色名称" rules={[{ required: true }]} style={{ flex: 1 }}>
            <Input onChange={event => {
              if (!editing && !form.getFieldValue('code')) form.setFieldValue('code', slugify(event.target.value));
            }} />
          </Form.Item>
          <Form.Item name="code" label="角色标识" rules={[{ required: true }]} style={{ flex: 1 }}>
            <Input disabled={!!editing} placeholder="quality_approver" />
          </Form.Item>
        </Space>
        <Form.Item name="description" label="说明"><Input.TextArea rows={2} /></Form.Item>
        <Form.Item name="data_scope" label="数据范围" rules={[{ required: true }]}>
          <Select options={DATA_SCOPE_OPTIONS} />
        </Form.Item>
        {dataScope === 'custom_departments' && <Form.Item
          name="department_ids"
          label="指定部门"
          rules={[{ required: true, message: '请至少选择一个部门' }]}
        ><Select mode="multiple" options={departmentOptions} /></Form.Item>}
        <Form.Item name="permission_codes" label="功能权限">
          <Checkbox.Group options={PERMISSION_GROUPS.flatMap(group => group.options.map(option => ({
            ...option, label: `${group.label} · ${option.label}`,
          })))} />
        </Form.Item>
        <Form.Item name="is_active" label="状态"><Select options={[
          { value: true, label: '启用' }, { value: false, label: '停用' },
        ]} /></Form.Item>
      </Form>
    </Modal>
  </FinderShell>;
}
