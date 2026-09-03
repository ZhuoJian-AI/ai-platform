import { useState } from 'react';
import { Button, Checkbox, Form, Input, Modal, Select, Space, Table, Tag, Typography, message } from 'antd';
import { DeleteOutlined, EditOutlined, PlusOutlined, SafetyCertificateOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { ApiError, organizations, roles, type Role } from '../../api/client';
import OrgSelect from '../../components/OrgSelect';
import { FinderShell, TitleBar } from '../../components/finder/primitives';

const PLATFORM_PERMISSIONS = [
  { label: '音频转写', value: 'multimodal.audio.transcribe' },
  { label: '音频理解', value: 'multimodal.audio.understand' },
  { label: '使用朗读音色', value: 'multimodal.speech.use' },
  { label: '设计音色', value: 'multimodal.voice.design' },
  { label: '克隆音色', value: 'multimodal.voice.clone' },
  { label: '管理音色', value: 'multimodal.voice.manage' },
];

function slugify(value: string) {
  return value.toLowerCase().trim().replace(/[^a-z0-9_.:-]+/g, '_').replace(/^_+|_+$/g, '');
}

export default function RolesPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [form] = Form.useForm();
  const [selectedOrgId, setSelectedOrgId] = useState<string>();
  const [editing, setEditing] = useState<Role | null>(null);
  const [open, setOpen] = useState(false);
  const { data: orgs = [] } = useQuery({ queryKey: ['orgs'], queryFn: organizations.list });
  const orgId = selectedOrgId ?? orgs.find(org => org.is_default)?.id ?? orgs[0]?.id;
  const { data: roleList = [], isLoading } = useQuery({
    queryKey: ['roles', orgId],
    queryFn: () => orgId ? roles.list(orgId) : Promise.resolve([]), enabled: !!orgId,
  });

  const close = () => { setOpen(false); setEditing(null); form.resetFields(); };
  const save = useMutation({
    mutationFn: async (values: {
      name: string; code: string; description?: string; permission_codes?: string[]; is_active: boolean;
    }) => {
      if (!orgId) throw new Error('请先选择企业');
      // 表单里的 Checkbox.Group 只认识平台通用能力；角色上其它权限码
      // （如 workspace.department.*:<id>、管理员通配 `*`）不在选项里，antd 会把它们从表单值里丢掉。
      // 保存时把这些非平台权限码原样合并回去，只用表单值覆盖平台能力这一段。
      const isPlatformCode = (code: string) => PLATFORM_PERMISSIONS.some(item => item.value === code);
      const nonPlatformCodes = (editing?.permission_codes ?? []).filter(code => !isPlatformCode(code));
      const nextPermissionCodes = Array.from(new Set([
        ...nonPlatformCodes, ...(values.permission_codes ?? []).filter(isPlatformCode),
      ]));
      const currentPermissionCodes = editing?.permission_codes ?? [];
      const permissionsChanged = !editing
        || nextPermissionCodes.length !== currentPermissionCodes.length
        || nextPermissionCodes.some(code => !currentPermissionCodes.includes(code));
      if (editing) {
        // 先写权限再改名：权限写失败时不会留下"改名成功但权限被清"的半成品。
        if (permissionsChanged) await roles.replacePermissions(editing.id, nextPermissionCodes);
        return roles.update(editing.id, {
          name: values.name, description: values.description, is_active: values.is_active,
        });
      }
      const role = await roles.create(orgId, {
        name: values.name, code: values.code, description: values.description, is_active: values.is_active,
      });
      if (nextPermissionCodes.length) await roles.replacePermissions(role.id, nextPermissionCodes);
      return role;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['roles', orgId] });
      qc.invalidateQueries({ queryKey: ['users', orgId] });
      close();
      message.success('角色已保存');
    },
    onError: error => message.error(error instanceof ApiError ? error.message : '角色保存失败'),
  });
  const remove = useMutation({
    mutationFn: (id: string) => roles.delete(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['roles', orgId] }); message.success('角色已删除'); },
    onError: error => message.error(error instanceof ApiError ? error.message : '角色删除失败'),
  });

  const edit = (role: Role) => {
    setEditing(role);
    form.setFieldsValue({
      name: role.name, code: role.code, description: role.description,
      permission_codes: role.permission_codes, is_active: role.is_active,
    });
    setOpen(true);
  };

  return <FinderShell>
    <TitleBar
      icon={<SafetyCertificateOutlined />}
      title="角色设置"
      titleExtra={<OrgSelect value={orgId} onChange={setSelectedOrgId} />}
      extra={<Space>
        <Button icon={<SafetyCertificateOutlined />} onClick={() => navigate('/enterprise-apps/permissions')}>配置企业模块权限</Button>
        <Button type="primary" icon={<PlusOutlined />} disabled={!orgId} onClick={() => {
          setEditing(null);
          form.resetFields();
          form.setFieldsValue({ is_active: true, permission_codes: [] });
          setOpen(true);
        }}>新建角色</Button>
      </Space>}
    />
    <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
      <Typography.Paragraph type="secondary">
        这里只维护角色名称和平台通用能力。企业模块、业务子模块、页面、操作和 AI 权限统一在“角色权限”配置。
      </Typography.Paragraph>
      <Table dataSource={roleList} rowKey="id" loading={isLoading} columns={[
        { title: '角色', render: (_: unknown, role: Role) => <Space>
          <Typography.Text strong>{role.name}</Typography.Text>
          {role.is_builtin && <Tag color="blue">内置</Tag>}
        </Space> },
        { title: '标识', dataIndex: 'code' },
        { title: '平台能力', render: (_: unknown, role: Role) => role.permission_codes.includes('*')
          ? <Tag color="red">全部平台能力</Tag> : `${role.permission_codes.length} 项` },
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
      open={open} title={editing ? `编辑角色：${editing.name}` : '新建角色'} width={720}
      onCancel={close} onOk={() => form.submit()} confirmLoading={save.isPending} forceRender
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
        <Form.Item name="permission_codes" label="平台通用能力" extra="这里不包含任何企业模块权限。">
          <Checkbox.Group options={PLATFORM_PERMISSIONS} />
        </Form.Item>
        <Form.Item
          name="is_active"
          label="状态"
          extra={editing?.is_builtin
            ? '内置角色用于基础登录与兜底授权，始终保持启用。'
            : '已分配给在职员工的角色，需要先从员工处移除后才能停用。'}
        >
          <Select
            disabled={Boolean(editing?.is_builtin)}
            options={[{ value: true, label: '启用' }, { value: false, label: '停用' }]}
          />
        </Form.Item>
      </Form>
    </Modal>
  </FinderShell>;
}
