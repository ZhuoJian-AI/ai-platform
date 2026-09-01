import { useState, useEffect, useMemo } from 'react';
import {
  Button, Modal, Table, Tag, Form, Input, Select, Typography, Space,
  Alert, message,
} from 'antd';
import { PlusOutlined, DeleteOutlined, EditOutlined, LockOutlined, UserOutlined } from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { organizations, users } from '../../api/client';
import type { ManagerScopeGrant, User } from '../../api/client';
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
  const watchedDepartmentId = Form.useWatch('department_id', form) as string | undefined;
  const watchedTeamId = Form.useWatch('team_id', form) as string | undefined;
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

  const { nodeMap } = useOrgTree();
  const deptName = (id: string | null) => (id ? nodeMap.get(`dept:${id}`)?.name : undefined);
  const teamName = (id: string | null) => (id ? nodeMap.get(`team:${id}`)?.name : undefined);

  const departmentOptions = useMemo(() => Array.from(nodeMap.values())
    .filter(node => node.type === 'department' && node.orgId === orgId)
    .map(node => ({ value: node.id, label: node.name }))
    .sort((a, b) => a.label.localeCompare(b.label, 'zh-CN')), [nodeMap, orgId]);

  const teamOptions = useMemo(() => {
    return Array.from(nodeMap.values())
      .filter(node => node.type === 'team' && node.orgId === orgId && node.deptId === watchedDepartmentId)
      .map(node => ({ value: node.id, label: `${deptName(node.deptId ?? null) ?? ''} / ${node.name}` }))
      .sort((a, b) => a.label.localeCompare(b.label, 'zh-CN'));
  }, [nodeMap, orgId, watchedDepartmentId]);

  const isEdit = !!editing;

  const managerOptions = useMemo(() => {
    const options: { value: string; label: string }[] = [];
    if (watchedDepartmentId) options.push({
      value: `department:${watchedDepartmentId}`,
      label: `部门负责人：${deptName(watchedDepartmentId) ?? watchedDepartmentId}`,
    });
    if (watchedTeamId) options.push({
      value: `team:${watchedTeamId}`,
      label: `团队负责人：${teamName(watchedTeamId) ?? watchedTeamId}`,
    });
    return options;
  }, [watchedDepartmentId, watchedTeamId, nodeMap]);

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
        department_id: editing.department_id ?? editing.department_ids?.[0] ?? undefined,
        team_id: editing.team_id ?? undefined,
        manager_scope_keys: (editing.manager_scopes ?? []).map((grant) => `${grant.scope_type}:${grant.scope_id}`),
      });
    }
  }, [modalOpen, editing, form]);

  const closeModal = () => { setModalOpen(false); setEditing(null); form.resetFields(); };

  const createUser = useMutation({
    mutationFn: (data: {
      username: string; display_name?: string | null; role: string; is_active: boolean; password: string;
      department_ids?: string[]; department_id?: string | null; team_id?: string | null;
      manager_scopes?: ManagerScopeGrant[];
    }) => {
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
    const department_id = (v.department_id as string | undefined) ?? null;
    const team_id = (v.team_id as string | undefined) ?? null;
    const manager_scopes = ((v.manager_scope_keys as string[] | undefined) ?? []).map((key) => {
      const [scope_type, scope_id] = key.split(':');
      return { scope_type, scope_id } as ManagerScopeGrant;
    });
    const payload = {
      username: v.username,
      display_name: v.display_name,
      role: 'member',
      is_active: v.is_active,
      password: v.password,
      // department_ids 仅保留为旧客户端兼容字段，服务端强制最多一个部门。
      department_ids: department_id ? [department_id] : [],
      department_id,
      team_id,
      manager_scopes,
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
              title: '所属部门', dataIndex: 'department_id', width: 200,
              render: (id: string | null, record: User) => {
                const departmentId = id ?? record.department_ids?.[0];
                return departmentId
                  ? <Tag color="blue">{deptName(departmentId) ?? departmentId}</Tag>
                  : <Typography.Text type="secondary">—</Typography.Text>;
              },
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
              title: '负责人授权', dataIndex: 'manager_scopes', width: 180,
              render: (grants: ManagerScopeGrant[] | undefined) => (grants?.length
                ? grants.map((grant) => <Tag key={`${grant.scope_type}:${grant.scope_id}`} color="purple">
                    {grant.scope_type === 'department' ? '部门负责人' : '团队负责人'}
                  </Tag>)
                : <Typography.Text type="secondary">—</Typography.Text>),
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
            name="department_id"
            label="所属部门"
            tooltip="一个用户只归属一个部门；可见的应用和子模块请在“应用权限”中单独授权。"
            rules={[{ required: true, message: '请选择所属部门' }]}
          >
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              options={departmentOptions}
              placeholder="选择一个所属部门"
              onChange={(departmentId?: string) => {
                const currentTeamId = form.getFieldValue('team_id') as string | undefined;
                const currentTeam = currentTeamId ? nodeMap.get(`team:${currentTeamId}`) : undefined;
                if (currentTeam?.deptId && currentTeam.deptId !== departmentId) {
                  form.setFieldValue('team_id', undefined);
                }
                form.setFieldValue('manager_scope_keys', []);
              }}
            />
          </Form.Item>
          <Form.Item
            name="team_id"
            label="所属团队（可选）"
            extra="团队只能从当前所属部门中选择，不会改变用户的部门归属。"
          >
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              options={teamOptions}
              placeholder={watchedDepartmentId ? '选择一个所属团队' : '请先选择所属部门'}
              disabled={!watchedDepartmentId}
              onChange={() => form.setFieldValue('manager_scope_keys', [])}
            />
          </Form.Item>
          <Form.Item
            name="manager_scope_keys"
            label="技能负责人授权"
            extra="负责人可上传、升级、停用其范围内的 Skill；部门负责人同时可管理下属团队 Skill。普通成员留空。"
          >
            <Select
              mode="multiple"
              allowClear
              options={managerOptions}
              placeholder={managerOptions.length ? '可选：任命为当前部门/团队负责人' : '请先选择部门或团队'}
              disabled={!managerOptions.length}
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
