import { useState } from 'react';
import {
  Alert, Button, Card, Descriptions, Form, Input, Modal, Select, Space, Switch, Table, Tag, message,
} from 'antd';
import { DeleteOutlined, EditOutlined, LockOutlined, PlusOutlined, TeamOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuth, type AdminRole } from '../context/AuthContext';
import { organizations as orgApi } from '../api/client';
import { adminFetch } from '../auth/adminSession';
import { FinderShell, TitleBar } from '../components/finder/primitives';
import ConfirmModal from '../components/finder/ConfirmModal';

const BASE_URL = import.meta.env.VITE_API_BASE_URL || '';

interface AdminItem {
  id: number;
  username: string;
  display_name: string | null;
  role: AdminRole;
  is_active: boolean;
  organization_id?: string | null;
  organization_name?: string | null;
  created_at: string;
  updated_at: string;
}

interface AdminCreateValues {
  username: string;
  password: string;
  display_name?: string;
  role?: AdminRole;
  organization_id?: string | null;
}

async function adminRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await adminFetch(`${BASE_URL}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: unknown };
    throw new Error(typeof body.detail === 'string' ? body.detail : `请求失败（HTTP ${response.status}）`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

const ROLE_LABELS: Record<AdminRole, string> = {
  platform_super_admin: '超级平台管理员',
  enterprise_admin: '企业管理员',
};

const ROLE_COLORS: Record<AdminRole, string> = {
  platform_super_admin: 'red',
  enterprise_admin: 'geekblue',
};

export default function AdminManagement() {
  const queryClient = useQueryClient();
  const { admin: currentUser, isSuperAdmin } = useAuth();
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [editingAdmin, setEditingAdmin] = useState<AdminItem | null>(null);
  const [createForm] = Form.useForm<AdminCreateValues>();
  const [editForm] = Form.useForm<{ display_name?: string; is_active: boolean }>();
  const [resetPwdAdmin, setResetPwdAdmin] = useState<AdminItem | null>(null);
  const [newPassword, setNewPassword] = useState('');
  const [confirm, setConfirm] = useState<{ id: number; name: string } | null>(null);
  const createRole = Form.useWatch('role', createForm);

  const adminScopeKey = currentUser?.organization_id || 'platform';
  const { data: adminList = [], isLoading } = useQuery({
    queryKey: ['admins', adminScopeKey],
    queryFn: () => adminRequest<AdminItem[]>('/api/v1/admins'),
    enabled: !!currentUser,
  });
  const { data: orgList = [] } = useQuery({
    queryKey: ['orgs'],
    queryFn: orgApi.list,
    enabled: isSuperAdmin(),
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['admins', adminScopeKey] });
  const mutationError = (error: unknown, fallback: string) => message.error(error instanceof Error ? error.message : fallback);

  const createAdmin = useMutation({
    mutationFn: (values: AdminCreateValues) => {
      const role: AdminRole = isSuperAdmin() ? (values.role || 'enterprise_admin') : 'enterprise_admin';
      const organizationId = role === 'enterprise_admin'
        ? (isSuperAdmin() ? values.organization_id : currentUser?.organization_id)
        : null;
      return adminRequest<AdminItem>('/api/v1/admins', {
        method: 'POST',
        body: JSON.stringify({ ...values, role, organization_id: organizationId }),
      });
    },
    onSuccess: () => {
      void invalidate();
      setCreateModalOpen(false);
      createForm.resetFields();
      message.success('管理员创建成功');
    },
    onError: (error) => mutationError(error, '创建失败'),
  });

  const updateAdmin = useMutation({
    mutationFn: ({ id, data }: { id: number; data: { display_name?: string; is_active: boolean } }) => (
      adminRequest<AdminItem>(`/api/v1/admins/${id}`, { method: 'PATCH', body: JSON.stringify(data) })
    ),
    onSuccess: () => {
      void invalidate();
      setEditModalOpen(false);
      setEditingAdmin(null);
      message.success('管理员更新成功');
    },
    onError: (error) => mutationError(error, '更新失败'),
  });

  const deleteAdmin = useMutation({
    mutationFn: (id: number) => adminRequest<void>(`/api/v1/admins/${id}`, { method: 'DELETE' }),
    onSuccess: () => { void invalidate(); message.success('管理员已删除'); },
    onError: (error) => mutationError(error, '删除失败'),
  });

  const resetPassword = useMutation({
    mutationFn: ({ id, password }: { id: number; password: string }) => (
      adminRequest<AdminItem>(`/api/v1/admins/${id}`, { method: 'PATCH', body: JSON.stringify({ password }) })
    ),
    onSuccess: () => {
      setResetPwdAdmin(null);
      setNewPassword('');
      message.success('密码已重置');
    },
    onError: (error) => mutationError(error, '重置失败'),
  });

  const openCreate = () => {
    createForm.resetFields();
    createForm.setFieldsValue({
      role: 'enterprise_admin',
      organization_id: isSuperAdmin() ? undefined : currentUser?.organization_id,
    });
    setCreateModalOpen(true);
  };

  const canManage = (target: AdminItem) => (
    isSuperAdmin()
    || (target.role === 'enterprise_admin' && target.organization_id === currentUser?.organization_id)
  );

  return (
    <FinderShell>
      <TitleBar
        icon={<TeamOutlined />}
        title="管理员管理"
        extra={<Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>创建管理员</Button>}
      />

      <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
        {currentUser && (
          <Card size="small" style={{ marginBottom: 16 }}>
            <Descriptions column={4} size="small">
              <Descriptions.Item label="当前账号">{currentUser.username}</Descriptions.Item>
              <Descriptions.Item label="姓名">{currentUser.display_name || '-'}</Descriptions.Item>
              <Descriptions.Item label="角色"><Tag color={ROLE_COLORS[currentUser.role]}>{ROLE_LABELS[currentUser.role]}</Tag></Descriptions.Item>
              <Descriptions.Item label="管理范围">{isSuperAdmin() ? '全部企业' : currentUser.organization_name}</Descriptions.Item>
            </Descriptions>
          </Card>
        )}

        <Alert
          type="info"
          showIcon
          message={isSuperAdmin() ? '超级平台管理员可以管理全平台两类管理员' : '企业管理员只能管理本企业的企业管理员'}
          description="管理员只有两级。员工业务角色在“角色权限”中单独维护，不属于这里的管理员角色。管理员创建后不可改角色或所属企业。"
          style={{ marginBottom: 16 }}
        />

        <Table
          dataSource={adminList}
          rowKey="id"
          loading={isLoading}
          pagination={{ pageSize: 20 }}
          columns={[
            { title: '用户名', dataIndex: 'username', width: 220 },
            { title: '姓名', dataIndex: 'display_name', width: 150, render: (value: string | null) => value || '-' },
            {
              title: '角色', dataIndex: 'role', width: 150,
              render: (role: AdminRole) => <Tag color={ROLE_COLORS[role]}>{ROLE_LABELS[role] || role}</Tag>,
            },
            {
              title: '企业', dataIndex: 'organization_name', width: 180,
              render: (value: string | null) => value ? <Tag color="green">{value}</Tag> : <span style={{ color: '#999' }}>平台级</span>,
            },
            {
              title: '状态', dataIndex: 'is_active', width: 90,
              render: (active: boolean) => <Tag color={active ? 'green' : 'red'}>{active ? '活跃' : '停用'}</Tag>,
            },
            {
              title: '创建时间', dataIndex: 'created_at', width: 180,
              render: (value: string) => new Date(value).toLocaleString('zh-CN'),
            },
            {
              title: '操作', width: 250,
              render: (_: unknown, row: AdminItem) => canManage(row) ? <Space>
                <Button size="small" icon={<EditOutlined />} onClick={() => {
                  setEditingAdmin(row);
                  editForm.setFieldsValue({ display_name: row.display_name || undefined, is_active: row.is_active });
                  setEditModalOpen(true);
                }}>编辑</Button>
                {row.id !== currentUser?.id && <Button size="small" icon={<LockOutlined />} onClick={() => { setResetPwdAdmin(row); setNewPassword(''); }}>重置密码</Button>}
                {row.id !== currentUser?.id && <Button size="small" danger icon={<DeleteOutlined />} onClick={() => setConfirm({ id: row.id, name: row.username })}>删除</Button>}
              </Space> : <TypographyPlaceholder />,
            },
          ]}
        />
      </div>

      <Modal
        title="创建管理员"
        open={createModalOpen}
        onCancel={() => setCreateModalOpen(false)}
        onOk={() => createForm.submit()}
        confirmLoading={createAdmin.isPending}
        width={520}
      >
        <Form form={createForm} layout="vertical" onFinish={(values) => createAdmin.mutate(values)}>
          <Form.Item name="username" label="用户名" rules={[{ required: true, min: 2, message: '请输入用户名（至少2位）' }]}><Input autoComplete="off" /></Form.Item>
          <Form.Item name="password" label="初始密码" rules={[{ required: true, message: '请输入密码' }, { max: 128, message: '密码不能超过128位' }]}><Input.Password autoComplete="new-password" /></Form.Item>
          <Form.Item name="display_name" label="姓名"><Input /></Form.Item>
          {isSuperAdmin() ? <>
            <Form.Item name="role" label="角色" rules={[{ required: true }]}>
              <Select options={[
                { value: 'platform_super_admin', label: '超级平台管理员 — 管理整个平台' },
                { value: 'enterprise_admin', label: '企业管理员 — 只管理一个企业' },
              ]} />
            </Form.Item>
            {createRole === 'enterprise_admin' && (
              <Form.Item name="organization_id" label="所属企业" rules={[{ required: true, message: '请选择企业' }]}>
                <Select showSearch optionFilterProp="label" options={orgList.map((org) => ({ value: org.id, label: org.name }))} />
              </Form.Item>
            )}
          </> : (
            <Descriptions size="small" bordered column={1}>
              <Descriptions.Item label="角色">企业管理员</Descriptions.Item>
              <Descriptions.Item label="所属企业">{currentUser?.organization_name}</Descriptions.Item>
            </Descriptions>
          )}
        </Form>
      </Modal>

      <Modal
        title={`编辑：${editingAdmin?.username || ''}`}
        open={editModalOpen}
        onCancel={() => { setEditModalOpen(false); setEditingAdmin(null); }}
        onOk={() => editForm.submit()}
        confirmLoading={updateAdmin.isPending}
        width={500}
      >
        <Alert type="info" showIcon message="管理员角色和所属企业创建后不可修改" style={{ marginBottom: 16 }} />
        <Form form={editForm} layout="vertical" onFinish={(values) => {
          if (editingAdmin) updateAdmin.mutate({
            id: editingAdmin.id,
            data: { ...values, is_active: editingAdmin.id === currentUser?.id ? true : values.is_active },
          });
        }}>
          <Form.Item label="角色"><Input value={editingAdmin ? ROLE_LABELS[editingAdmin.role] : ''} disabled /></Form.Item>
          <Form.Item label="所属企业"><Input value={editingAdmin?.organization_name || '平台级'} disabled /></Form.Item>
          <Form.Item name="display_name" label="姓名"><Input /></Form.Item>
          <Form.Item name="is_active" label="启用" valuePropName="checked">
            <Switch disabled={editingAdmin?.id === currentUser?.id} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`重置密码：${resetPwdAdmin?.username || ''}`}
        open={!!resetPwdAdmin}
        onCancel={() => { setResetPwdAdmin(null); setNewPassword(''); }}
        onOk={() => { if (resetPwdAdmin) resetPassword.mutate({ id: resetPwdAdmin.id, password: newPassword }); }}
        confirmLoading={resetPassword.isPending}
        okButtonProps={{ disabled: newPassword.length < 1 || newPassword.length > 128 }}
      >
        <Alert type="warning" showIcon message="完整密码仅通过受控渠道交给该管理员" style={{ marginBottom: 16 }} />
        <Input.Password autoComplete="new-password" placeholder="输入新密码" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} />
      </Modal>

      <ConfirmModal
        open={!!confirm}
        title={<>确定删除管理员「{confirm?.name}」？</>}
        okText="删除"
        loading={deleteAdmin.isPending}
        onCancel={() => setConfirm(null)}
        onOk={() => { if (confirm) deleteAdmin.mutate(confirm.id); setConfirm(null); }}
      />
    </FinderShell>
  );
}

function TypographyPlaceholder() {
  return <span style={{ color: '#999' }}>无权操作</span>;
}
