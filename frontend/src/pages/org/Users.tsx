import { useState, useEffect, useMemo } from 'react';
import {
  Button, Modal, Table, Tag, Form, Input, Select, TreeSelect, Typography, Space,
  Alert, message,
} from 'antd';
import { PlusOutlined, DeleteOutlined, EditOutlined, LockOutlined, UserOutlined } from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { organizations, users } from '../../api/client';
import type { User } from '../../api/client';
import { ApiError } from '../../api/client';
import { useOrgTree } from '../../hooks/useOrgTree';
import OrgSelect from '../../components/OrgSelect';
import { FinderShell, TitleBar } from '../../components/finder/primitives';
import ConfirmModal from '../../components/finder/ConfirmModal';

const ROLE_LABELS: Record<string, string> = { admin: '组织管理员', member: '成员' };
const ROLE_COLORS: Record<string, string> = { admin: 'blue', member: 'default' };

export default function UsersPage() {
  const qc = useQueryClient();
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<User | null>(null);
  const [form] = Form.useForm();
  const [resetModalOpen, setResetModalOpen] = useState(false);
  const [resetTarget, setResetTarget] = useState<User | null>(null);
  const [newPassword, setNewPassword] = useState('');
  const [confirm, setConfirm] = useState<{ id: string; name: string } | null>(null);

  const { data: orgs } = useQuery({ queryKey: ['orgs'], queryFn: organizations.list });
  const [selectedOrgId, setSelectedOrgId] = useState<string | undefined>();
  const orgId = selectedOrgId ?? orgs?.find(o => o.is_default)?.id ?? orgs?.[0]?.id;

  const { data: userList, isLoading } = useQuery({
    queryKey: ['users', orgId],
    queryFn: () => orgId ? users.list(orgId) : Promise.resolve([]),
    enabled: !!orgId,
  });

  // 组织架构树：用于「所属」选择器；nodeMap 已含全部 org/dept/team 元信息，
  // 选中节点后据此自动解析出 department_id / team_id（驱动终端资源 scope 与长期记忆载入）
  const { treeData, nodeMap } = useOrgTree();
  const deptName = (id: string | null) => (id ? nodeMap.get(`dept:${id}`)?.name : undefined);
  const teamName = (id: string | null) => (id ? nodeMap.get(`team:${id}`)?.name : undefined);

  // 仅展示当前组织下的子树（组织 → 部门 → 团队），避免跨组织误选
  const belongTree = useMemo(() => {
    if (!orgId) return [];
    const root = treeData.find(n => n.value === `org:${orgId}`);
    return root ? [root] : [];
  }, [treeData, orgId]);

  // 所属节点 value → { department_id, team_id }
  const resolveBelong = (val: string | undefined): { department_id: string | null; team_id: string | null } => {
    if (!val) return { department_id: null, team_id: null };
    const node = nodeMap.get(val);
    if (!node) return { department_id: null, team_id: null };
    if (node.type === 'team') return { department_id: node.deptId ?? null, team_id: node.id };
    if (node.type === 'department') return { department_id: node.id, team_id: null };
    return { department_id: null, team_id: null }; // 组织级：仅绑定组织
  };
  // { department_id, team_id } → 所属节点 value（编辑回填用）
  const toBelongValue = (deptId: string | null, teamId: string | null): string | undefined => {
    if (teamId) return `team:${teamId}`;
    if (deptId) return `dept:${deptId}`;
    return orgId ? `org:${orgId}` : undefined;
  };

  const isEdit = !!editing;

  const openCreate = () => { setEditing(null); form.resetFields(); setModalOpen(true); };
  const openEdit = (r: User) => { setEditing(r); setModalOpen(true); };
  const openReset = (r: User) => { setResetTarget(r); setNewPassword(''); setResetModalOpen(true); };
  const closeReset = () => { setResetModalOpen(false); setResetTarget(null); setNewPassword(''); };

  useEffect(() => {
    if (modalOpen && editing) {
      form.setFieldsValue({
        username: editing.username,
        display_name: editing.display_name,
        is_active: editing.is_active,
        belongTo: toBelongValue(editing.department_id, editing.team_id),
      });
    }
  }, [modalOpen, editing, form]);

  const closeModal = () => { setModalOpen(false); setEditing(null); form.resetFields(); };

  const createUser = useMutation({
    mutationFn: (data: { username: string; display_name?: string | null; role: string; is_active: boolean; password: string; department_id?: string | null; team_id?: string | null }) => {
      if (!orgId) { message.error('请先创建组织'); return Promise.reject(new Error('No org')); }
      return users.create(orgId, data);
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['users'] }); closeModal(); message.success('用户已创建'); },
    onError: (err: unknown) => { const msg = err instanceof ApiError ? err.message : '创建失败'; message.error(msg); },
  });

  const updateUser = useMutation({
    mutationFn: (data: Partial<User>) => {
      if (!editing) return Promise.reject(new Error('No user'));
      return users.update(editing.id, data);
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['users'] }); closeModal(); message.success('用户已更新'); },
    onError: (err: unknown) => { const msg = err instanceof ApiError ? err.message : '更新失败'; message.error(msg); },
  });

  const resetPassword = useMutation({
    mutationFn: ({ id, password }: { id: string; password: string }) => users.resetPassword(id, password),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['users'] }); closeReset(); message.success('密码已重置，请安全地通知该用户'); },
    onError: (err: unknown) => { const msg = err instanceof ApiError ? err.message : '重置失败'; message.error(msg); },
  });

  const submit = (v: Record<string, unknown>) => {
    // 「所属」树节点 → department_id / team_id，选择部门/团队后自动绑定
    const { department_id, team_id } = resolveBelong(v.belongTo as string | undefined);
    const payload = {
      username: v.username,
      display_name: v.display_name,
      role: 'member',
      is_active: v.is_active,
      password: v.password,
      department_id,
      team_id,
    };
    if (isEdit) {
      const { password, ...updatePayload } = payload;
      updateUser.mutate(updatePayload as Partial<User>);
    } else {
      createUser.mutate(payload as Parameters<typeof createUser.mutate>[0]);
    }
  };

  const deleteUser = useMutation({
    mutationFn: (id: string) => users.delete(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['users'] }); message.success('用户已删除'); },
    onError: () => { message.error('删除失败'); },
  });

  return (
    <FinderShell>
      <TitleBar
        icon={<UserOutlined />}
        title="用户管理"
        titleExtra={<OrgSelect value={orgId} onChange={setSelectedOrgId} />}
        extra={<Button type="primary" icon={<PlusOutlined />} onClick={openCreate} disabled={!orgId}>新建用户</Button>}
      />

      <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
        <Table
          dataSource={userList ?? []}
          rowKey="id"
          loading={isLoading}
          pagination={{ pageSize: 20 }}
          columns={[
            { title: '用户名', dataIndex: 'username', width: 280 },
            { title: '显示名', dataIndex: 'display_name', width: 200 },
            {
              title: '角色', dataIndex: 'role', width: 120,
              render: (v: string) => <Tag color={ROLE_COLORS[v]}>{ROLE_LABELS[v] || v}</Tag>,
            },
            {
              title: '部门', dataIndex: 'department_id', width: 140,
              render: (id: string | null) => (id ? <Tag color="cyan">{deptName(id) ?? id}</Tag> : <Typography.Text type="secondary">—</Typography.Text>),
            },
            {
              title: '团队', dataIndex: 'team_id', width: 140,
              render: (id: string | null) => (id ? <Tag color="geekblue">{teamName(id) ?? id}</Tag> : <Typography.Text type="secondary">—</Typography.Text>),
            },
            {
              title: '状态', dataIndex: 'is_active', width: 80,
              render: (v: boolean) => <Tag color={v ? 'green' : 'red'}>{v ? '启用' : '停用'}</Tag>,
            },
            {
              title: '操作', width: 230, fixed: 'right',
              render: (_: unknown, r: User) => (
                <Space size="small">
                  <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(r)}>编辑</Button>
                  <Button size="small" icon={<LockOutlined />} onClick={() => openReset(r)}>重置密码</Button>
                  <Button size="small" danger icon={<DeleteOutlined />} onClick={() => setConfirm({ id: r.id, name: r.username })}>删除</Button>
                </Space>
              ),
            },
          ]}
        />
      </div>

      <Modal
        title={isEdit ? '编辑用户' : '新建用户'}
        open={modalOpen}
        onCancel={closeModal}
        onOk={() => form.submit()}
        confirmLoading={createUser.isPending || updateUser.isPending}
        width={560}
      >
        <Form form={form} layout="vertical" onFinish={submit}>
          <Form.Item name="username" label="用户名" rules={[{ required: true, min: 2, message: '请输入用户名（至少2位）' }]}>
            <Input placeholder="用户名（同一组织内不可同名）" />
          </Form.Item>
          <Form.Item name="display_name" label="显示名">
            <Input placeholder="张三" />
          </Form.Item>
          {isEdit && (
            <Form.Item name="is_active" label="状态" initialValue={true}>
              <Select options={[{ value: true, label: '启用' }, { value: false, label: '停用' }]} />
            </Form.Item>
          )}
          <Form.Item
            name="belongTo"
            label="所属"
            tooltip="选择用户所属的组织架构节点；选中部门/团队后自动绑定对应的部门与团队，驱动终端资源 scope 与长期记忆"
            rules={[{ required: true, message: '请选择所属组织架构节点' }]}
          >
            <TreeSelect
              treeData={belongTree}
              treeDefaultExpandAll
              showSearch
              treeNodeFilterProp="title"
              allowClear
              placeholder="选择所属（组织 / 部门 / 团队）"
            />
          </Form.Item>
          {!isEdit && (
            <Form.Item
              name="password"
              label="初始密码"
              rules={[{ required: true, min: 8, message: '密码至少 8 位' }]}
              extra="创建后该用户下次登录需修改密码"
            >
              <Input.Password placeholder="至少 8 位" />
            </Form.Item>
          )}
        </Form>
      </Modal>

      {/* 重置密码 Modal */}
      <Modal
        title={`重置密码：${resetTarget?.username ?? ''}`}
        open={resetModalOpen}
        onCancel={closeReset}
        onOk={() => {
          if (resetTarget && newPassword.length >= 8) {
            resetPassword.mutate({ id: resetTarget.id, password: newPassword });
          }
        }}
        okButtonProps={{ disabled: newPassword.length < 8, loading: resetPassword.isPending }}
      >
        <Alert type="warning" message="重置后该用户下次登录强制修改密码，请将新密码安全地通知该用户" style={{ marginBottom: 16 }} />
        <Input.Password
          placeholder="输入新密码（至少 8 位）"
          value={newPassword}
          onChange={e => setNewPassword(e.target.value)}
        />
      </Modal>

      <ConfirmModal
        open={!!confirm}
        title={<>确定删除用户「{confirm?.name}」？</>}
        okText="删除"
        loading={deleteUser.isPending}
        onCancel={() => setConfirm(null)}
        onOk={() => { if (confirm) deleteUser.mutate(confirm.id); setConfirm(null); }}
      />
    </FinderShell>
  );
}
