import { useMemo, useState } from 'react';
import {
  Button, DatePicker, Form, Input, Modal, Popconfirm, Select, Space, Table, Tag,
  Typography, message,
} from 'antd';
import { AudioOutlined, DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import dayjs, { type Dayjs } from 'dayjs';
import {
  ApiError, organizations, roles, users, voiceAdmin,
  type VoiceGrantInput, type VoiceProfile,
} from '../../api/client';
import OrgSelect from '../../components/OrgSelect';
import { FinderShell, TitleBar } from '../../components/finder/primitives';
import { useOrgTree } from '../../hooks/useOrgTree';

type VoiceKind = 'builtin' | 'designed' | 'cloned';

interface VoiceFormValues {
  name: string;
  voice_type: VoiceKind;
  provider_voice_id?: string;
  design_prompt?: string;
  sample_file_id?: string;
  evidence_file_id?: string;
  rights_holder?: string;
  purpose?: string;
  valid_until?: Dayjs;
  confirmed?: boolean;
  status?: 'active' | 'disabled';
  grants?: VoiceGrantInput[];
}

const TYPE_LABELS: Record<VoiceKind, string> = {
  builtin: '内置音色', designed: '设计音色', cloned: '克隆音色',
};

export default function VoicesPage() {
  const qc = useQueryClient();
  const [form] = Form.useForm<VoiceFormValues>();
  const [selectedOrgId, setSelectedOrgId] = useState<string>();
  const [editing, setEditing] = useState<VoiceProfile | null>(null);
  const [open, setOpen] = useState(false);
  const kind = Form.useWatch('voice_type', form);
  const grants = Form.useWatch('grants', form) ?? [];
  const { data: orgs = [] } = useQuery({ queryKey: ['orgs'], queryFn: organizations.list });
  const orgId = selectedOrgId ?? orgs.find(org => org.is_default)?.id ?? orgs[0]?.id;
  const { data: voices = [], isLoading } = useQuery({
    queryKey: ['voice-admin', orgId],
    queryFn: () => orgId ? voiceAdmin.list(orgId) : Promise.resolve([]),
    enabled: !!orgId,
  });
  const { data: roleList = [] } = useQuery({
    queryKey: ['roles', orgId], queryFn: () => orgId ? roles.list(orgId) : Promise.resolve([]), enabled: !!orgId,
  });
  const { data: userList = [] } = useQuery({
    queryKey: ['users', orgId], queryFn: () => orgId ? users.list(orgId) : Promise.resolve([]), enabled: !!orgId,
  });
  const { nodeMap } = useOrgTree();
  const departments = useMemo(() => Array.from(nodeMap.values())
    .filter(node => node.type === 'department' && node.orgId === orgId)
    .map(node => ({ value: node.id, label: node.name })), [nodeMap, orgId]);

  const targetOptions = (scopeType: VoiceGrantInput['scope_type']) => {
    if (scopeType === 'role') return roleList.map(role => ({ value: role.id, label: role.name }));
    if (scopeType === 'department') return departments;
    if (scopeType === 'user') return userList.map(user => ({ value: user.id, label: user.display_name || user.username }));
    return [];
  };

  const close = () => { setOpen(false); setEditing(null); form.resetFields(); };
  const save = useMutation({
    mutationFn: async (values: VoiceFormValues) => {
      if (!orgId) throw new Error('请先选择企业');
      const sourceGrants: VoiceGrantInput[] = values.grants?.length
        ? values.grants
        : [{ scope_type: 'organization', scope_id: null }];
      const normalizedGrants = sourceGrants
        .map(grant => ({
          scope_type: grant.scope_type,
          scope_id: grant.scope_type === 'organization' ? null : grant.scope_id,
        })) as VoiceGrantInput[];
      if (editing) {
        return voiceAdmin.update(editing.id, {
          name: values.name, status: values.status, grants: normalizedGrants,
        });
      }
      if (values.voice_type === 'builtin') {
        return voiceAdmin.createBuiltin(orgId, {
          name: values.name, provider_voice_id: values.provider_voice_id!, grants: normalizedGrants,
        });
      }
      if (values.voice_type === 'designed') {
        return voiceAdmin.createDesign(orgId, {
          name: values.name, design_prompt: values.design_prompt!, grants: normalizedGrants,
        });
      }
      return voiceAdmin.createClone(orgId, {
        name: values.name,
        sample_file_id: values.sample_file_id!,
        evidence_file_id: values.evidence_file_id!,
        rights_holder: values.rights_holder!,
        purpose: values.purpose!,
        valid_until: values.valid_until!.toISOString(),
        confirmed: values.confirmed === true,
        grants: normalizedGrants,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['voice-admin', orgId] });
      close();
      message.success('企业音色已保存');
    },
    onError: error => message.error(error instanceof ApiError ? error.message : '企业音色保存失败'),
  });
  const remove = useMutation({
    mutationFn: (id: string) => voiceAdmin.delete(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['voice-admin', orgId] });
      message.success('音色已撤销并进入异步清理');
    },
    onError: error => message.error(error instanceof ApiError ? error.message : '删除失败'),
  });

  const create = (voiceType: VoiceKind) => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({
      voice_type: voiceType,
      status: 'active',
      confirmed: false,
      grants: [{ scope_type: 'organization', scope_id: null }],
    });
    setOpen(true);
  };
  const edit = (voice: VoiceProfile) => {
    setEditing(voice);
    form.setFieldsValue({
      name: voice.name,
      voice_type: voice.voice_type,
      status: voice.status === 'disabled' ? 'disabled' : 'active',
      grants: voice.grants.map(grant => ({
        scope_type: grant.scope_type as VoiceGrantInput['scope_type'], scope_id: grant.scope_id,
      })),
    });
    setOpen(true);
  };

  return <FinderShell>
    <TitleBar
      icon={<AudioOutlined />}
      title="企业音色库"
      titleExtra={<OrgSelect value={orgId} onChange={setSelectedOrgId} />}
      extra={<Space>
        <Button icon={<PlusOutlined />} disabled={!orgId} onClick={() => create('builtin')}>内置音色</Button>
        <Button icon={<PlusOutlined />} disabled={!orgId} onClick={() => create('designed')}>设计音色</Button>
        <Button type="primary" icon={<PlusOutlined />} disabled={!orgId} onClick={() => create('cloned')}>克隆音色</Button>
      </Space>}
    />
    <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
      <Typography.Paragraph type="secondary">
        音色按角色、部门或用户授权。克隆音色必须提供 OSS 中的样本和授权证明，并明确二次确认。
      </Typography.Paragraph>
      <Table rowKey="id" loading={isLoading} dataSource={voices} columns={[
        { title: '名称', dataIndex: 'name' },
        { title: '类型', dataIndex: 'voice_type', render: (value: VoiceKind) => <Tag>{TYPE_LABELS[value]}</Tag> },
        { title: '授权范围', render: (_: unknown, voice: VoiceProfile) => (
          <Space wrap>{voice.grants.map(grant => <Tag key={grant.id}>{grant.scope_type}</Tag>)}</Space>
        ) },
        { title: '状态', dataIndex: 'status', render: (value: string) => (
          <Tag color={value === 'active' ? 'green' : 'default'}>{value === 'active' ? '启用' : '停用'}</Tag>
        ) },
        { title: '操作', render: (_: unknown, voice: VoiceProfile) => <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => edit(voice)}>编辑</Button>
          <Popconfirm title="撤销授权并清理音色文件？" onConfirm={() => remove.mutate(voice.id)}>
            <Button size="small" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </Space> },
      ]} />
    </div>
    <Modal
      open={open}
      width={760}
      title={editing ? `编辑音色：${editing.name}` : `创建${TYPE_LABELS[kind ?? 'builtin']}`}
      onCancel={close}
      onOk={() => form.submit()}
      confirmLoading={save.isPending}
      forceRender
    >
      <Form form={form} layout="vertical" onFinish={values => save.mutate(values)}>
        <Form.Item name="voice_type" hidden><Input /></Form.Item>
        <Form.Item name="name" label="音色名称" rules={[{ required: true }]}><Input /></Form.Item>
        {!editing && kind === 'builtin' && <Form.Item
          name="provider_voice_id" label="供应商 Voice ID" rules={[{ required: true }]}
        ><Input /></Form.Item>}
        {!editing && kind === 'designed' && <Form.Item
          name="design_prompt" label="音色描述" rules={[{ required: true, min: 5 }]}
        ><Input.TextArea rows={3} /></Form.Item>}
        {!editing && kind === 'cloned' && <>
          <Form.Item name="sample_file_id" label="克隆样本文件 ID" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="evidence_file_id" label="授权证明文件 ID" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="rights_holder" label="权利人" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="purpose" label="用途说明" rules={[{ required: true }]}><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="valid_until" label="授权有效期" rules={[{ required: true }]}>
            <DatePicker showTime disabledDate={date => date.isBefore(dayjs(), 'day')} />
          </Form.Item>
          <Form.Item
            name="confirmed"
            label="二次确认"
            rules={[{ validator: (_, value) => value === true ? Promise.resolve() : Promise.reject(new Error('必须确认已获得合法授权')) }]}
          >
            <Select options={[
              { value: false, label: '尚未确认' }, { value: true, label: '已核验授权并确认创建' },
            ]} />
          </Form.Item>
        </>}
        {editing && <Form.Item name="status" label="状态"><Select options={[
          { value: 'active', label: '启用' }, { value: 'disabled', label: '停用' },
        ]} /></Form.Item>}
        <Form.List name="grants">
          {(fields, { add, remove: removeGrant }) => <>
            <Space style={{ marginBottom: 8 }}>
              <Typography.Text strong>使用范围</Typography.Text>
              <Button size="small" onClick={() => add({ scope_type: 'role' })}>增加授权</Button>
            </Space>
            {fields.map((field, index) => {
              const scopeType = grants[index]?.scope_type ?? 'role';
              return <Space key={field.key} align="start" style={{ display: 'flex', marginBottom: 8 }}>
                <Form.Item {...field} name={[field.name, 'scope_type']} rules={[{ required: true }]}>
                  <Select style={{ width: 130 }} options={[
                    { value: 'organization', label: '全企业' },
                    { value: 'role', label: '角色' },
                    { value: 'department', label: '部门' },
                    { value: 'user', label: '指定用户' },
                  ]} onChange={() => form.setFieldValue(['grants', index, 'scope_id'], null)} />
                </Form.Item>
                {scopeType !== 'organization' && <Form.Item
                  {...field}
                  name={[field.name, 'scope_id']}
                  rules={[{ required: true, message: '请选择授权对象' }]}
                ><Select showSearch style={{ width: 280 }} options={targetOptions(scopeType)} /></Form.Item>}
                <Button danger onClick={() => removeGrant(field.name)}>移除</Button>
              </Space>;
            })}
          </>}
        </Form.List>
      </Form>
    </Modal>
  </FinderShell>;
}
