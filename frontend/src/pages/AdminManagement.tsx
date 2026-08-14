import { useState } from 'react';
import {
  Button, Card, Modal, Table, Tag, Form, Input, Select, Switch,
  Space, message, Alert, Descriptions,
} from 'antd';
import {
  PlusOutlined, DeleteOutlined, EditOutlined, LockOutlined, TeamOutlined,
} from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useAuth } from '../context/AuthContext';
import { organizations as orgApi } from '../api/client';
import { FinderShell, TitleBar } from '../components/finder/primitives';
import ConfirmModal from '../components/finder/ConfirmModal';

const BASE_URL = import.meta.env.VITE_API_BASE_URL || '';

function getAuthHeaders() {
  const token = localStorage.getItem('ai_infra_token');
  return { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` };
}

interface AdminItem {
  id: number;
  username: string;
  display_name: string | null;
  role: string;
  is_active: boolean;
  organization_id?: string | null;
  organization_name?: string | null;
  created_at: string;
  updated_at: string;
}

export default function AdminManagement() {
  const qc = useQueryClient();
  const { admin: currentUser, isSuperAdmin } = useAuth();
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [editingAdmin, setEditingAdmin] = useState<AdminItem | null>(null);
  const [createForm] = Form.useForm();
  const [editForm] = Form.useForm();
  const [resetPwdModalOpen, setResetPwdModalOpen] = useState(false);
  const [resetPwdAdmin, setResetPwdAdmin] = useState<AdminItem | null>(null);
  const [newPassword, setNewPassword] = useState('');
  const [confirm, setConfirm] = useState<{ id: number; name: string } | null>(null);

  const { data: adminList, isLoading } = useQuery({
    queryKey: ['admins'],
    queryFn: async () => {
      const resp = await fetch(`${BASE_URL}/api/v1/admins`, { headers: getAuthHeaders() });
      if (!resp.ok) throw new Error('获取管理员列表失败');
      return resp.json() as Promise<AdminItem[]>;
    },
    enabled: isSuperAdmin(),
  });

  // 创建管理员
  const createAdmin = useMutation({
    mutationFn: async (data: { username: string; password: string; display_name?: string; role: string; organization_id?: string | null }) => {
      const resp = await fetch(`${BASE_URL}/api/v1/admins`, {
        method: 'POST', headers: getAuthHeaders(), body: JSON.stringify(data),
      });
      if (!resp.ok) { const b = await resp.json().catch(() => ({})); throw new Error(b.detail || '创建失败'); }
      return resp.json();
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['admins'] }); setCreateModalOpen(false); createForm.resetFields(); message.success('管理员创建成功'); },
  });

  // 组织列表（用于指派 org_admin）
  const { data: orgList } = useQuery({ queryKey: ['orgs'], queryFn: orgApi.list });
  const createRole = Form.useWatch('role', createForm) as string | undefined;
  const editRole = Form.useWatch('role', editForm) as string | undefined;

  // 更新管理员
  const updateAdmin = useMutation({
    mutationFn: async ({ id, data }: { id: number; data: Record<string, unknown> }) => {
      const resp = await fetch(`${BASE_URL}/api/v1/admins/${id}`, {
        method: 'PATCH', headers: getAuthHeaders(), body: JSON.stringify(data),
      });
      if (!resp.ok) { const b = await resp.json().catch(() => ({})); throw new Error(b.detail || '更新失败'); }
      return resp.json();
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['admins'] }); setEditModalOpen(false); setEditingAdmin(null); message.success('管理员更新成功'); },
  });

  // 删除管理员
  const deleteAdmin = useMutation({
    mutationFn: async (id: number) => {
      const resp = await fetch(`${BASE_URL}/api/v1/admins/${id}`, {
        method: 'DELETE', headers: getAuthHeaders(),
      });
      if (!resp.ok) { const b = await resp.json().catch(() => ({})); throw new Error(b.detail || '删除失败'); }
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['admins'] }); message.success('管理员已删除'); },
  });

  // 重置密码
  const resetPassword = useMutation({
    mutationFn: async ({ id, password }: { id: number; password: string }) => {
      const resp = await fetch(`${BASE_URL}/api/v1/admins/${id}`, {
        method: 'PATCH', headers: getAuthHeaders(), body: JSON.stringify({ password }),
      });
      if (!resp.ok) { const b = await resp.json().catch(() => ({})); throw new Error(b.detail || '重置失败'); }
      return resp.json();
    },
    onSuccess: () => { setResetPwdModalOpen(false); setResetPwdAdmin(null); setNewPassword(''); message.success('密码已重置'); },
  });

  const ROLE_LABELS: Record<string, string> = { super_admin: '超级管理员', admin: '管理员', org_admin: '组织管理员' };
  const ROLE_COLORS: Record<string, string> = { super_admin: 'red', admin: 'blue', org_admin: 'geekblue' };

  return (
    <FinderShell>
      <TitleBar
        icon={<TeamOutlined />}
        title="管理员管理"
        extra={isSuperAdmin() ? (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateModalOpen(true)}>创建管理员</Button>
        ) : undefined}
      />

      <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
        {/* 当前账号信息 */}
        {currentUser && (
          <Card size="small" style={{ marginBottom: 16 }}>
            <Descriptions column={4} size="small">
              <Descriptions.Item label="当前账号">{currentUser.username}</Descriptions.Item>
              <Descriptions.Item label="姓名">{currentUser.display_name || '-'}</Descriptions.Item>
              <Descriptions.Item label="角色"><Tag color={ROLE_COLORS[currentUser.role]}>{ROLE_LABELS[currentUser.role]}</Tag></Descriptions.Item>
              <Descriptions.Item label="状态">{currentUser.is_active ? '✅ 活跃' : '❌ 停用'}</Descriptions.Item>
            </Descriptions>
          </Card>
        )}

        {!isSuperAdmin() && (
          <Alert type="info" message="仅超级管理员可查看和管理其他管理员账号" style={{ marginBottom: 16 }} />
        )}

        {isSuperAdmin() && (
          <Table
            dataSource={adminList ?? []}
            rowKey="id"
            loading={isLoading}
            pagination={{ pageSize: 20 }}
            columns={[
              { title: 'ID', dataIndex: 'id', width: 60 },
              { title: '用户名', dataIndex: 'username', width: 240 },
              { title: '姓名', dataIndex: 'display_name', width: 150, render: (v: string | null) => v || '-' },
              {
                title: '角色', dataIndex: 'role', width: 120,
                render: (v: string) => <Tag color={ROLE_COLORS[v]}>{ROLE_LABELS[v] || v}</Tag>,
              },
              {
                title: '组织', dataIndex: 'organization_name', width: 160,
                render: (v: string | null) => v ? <Tag color="green">{v}</Tag> : <span style={{ color: '#999' }}>平台级</span>,
              },
              {
                title: '状态', dataIndex: 'is_active', width: 80,
                render: (v: boolean) => v ? <Tag color="green">活跃</Tag> : <Tag color="red">停用</Tag>,
              },
              {
                title: '创建时间', dataIndex: 'created_at', width: 180,
                render: (v: string) => new Date(v).toLocaleString('zh-CN'),
              },
              {
                title: '操作', width: 240,
                render: (_: unknown, r: AdminItem) => (
                  <Space>
                    <Button
                      size="small"
                      icon={<EditOutlined />}
                      onClick={() => { setEditingAdmin(r); editForm.setFieldsValue(r); setEditModalOpen(true); }}
                    >
                      编辑
                    </Button>
                    <Button
                      size="small"
                      icon={<LockOutlined />}
                      onClick={() => { setResetPwdAdmin(r); setResetPwdModalOpen(true); }}
                    >
                      重置密码
                    </Button>
                    {r.id !== currentUser?.id && (
                      <Button size="small" danger icon={<DeleteOutlined />} onClick={() => setConfirm({ id: r.id, name: r.username })}>删除</Button>
                    )}
                  </Space>
                ),
              },
            ]}
          />
        )}
      </div>

      {/* 创建管理员 Modal */}
      <Modal
        title="创建管理员"
        open={createModalOpen}
        onCancel={() => setCreateModalOpen(false)}
        onOk={() => createForm.submit()}
        width={500}
      >
        <Form form={createForm} layout="vertical" onFinish={v => createAdmin.mutate(v)}>
          <Form.Item name="username" label="用户名" rules={[{ required: true, min: 2, message: '请输入用户名（至少2位）' }]}>
            <Input placeholder="admin" />
          </Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true, min: 8 }]}>
            <Input.Password placeholder="至少8位" />
          </Form.Item>
          <Form.Item name="display_name" label="姓名">
            <Input placeholder="张三" />
          </Form.Item>
          <Form.Item name="role" label="角色" rules={[{ required: true }]} initialValue="admin">
            <Select options={[
              { value: 'super_admin', label: '🔴 超级管理员 — 可创建/删除管理员，管理所有资源' },
              { value: 'admin', label: '🔵 管理员 — 管理组织/Key/规则等，不可管理管理员' },
              { value: 'org_admin', label: '🟢 组织管理员 — 仅管理被指派的单个组织' },
            ]} />
          </Form.Item>
          {createRole === 'org_admin' && (
            <Form.Item name="organization_id" label="所属组织" rules={[{ required: true, message: '请选择组织' }]}>
              <Select
                placeholder="选择该管理员负责的组织"
                options={orgList?.map(o => ({ value: o.id, label: o.name })) ?? []}
                showSearch
                optionFilterProp="label"
              />
            </Form.Item>
          )}
        </Form>
      </Modal>

      {/* 编辑管理员 Modal */}
      <Modal
        title={`编辑：${editingAdmin?.username}`}
        open={editModalOpen}
        onCancel={() => { setEditModalOpen(false); setEditingAdmin(null); }}
        onOk={() => editForm.submit()}
        width={500}
      >
        <Form form={editForm} layout="vertical" onFinish={v => {
          if (editingAdmin) updateAdmin.mutate({ id: editingAdmin.id, data: v });
        }}>
          <Form.Item name="display_name" label="姓名">
            <Input placeholder="张三" />
          </Form.Item>
          <Form.Item name="role" label="角色">
            <Select options={[
              { value: 'super_admin', label: '超级管理员' },
              { value: 'admin', label: '管理员' },
              { value: 'org_admin', label: '组织管理员' },
            ]} />
          </Form.Item>
          {editRole === 'org_admin' && (
            <Form.Item name="organization_id" label="所属组织" rules={[{ required: true, message: '请选择组织' }]}>
              <Select
                placeholder="选择该管理员负责的组织"
                options={orgList?.map(o => ({ value: o.id, label: o.name })) ?? []}
                showSearch
                optionFilterProp="label"
              />
            </Form.Item>
          )}
          <Form.Item name="is_active" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      {/* 重置密码 Modal */}
      <Modal
        title={`重置密码：${resetPwdAdmin?.username}`}
        open={resetPwdModalOpen}
        onCancel={() => { setResetPwdModalOpen(false); setResetPwdAdmin(null); }}
        onOk={() => {
          if (resetPwdAdmin && newPassword.length >= 8) {
            resetPassword.mutate({ id: resetPwdAdmin.id, password: newPassword });
          }
        }}
        okButtonProps={{ disabled: newPassword.length < 8 }}
      >
        <Alert type="warning" message="重置后请将新密码安全地通知该管理员" style={{ marginBottom: 16 }} />
        <Input.Password
          placeholder="输入新密码（至少8位）"
          value={newPassword}
          onChange={e => setNewPassword(e.target.value)}
        />
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
