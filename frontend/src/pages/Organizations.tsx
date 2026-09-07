import { useEffect, useState, type CSSProperties, type ReactNode } from 'react';
import {
  Alert, Button, Col, Form, Input, InputNumber, message, Modal, Row, Tag,
} from 'antd';
import {
  ApartmentOutlined, ArrowDownOutlined, ArrowUpOutlined, DeleteOutlined,
  EditOutlined, HolderOutlined, PlusOutlined, StarOutlined,
} from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { departments, organizations } from '../api/client';
import type { Department, Organization } from '../api/client';
import { useAuth } from '../context/AuthContext';
import {
  FinderEmpty, FinderLoading, FinderShell, IconActionButton, TitleBar,
} from '../components/finder/primitives';
import ConfirmModal from '../components/finder/ConfirmModal';
import { FS, WB } from '../components/finder/theme';

const columnStyle: CSSProperties = {
  flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0,
  borderRight: `1px solid ${WB.border}`,
};
const headerStyle: CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px',
  borderBottom: `1px solid ${WB.border}`, background: WB.titleBarBg,
};
const rowStyle = (active: boolean): CSSProperties => ({
  display: 'flex', alignItems: 'center', gap: 8, padding: '8px 10px', margin: '1px 6px',
  borderRadius: 6, cursor: 'pointer', fontSize: FS.body,
  background: active ? `${WB.primary}1A` : 'transparent',
});

function ColumnHeader({ icon, title, count, extra }: {
  icon: ReactNode; title: string; count?: number; extra?: ReactNode;
}) {
  return <div style={headerStyle}>
    <span style={{ color: WB.primary }}>{icon}</span>
    <strong>{title}</strong>
    {count !== undefined && <span style={{ color: WB.textAux, fontSize: FS.micro }}>{count}</span>}
    {extra && <span style={{ marginLeft: 'auto' }}>{extra}</span>}
  </div>;
}

type Editable = Partial<Organization & Department>;
type EditTarget = { kind: 'organization' | 'department'; id: string };

function LimitFields({ disabled = false, inherited = false }: { disabled?: boolean; inherited?: boolean }) {
  const placeholder = inherited ? '继承企业' : '不限';
  return <Row gutter={16}>
    <Col span={12}><Form.Item name="rate_limit_rpm" label="RPM 上限"><InputNumber min={1} disabled={disabled} style={{ width: '100%' }} placeholder={placeholder} /></Form.Item></Col>
    <Col span={12}><Form.Item name="rate_limit_tpm" label="TPM 上限"><InputNumber min={1} disabled={disabled} style={{ width: '100%' }} placeholder={placeholder} /></Form.Item></Col>
    <Col span={12}><Form.Item name="budget_cap_tokens" label="每月 Token 上限"><InputNumber min={0} disabled={disabled} style={{ width: '100%' }} placeholder={placeholder} /></Form.Item></Col>
    <Col span={12}><Form.Item name="budget_cap_credits" label="每月调用额度"><InputNumber min={0} precision={0} disabled={disabled} style={{ width: '100%' }} placeholder={placeholder} /></Form.Item></Col>
  </Row>;
}

export default function Organizations() {
  const qc = useQueryClient();
  const { isOrgScoped } = useAuth();
  const [selectedOrg, setSelectedOrg] = useState<Organization | null>(null);
  const [selectedDept, setSelectedDept] = useState<Department | null>(null);
  const [orgModalOpen, setOrgModalOpen] = useState(false);
  const [deptModalOpen, setDeptModalOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<EditTarget | null>(null);
  const [editRecord, setEditRecord] = useState<Editable | null>(null);
  const [confirm, setConfirm] = useState<{ kind: EditTarget['kind']; id: string; name: string } | null>(null);
  const [draggedDepartmentId, setDraggedDepartmentId] = useState<string | null>(null);
  const [orgForm] = Form.useForm();
  const [deptForm] = Form.useForm();
  const [editForm] = Form.useForm();

  const { data: orgList = [], isLoading } = useQuery({ queryKey: ['orgs'], queryFn: organizations.list });
  const { data: deptList = [] } = useQuery({
    queryKey: ['depts', selectedOrg?.id],
    queryFn: () => departments.list(selectedOrg!.id),
    enabled: !!selectedOrg,
  });
  useEffect(() => {
    if (!selectedOrg && orgList.length) setSelectedOrg(orgList.find(org => org.is_default) ?? orgList[0]);
  }, [orgList, selectedOrg]);

  const fail = (error: unknown) => message.error((error as { message?: string })?.message || '操作失败，请重试');
  const refreshTree = () => qc.invalidateQueries({ queryKey: ['orgTreeV2'] });
  const createOrg = useMutation({
    mutationFn: (data: Partial<Organization>) => organizations.create(data),
    onSuccess: org => { qc.invalidateQueries({ queryKey: ['orgs'] }); refreshTree(); setOrgModalOpen(false); orgForm.resetFields(); setSelectedOrg(org); message.success('企业创建成功'); },
    onError: fail,
  });
  const createDept = useMutation({
    mutationFn: (data: Partial<Department>) => departments.create(selectedOrg!.id, data),
    onSuccess: dept => { qc.invalidateQueries({ queryKey: ['depts', selectedOrg?.id] }); refreshTree(); setDeptModalOpen(false); deptForm.resetFields(); setSelectedDept(dept); message.success('部门创建成功'); },
    onError: fail,
  });
  const updateOrg = useMutation({
    mutationFn: (data: Partial<Organization>) => organizations.update(editTarget!.id, data),
    onSuccess: org => { qc.invalidateQueries({ queryKey: ['orgs'] }); refreshTree(); setSelectedOrg(org); setEditOpen(false); message.success('企业已更新'); },
    onError: fail,
  });
  const updateDept = useMutation({
    mutationFn: (data: Partial<Department>) => departments.update(editTarget!.id, data),
    onSuccess: dept => { qc.invalidateQueries({ queryKey: ['depts', selectedOrg?.id] }); refreshTree(); setSelectedDept(dept); setEditOpen(false); message.success('部门已更新'); },
    onError: fail,
  });
  const deleteOrg = useMutation({
    mutationFn: organizations.delete,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['orgs'] }); refreshTree(); setSelectedOrg(null); setSelectedDept(null); message.success('企业已删除'); },
    onError: fail,
  });
  const deleteDept = useMutation({
    mutationFn: departments.delete,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['depts', selectedOrg?.id] }); refreshTree(); setSelectedDept(null); message.success('部门已删除'); },
    onError: fail,
  });
  const setDefaultOrg = useMutation({
    mutationFn: organizations.setDefault,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['orgs'] }); message.success('已设为默认企业'); },
    onError: fail,
  });
  const reorderDept = useMutation({
    mutationFn: (ids: string[]) => departments.reorder(selectedOrg!.id, ids),
    onSuccess: rows => { qc.setQueryData(['depts', selectedOrg?.id], rows); refreshTree(); },
    onError: fail,
  });

  const openEdit = (kind: EditTarget['kind'], record: Organization | Department) => {
    setEditTarget({ kind, id: record.id }); setEditRecord(record); setEditOpen(true);
  };
  const submitEdit = (values: Editable) => {
    if (!editTarget) return;
    const profile = { name: values.name, slug: values.slug, description: values.description ?? null };
    const payload = isOrgScoped() && editTarget.kind === 'organization' ? profile : {
      ...profile,
      rate_limit_rpm: values.rate_limit_rpm ?? null,
      rate_limit_tpm: values.rate_limit_tpm ?? null,
      budget_cap_tokens: values.budget_cap_tokens ?? null,
      budget_cap_credits: values.budget_cap_credits ?? null,
    };
    if (editTarget.kind === 'organization') updateOrg.mutate(payload);
    else updateDept.mutate(payload);
  };
  const moveDepartment = (index: number, offset: -1 | 1) => {
    const target = index + offset;
    if (target < 0 || target >= deptList.length || reorderDept.isPending) return;
    const ids = deptList.map(dept => dept.id);
    [ids[index], ids[target]] = [ids[target], ids[index]];
    reorderDept.mutate(ids);
  };
  const dropBefore = (targetId: string) => {
    if (!draggedDepartmentId || draggedDepartmentId === targetId || reorderDept.isPending) return;
    const ids = deptList.map(dept => dept.id);
    const from = ids.indexOf(draggedDepartmentId);
    const to = ids.indexOf(targetId);
    if (from < 0 || to < 0) return;
    const [moved] = ids.splice(from, 1); ids.splice(to, 0, moved);
    setDraggedDepartmentId(null); reorderDept.mutate(ids);
  };

  return <FinderShell>
    <TitleBar
      icon={<ApartmentOutlined />}
      title="组织架构"
      titleExtra={<Tag color="blue">企业 → 部门 → 用户</Tag>}
      extra={isOrgScoped() ? undefined : <Button type="primary" icon={<PlusOutlined />} onClick={() => setOrgModalOpen(true)}>创建企业</Button>}
    />
    <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
      <section style={columnStyle}>
        <ColumnHeader icon={<ApartmentOutlined />} title="企业" count={orgList.length} />
        <div style={{ flex: 1, overflow: 'auto' }}>
          {isLoading ? <FinderLoading /> : orgList.length === 0 ? <FinderEmpty description="暂无企业" /> : orgList.map(org => {
            const active = selectedOrg?.id === org.id;
            return <div key={org.id} style={rowStyle(active)} onClick={() => { setSelectedOrg(org); setSelectedDept(null); }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div><strong>{org.name}</strong>{org.is_default && <Tag color="gold" style={{ marginLeft: 6 }}>默认</Tag>}</div>
                <div style={{ fontSize: FS.micro, color: WB.textAux }}>{org.slug} · 月调用额度 {org.budget_cap_credits?.toLocaleString() ?? '不限'}</div>
              </div>
              <span style={{ display: 'flex', gap: 2 }}>
                {!isOrgScoped() && !org.is_default && <IconActionButton icon={<StarOutlined />} title="设为默认" onClick={event => { event.stopPropagation(); setDefaultOrg.mutate(org.id); }} />}
                <IconActionButton icon={<EditOutlined />} title="编辑" onClick={event => { event.stopPropagation(); openEdit('organization', org); }} />
                {!isOrgScoped() && <IconActionButton variant="danger" icon={<DeleteOutlined />} title="删除" onClick={event => { event.stopPropagation(); setConfirm({ kind: 'organization', id: org.id, name: org.name }); }} />}
              </span>
            </div>;
          })}
        </div>
      </section>
      <section style={{ ...columnStyle, borderRight: 0 }}>
        <ColumnHeader
          icon={<ApartmentOutlined />}
          title="部门"
          count={selectedOrg ? deptList.length : undefined}
          extra={<Button size="small" icon={<PlusOutlined />} disabled={!selectedOrg} onClick={() => setDeptModalOpen(true)}>添加部门</Button>}
        />
        <div style={{ flex: 1, overflow: 'auto' }}>
          {!selectedOrg ? <FinderEmpty description="请先选择企业" /> : deptList.length === 0 ? <FinderEmpty description="暂无部门" /> : deptList.map((dept, index) => {
            const active = selectedDept?.id === dept.id;
            return <div
              key={dept.id} style={rowStyle(active)} draggable
              onDragStart={() => setDraggedDepartmentId(dept.id)}
              onDragOver={event => event.preventDefault()}
              onDrop={() => dropBefore(dept.id)}
              onClick={() => setSelectedDept(dept)}
            >
              <HolderOutlined style={{ color: WB.textAux }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <strong>{dept.name}</strong>
                <div style={{ fontSize: FS.micro, color: WB.textAux }}>{dept.slug} · 月调用额度 {dept.budget_cap_credits?.toLocaleString() ?? '继承企业'}</div>
              </div>
              <span style={{ display: 'flex', gap: 2 }}>
                <IconActionButton icon={<ArrowUpOutlined />} title="上移" disabled={index === 0} onClick={event => { event.stopPropagation(); moveDepartment(index, -1); }} />
                <IconActionButton icon={<ArrowDownOutlined />} title="下移" disabled={index === deptList.length - 1} onClick={event => { event.stopPropagation(); moveDepartment(index, 1); }} />
                <IconActionButton icon={<EditOutlined />} title="编辑" onClick={event => { event.stopPropagation(); openEdit('department', dept); }} />
                <IconActionButton variant="danger" icon={<DeleteOutlined />} title="删除" onClick={event => { event.stopPropagation(); setConfirm({ kind: 'department', id: dept.id, name: dept.name }); }} />
              </span>
            </div>;
          })}
        </div>
      </section>
    </div>

    <Modal title="创建企业" open={orgModalOpen} onCancel={() => setOrgModalOpen(false)} onOk={() => orgForm.submit()} confirmLoading={createOrg.isPending}>
      <Form form={orgForm} layout="vertical" onFinish={createOrg.mutate}>
        <Form.Item name="name" label="企业名称" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="slug" label="Slug" rules={[{ required: true, pattern: /^[a-z0-9-]+$/ }]}><Input placeholder="alphabet" /></Form.Item>
        <Form.Item name="description" label="描述"><Input.TextArea rows={2} /></Form.Item>
        <LimitFields />
      </Form>
    </Modal>
    <Modal title="创建部门" open={deptModalOpen} onCancel={() => setDeptModalOpen(false)} onOk={() => deptForm.submit()} confirmLoading={createDept.isPending}>
      <Form form={deptForm} layout="vertical" onFinish={createDept.mutate}>
        <Form.Item name="name" label="部门名称" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="slug" label="Slug" rules={[{ required: true, pattern: /^[a-z0-9-]+$/ }]}><Input placeholder="production" /></Form.Item>
        <Form.Item name="description" label="描述"><Input.TextArea rows={2} /></Form.Item>
        <LimitFields inherited />
      </Form>
    </Modal>
    <Modal
      title={`编辑${editTarget?.kind === 'organization' ? '企业' : '部门'}`}
      open={editOpen}
      onCancel={() => setEditOpen(false)}
      onOk={() => editForm.submit()}
      confirmLoading={updateOrg.isPending || updateDept.isPending}
      destroyOnClose
    >
      <Form key={editTarget?.id ?? 'none'} form={editForm} layout="vertical" onFinish={submitEdit} initialValues={{
        name: editRecord?.name, slug: editRecord?.slug, description: editRecord?.description ?? undefined,
        rate_limit_rpm: editRecord?.rate_limit_rpm ?? undefined,
        rate_limit_tpm: editRecord?.rate_limit_tpm ?? undefined,
        budget_cap_tokens: editRecord?.budget_cap_tokens ?? undefined,
        budget_cap_credits: editRecord?.budget_cap_credits ?? undefined,
      }}>
        <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="slug" label="Slug" rules={[{ required: true, pattern: /^[a-z0-9-]+$/ }]}><Input /></Form.Item>
        <Form.Item name="description" label="描述"><Input.TextArea rows={2} /></Form.Item>
        {isOrgScoped() && editTarget?.kind === 'organization' && <Alert showIcon type="info" message="企业顶层额度由平台超级管理员设置；企业管理员可管理部门额度。" style={{ marginBottom: 16 }} />}
        <LimitFields disabled={isOrgScoped() && editTarget?.kind === 'organization'} inherited={editTarget?.kind === 'department'} />
      </Form>
    </Modal>
    <ConfirmModal
      open={!!confirm}
      title={<>确定删除{confirm?.kind === 'organization' ? '企业' : '部门'}「{confirm?.name}」？</>}
      okText="删除"
      loading={deleteOrg.isPending || deleteDept.isPending}
      onCancel={() => setConfirm(null)}
      onOk={() => { if (!confirm) return; (confirm.kind === 'organization' ? deleteOrg : deleteDept).mutate(confirm.id); setConfirm(null); }}
    />
  </FinderShell>;
}
