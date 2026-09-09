import { useState, useEffect, useMemo } from 'react';
import {
  Button, Modal, Table, Tag, Form, Input, Select, Typography, Space,
  Alert, message,
} from 'antd';
import { PlusOutlined, DeleteOutlined, EditOutlined, LockOutlined, UserOutlined } from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { organizations, roles, users } from '../../api/client';
import type { User } from '../../api/client';
import { ApiError } from '../../api/client';
import { useOrgTree } from '../../hooks/useOrgTree';
import OrgSelect from '../../components/OrgSelect';
import { FinderShell, TitleBar } from '../../components/finder/primitives';
import ConfirmModal from '../../components/finder/ConfirmModal';

export default function UsersPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<User | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [conflictUser, setConflictUser] = useState<User | null>(null);
  const [searchText, setSearchText] = useState('');
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
  const { data: roleList = [] } = useQuery({
    queryKey: ['roles', orgId],
    queryFn: () => orgId ? roles.list(orgId) : Promise.resolve([]),
    enabled: !!orgId,
  });

  const { nodeMap } = useOrgTree();
  const deptName = (id: string | null) => (id ? nodeMap.get(`dept:${id}`)?.name : undefined);

  const departmentOptions = useMemo(() => Array.from(nodeMap.values())
    .filter(node => node.type === 'department' && node.orgId === orgId)
    .sort((a, b) => (a.sortOrder ?? Number.MAX_SAFE_INTEGER) - (b.sortOrder ?? Number.MAX_SAFE_INTEGER))
    .map(node => ({ value: node.id, label: node.name })), [nodeMap, orgId]);

  const isEdit = !!editing;
  const activeRoleIds = useMemo(
    () => new Set(roleList.filter(role => role.is_active).map(role => role.id)),
    [roleList],
  );
  const filteredUsers = useMemo(() => {
    const keyword = searchText.trim().toLocaleLowerCase();
    if (!keyword) return userList ?? [];
    return (userList ?? []).filter(user => [
      user.username,
      user.display_name ?? '',
      deptName(user.department_id ?? user.department_ids?.[0] ?? null) ?? '',
    ].some(value => value.toLocaleLowerCase().includes(keyword)));
  }, [userList, searchText, nodeMap]);

  const openCreate = () => {
    setEditing(null);
    setSubmitError(null);
    setConflictUser(null);
    form.resetFields();
    const employeeRole = roleList.find(role => role.code === 'employee' && role.is_active);
    form.setFieldsValue({ role_ids: employeeRole ? [employeeRole.id] : [], is_active: true });
    setModalOpen(true);
  };
  const openEdit = (r: User) => {
    setEditing(r);
    setSubmitError(null);
    setConflictUser(null);
    setModalOpen(true);
  };
  const openReset = (r: User) => { setResetTarget(r); setNewPassword(''); setResetModalOpen(true); };
  const closeReset = () => { setResetModalOpen(false); setResetTarget(null); setNewPassword(''); };

  useEffect(() => {
    if (modalOpen && editing) {
      form.setFieldsValue({
        username: editing.username,
        display_name: editing.display_name,
        is_active: editing.is_active,
        // 历史数据可能仍指向已停用或已删除角色。不可把这些不可见 UUID
        // 带回提交，否则一次正常的员工修改也会被服务端整体拒绝。
        role_ids: (editing.role_ids ?? []).filter(roleId => activeRoleIds.has(roleId)),
        department_id: editing.department_id ?? editing.department_ids?.[0] ?? undefined,
      });
    }
  }, [modalOpen, editing, form, activeRoleIds]);

  const closeModal = () => {
    setModalOpen(false);
    setEditing(null);
    setSubmitError(null);
    setConflictUser(null);
    form.resetFields();
  };

  const createUser = useMutation({
    mutationFn: (data: {
      username: string; display_name?: string | null; role: string; is_active: boolean; password: string;
      role_ids?: string[];
      department_ids?: string[]; department_id?: string | null;
    }) => {
      if (!orgId) { message.error('请先创建组织'); return Promise.reject(new Error('No org')); }
      return users.create(orgId, data);
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['users'] }); closeModal(); message.success('用户已创建'); },
    onError: (err: unknown) => {
      if (err instanceof ApiError && err.status === 409) {
        const username = String(form.getFieldValue('username') ?? '').trim();
        const normalizedUsername = username.toLocaleLowerCase();
        const existing = (userList ?? []).find(
          user => user.username.toLocaleLowerCase() === normalizedUsername,
        ) ?? null;
        const existingDepartment = existing
          ? deptName(existing.department_id ?? existing.department_ids?.[0] ?? null)
          : undefined;
        const msg = existing
          ? `用户名“${username}”已由${existingDepartment ? `${existingDepartment}员工` : '现有员工'}“${existing.display_name || existing.username}”使用`
          : err.message;
        setConflictUser(existing);
        setSubmitError(msg);
        form.setFields([{ name: 'username', errors: [msg] }]);
        return;
      }
      const msg = err instanceof ApiError ? err.message : '创建失败，请稍后重试';
      setSubmitError(msg);
      message.error(msg);
    },
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
    if (createUser.isPending || updateUser.isPending) return;
    setSubmitError(null);
    const department_id = (v.department_id as string | undefined) ?? null;
    const payload = {
      username: v.username,
      display_name: v.display_name,
      role: 'member',
      role_ids: (v.role_ids as string[] | undefined) ?? [],
      is_active: v.is_active,
      password: v.password,
      // department_ids 仅保留为旧客户端兼容字段，服务端强制最多一个部门。
      department_ids: department_id ? [department_id] : [],
      department_id,
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
        title="员工授权"
        titleExtra={<OrgSelect value={orgId} onChange={setSelectedOrgId} />}
        extra={<Button type="primary" icon={<PlusOutlined />} onClick={openCreate} disabled={!orgId}>新建员工</Button>}
      />

      <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
        <Input.Search
          allowClear
          value={searchText}
          onChange={event => setSearchText(event.target.value)}
          placeholder="搜索用户名、显示名或部门"
          style={{ width: 320, marginBottom: 12 }}
        />
        <Table
          dataSource={filteredUsers}
          rowKey="id"
          loading={isLoading}
          pagination={{ pageSize: 20 }}
          columns={[
            { title: '用户名', dataIndex: 'username', width: 280 },
            { title: '显示名', dataIndex: 'display_name', width: 200 },
            {
              title: '角色', dataIndex: 'roles', width: 220,
              render: (_: unknown, record: User) => (record.roles?.length
                ? record.roles.map(role => (
                    <Tag key={role.id} color={role.is_builtin ? 'blue' : 'purple'}>{role.name}</Tag>
                  ))
                : <Typography.Text type="secondary">未分配</Typography.Text>),
            },
            {
              title: '所属部门', dataIndex: 'department_id', width: 200,
              render: (id: string | null, record: User) => {
                const departmentId = id ?? record.department_ids?.[0];
                return departmentId
                  ? (deptName(departmentId)
                    ? <Tag color="blue">{deptName(departmentId)}</Tag>
                    : <Tag color="red">原部门已删除，请重新选择</Tag>)
                  : <Typography.Text type="secondary">—</Typography.Text>;
              },
            },
            {
              title: '状态', dataIndex: 'is_active', width: 80,
              render: (v: boolean) => <Tag color={v ? 'green' : 'red'}>{v ? '启用' : '停用'}</Tag>,
            },
            {
              title: '操作', width: 310, fixed: 'right',
              render: (_: unknown, r: User) => (
                <Space size="small">
                  <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(r)}>编辑</Button>
                  <Button size="small" icon={<UserOutlined />} onClick={() => navigate(`/enterprise-apps/permissions?user=${r.id}`)}>访问预览</Button>
                  <Button size="small" icon={<LockOutlined />} onClick={() => openReset(r)}>重置密码</Button>
                  <Button size="small" danger icon={<DeleteOutlined />} onClick={() => setConfirm({ id: r.id, name: r.username })}>删除</Button>
                </Space>
              ),
            },
          ]}
        />
      </div>

      <Modal
        title={isEdit ? '编辑员工' : '新建员工'}
        open={modalOpen}
        onCancel={closeModal}
        onOk={() => form.submit()}
        confirmLoading={createUser.isPending || updateUser.isPending}
        width={560}
      >
        <Form form={form} layout="vertical" onFinish={submit}>
          {submitError && (
            <Alert
              type="error"
              showIcon
              message="员工保存失败"
              description={submitError}
              action={conflictUser ? (
                <Button
                  size="small"
                  onClick={() => {
                    setSearchText(conflictUser.username);
                    closeModal();
                  }}
                >
                  查看已有员工
                </Button>
              ) : undefined}
              style={{ marginBottom: 16 }}
            />
          )}
          <Form.Item name="username" label="用户名" rules={[{ required: true, min: 2, message: '请输入用户名（至少2位）' }]}>
            <Input
              placeholder="用户名（同一组织内不可同名）"
              autoComplete="off"
              onChange={() => {
                setSubmitError(null);
                setConflictUser(null);
                form.setFields([{ name: 'username', errors: [] }]);
              }}
            />
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
            name="department_id"
            label="所属部门"
            tooltip="一个员工只归属一个部门；部门只记录组织关系，不直接授予企业模块权限。"
            rules={[{ required: true, message: '请选择所属部门' }]}
          >
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              options={departmentOptions}
              placeholder="选择一个所属部门"
            />
          </Form.Item>
          <Form.Item
            name="role_ids"
            label="角色（可多选）"
            extra="企业模块、业务子模块、最小页面、页面操作和 AI 权限由一个或多个角色叠加决定。"
            rules={[{ required: true, message: '请至少选择一个角色' }]}
          >
            <Select
              mode="multiple"
              showSearch
              optionFilterProp="label"
              options={roleList.filter(role => role.is_active).map(role => ({
                value: role.id,
                label: `${role.name}${role.is_builtin ? '（内置）' : ''}`,
              }))}
              placeholder="选择一个或多个角色"
            />
          </Form.Item>
          {!isEdit && (
            <Form.Item
              name="password"
              label="初始密码"
              rules={[{ required: true, min: 8, message: '密码至少 8 位' }]}
              extra="创建后该用户下次登录需修改密码"
            >
              <Input.Password placeholder="至少 8 位" autoComplete="new-password" />
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
