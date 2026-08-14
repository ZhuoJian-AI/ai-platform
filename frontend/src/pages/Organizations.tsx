import { useState, type CSSProperties, type ReactNode } from 'react';
import {
  Button, Col, Modal, Row, Form, Input, InputNumber, message, Tag,
} from 'antd';
import {
  PlusOutlined, DeleteOutlined, EditOutlined, ApartmentOutlined, StarOutlined,
  TeamOutlined,
} from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { organizations, departments, teams } from '../api/client';
import type { Organization, Department, Team } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { FinderShell, TitleBar, FinderEmpty, FinderLoading, IconActionButton } from '../components/finder/primitives';
import ConfirmModal from '../components/finder/ConfirmModal';
import { WB, FS } from '../components/finder/theme';

/* ── 三栏列表样式（与 Finder primitives 同设计令牌） ─────────────────── */
const colSectionStyle: CSSProperties = {
  flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0,
  borderRight: `1px solid ${WB.border}`,
};
const colHeaderStyle: CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px',
  borderBottom: `1px solid ${WB.border}`, background: WB.titleBarBg, flex: '0 0 auto',
};
const colRowStyle = (active: boolean): CSSProperties => ({
  display: 'flex', alignItems: 'center', gap: 8, padding: '6px 10px', margin: '1px 6px',
  borderRadius: 6, cursor: 'pointer', fontSize: FS.body, lineHeight: 1.2, userSelect: 'none',
  background: active ? `${WB.primary}1A` : 'transparent',
});

/** 栏头：图标 + 标题 + 计数 + 右侧操作 */
function ColumnHeader({ icon, title, count, extra }: {
  icon: ReactNode; title: string; count?: number; extra?: ReactNode;
}) {
  return (
    <div style={colHeaderStyle}>
      <span style={{ color: WB.primary, display: 'inline-flex' }}>{icon}</span>
      <span style={{ fontWeight: 600, color: WB.text }}>{title}</span>
      {count !== undefined && <span style={{ fontSize: FS.micro, color: WB.textAux }}>{count}</span>}
      {extra !== undefined && <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>{extra}</div>}
    </div>
  );
}

export default function Organizations() {
  const qc = useQueryClient();
  const { isOrgScoped } = useAuth();
  const [selectedOrg, setSelectedOrg] = useState<Organization | null>(null);
  const [selectedDept, setSelectedDept] = useState<Department | null>(null);
  const [selectedTeam, setSelectedTeam] = useState<Team | null>(null);

  // 统一错误提示 —— 避免 mutation 失败时静默无反馈（“点了确定没反应”）
  const onMutationError = (e: unknown) => {
    const msg = (e as { message?: string })?.message || '操作失败，请重试';
    message.error(msg);
  };

  // 组织列表
  const { data: orgList, isLoading } = useQuery({
    queryKey: ['orgs'],
    queryFn: organizations.list,
  });

  // 部门列表
  const { data: deptList } = useQuery({
    queryKey: ['depts', selectedOrg?.id],
    queryFn: () => departments.list(selectedOrg!.id),
    enabled: !!selectedOrg,
  });

  // 团队列表
  const { data: teamList } = useQuery({
    queryKey: ['teams', selectedDept?.id],
    queryFn: () => teams.list(selectedDept!.id),
    enabled: !!selectedDept,
  });

  // ── 创建组织 ──
  const [orgModalOpen, setOrgModalOpen] = useState(false);
  const [orgForm] = Form.useForm();

  const createOrg = useMutation({
    mutationFn: (data: Partial<Organization>) => organizations.create(data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['orgs'] }); setOrgModalOpen(false); orgForm.resetFields(); message.success('组织创建成功'); },
    onError: onMutationError,
  });

  // ── 创建部门 ──
  const [deptModalOpen, setDeptModalOpen] = useState(false);
  const [deptForm] = Form.useForm();

  const createDept = useMutation({
    mutationFn: (data: Partial<Department>) => departments.create(selectedOrg!.id, data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['depts'] }); setDeptModalOpen(false); deptForm.resetFields(); message.success('部门创建成功'); },
    onError: onMutationError,
  });

  // ── 创建团队 ──
  const [teamModalOpen, setTeamModalOpen] = useState(false);
  const [teamForm] = Form.useForm();

  const createTeam = useMutation({
    mutationFn: (data: Partial<Team>) => teams.create(selectedDept!.id, data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['teams'] }); setTeamModalOpen(false); teamForm.resetFields(); message.success('团队创建成功'); },
    onError: onMutationError,
  });

  // ── 删除 ──
  const deleteOrg = useMutation({
    mutationFn: (id: string) => organizations.delete(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['orgs'] }); setSelectedOrg(null); message.success('组织已删除'); },
    onError: onMutationError,
  });

  const deleteDept = useMutation({
    mutationFn: (id: string) => departments.delete(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['depts'] }); setSelectedDept(null); message.success('部门已删除'); },
    onError: onMutationError,
  });

  const deleteTeam = useMutation({
    mutationFn: (id: string) => teams.delete(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['teams'] }); message.success('团队已删除'); },
    onError: onMutationError,
  });

  // ── 编辑 ──
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [editForm] = Form.useForm();
  const [editTarget, setEditTarget] = useState<{ kind: 'org' | 'dept' | 'team'; id: string } | null>(null);
  // 缓存当前编辑的整条记录，供 Form initialValues 取值。
  // 通过 key=editTarget.id 强制 Form 按记录重挂载，避免 setFieldsValue 时序丢失字段。
  const [editRecord, setEditRecord] = useState<Partial<Organization & Department & Team> | null>(null);
  const [confirm, setConfirm] = useState<{ kind: 'org' | 'dept' | 'team'; id: string; name: string } | null>(null);

  const openEdit = (kind: 'org' | 'dept' | 'team', record: Organization | Department | Team) => {
    setEditTarget({ kind, id: record.id });
    setEditRecord(record);
    setEditModalOpen(true);
  };

  const updateOrg = useMutation({
    mutationFn: (data: Partial<Organization>) => organizations.update(selectedOrg!.id, data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['orgs'] }); setEditModalOpen(false); message.success('组织已更新'); },
    onError: onMutationError,
  });

  // ── 设为默认组织 ──
  const setDefaultOrg = useMutation({
    mutationFn: (id: string) => organizations.setDefault(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['orgs'] }); message.success('已设为默认组织'); },
    onError: onMutationError,
  });

  const updateDept = useMutation({
    mutationFn: (data: Partial<Department>) => departments.update(editTarget!.id, data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['depts'] }); setEditModalOpen(false); message.success('部门已更新'); },
    onError: onMutationError,
  });

  const updateTeam = useMutation({
    mutationFn: (data: Partial<Team>) => teams.update(editTarget!.id, data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['teams'] }); setEditModalOpen(false); message.success('团队已更新'); },
    onError: onMutationError,
  });

  const submitEdit = (values: Partial<Organization & Department & Team>) => {
    if (!editTarget) return;
    // 空值转为 null，避免把 undefined 当作“未传”而无法清空字段
    const payload = {
      name: values.name,
      slug: values.slug,
      description: values.description ?? null,
      rate_limit_rpm: values.rate_limit_rpm ?? null,
      rate_limit_tpm: values.rate_limit_tpm ?? null,
      budget_cap_tokens: values.budget_cap_tokens ?? null,
    };
    if (editTarget.kind === 'org') updateOrg.mutate(payload);
    else if (editTarget.kind === 'dept') updateDept.mutate(payload);
    else updateTeam.mutate(payload);
  };

  // ── 三栏列表数据：组织 → 部门 → 团队 ──
  // 部门列表已按 selectedOrg 查询；团队列表已按 selectedDept 查询，无需再 filter
  // 注意：局部变量勿命名为 teams/departments，会遮蔽从 api/client 导入的同名客户端
  const deptItems = deptList ?? [];
  const teamItems = teamList ?? [];

  return (
    <FinderShell>
      <TitleBar
        icon={<ApartmentOutlined />}
        title="组织架构"
        extra={isOrgScoped() ? undefined : <Button type="primary" icon={<PlusOutlined />} onClick={() => setOrgModalOpen(true)}>创建组织</Button>}
      />

      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {/* ── 左栏：组织 ── */}
        <section style={colSectionStyle}>
          <ColumnHeader icon={<ApartmentOutlined />} title="组织" count={orgList?.length ?? 0} />
          <div style={{ flex: 1, overflow: 'auto' }} className="wb-scroll-hide">
            {isLoading ? <FinderLoading /> :
              (orgList ?? []).length === 0 ? <FinderEmpty description="暂无组织" /> :
              (orgList ?? []).map(org => {
                const active = selectedOrg?.id === org.id;
                return (
                  <div
                    key={org.id}
                    className={`org-row${active ? ' active' : ''}`}
                    onClick={() => { setSelectedOrg(org); setSelectedDept(null); setSelectedTeam(null); }}
                    style={colRowStyle(active)}
                    onMouseEnter={(e) => { if (!active) e.currentTarget.style.background = WB.hover; }}
                    onMouseLeave={(e) => { if (!active) e.currentTarget.style.background = 'transparent'; }}
                  >
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <span style={{ fontWeight: active ? 600 : 400, color: active ? WB.primary : WB.text, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{org.name}</span>
                        {org.is_default && <Tag color="gold" style={{ marginInlineEnd: 0 }}>默认</Tag>}
                      </div>
                      <div style={{ fontSize: FS.micro, color: WB.textAux, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{org.slug}</div>
                    </div>
                    <div className="row-actions" style={{ display: 'flex', gap: 2, flex: '0 0 auto' }}>
                      {!isOrgScoped() && !org.is_default && (
                        <IconActionButton icon={<StarOutlined />} title="设为默认" onClick={(e) => { e.stopPropagation(); setDefaultOrg.mutate(org.id); }} />
                      )}
                      <IconActionButton icon={<EditOutlined />} title="编辑" onClick={(e) => { e.stopPropagation(); openEdit('org', org); }} />
                      {!isOrgScoped() && (
                        <IconActionButton variant="danger" icon={<DeleteOutlined />} title="删除" onClick={(e) => { e.stopPropagation(); setConfirm({ kind: 'org', id: org.id, name: org.name }); }} />
                      )}
                    </div>
                  </div>
                );
              })}
          </div>
        </section>

        {/* ── 中栏：部门 ── */}
        <section style={colSectionStyle}>
          <ColumnHeader
            icon={<ApartmentOutlined />} title="部门" count={selectedOrg ? deptItems.length : undefined}
            extra={<Button size="small" icon={<PlusOutlined />} disabled={!selectedOrg} onClick={() => setDeptModalOpen(true)}>添加部门</Button>}
          />
          <div style={{ flex: 1, overflow: 'auto' }} className="wb-scroll-hide">
            {!selectedOrg ? <FinderEmpty description="← 请先选择组织" /> :
              deptItems.length === 0 ? <FinderEmpty description="暂无部门" /> :
              deptItems.map(dept => {
                const active = selectedDept?.id === dept.id;
                return (
                  <div
                    key={dept.id}
                    className={`org-row${active ? ' active' : ''}`}
                    onClick={() => { setSelectedDept(dept); setSelectedTeam(null); }}
                    style={colRowStyle(active)}
                    onMouseEnter={(e) => { if (!active) e.currentTarget.style.background = WB.hover; }}
                    onMouseLeave={(e) => { if (!active) e.currentTarget.style.background = 'transparent'; }}
                  >
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontWeight: active ? 600 : 400, color: active ? WB.primary : WB.text, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{dept.name}</div>
                      <div style={{ fontSize: FS.micro, color: WB.textAux, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{dept.slug}</div>
                    </div>
                    <div className="row-actions" style={{ display: 'flex', gap: 2, flex: '0 0 auto' }}>
                      <IconActionButton icon={<EditOutlined />} title="编辑" onClick={(e) => { e.stopPropagation(); openEdit('dept', dept); }} />
                      <IconActionButton variant="danger" icon={<DeleteOutlined />} title="删除" onClick={(e) => { e.stopPropagation(); setConfirm({ kind: 'dept', id: dept.id, name: dept.name }); }} />
                    </div>
                  </div>
                );
              })}
          </div>
        </section>

        {/* ── 右栏：团队 ── */}
        <section style={{ ...colSectionStyle, borderRight: 'none' }}>
          <ColumnHeader
            icon={<TeamOutlined />} title="团队" count={selectedDept ? teamItems.length : undefined}
            extra={<Button size="small" icon={<PlusOutlined />} disabled={!selectedDept} onClick={() => setTeamModalOpen(true)}>添加团队</Button>}
          />
          <div style={{ flex: 1, overflow: 'auto' }} className="wb-scroll-hide">
            {!selectedDept ? <FinderEmpty description="← 请先选择部门" /> :
              teamItems.length === 0 ? <FinderEmpty description="暂无团队" /> :
              teamItems.map(team => {
                const active = selectedTeam?.id === team.id;
                return (
                  <div
                    key={team.id}
                    className={`org-row${active ? ' active' : ''}`}
                    onClick={() => setSelectedTeam(team)}
                    style={colRowStyle(active)}
                    onMouseEnter={(e) => { if (!active) e.currentTarget.style.background = WB.hover; }}
                    onMouseLeave={(e) => { if (!active) e.currentTarget.style.background = 'transparent'; }}
                  >
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontWeight: active ? 600 : 400, color: active ? WB.primary : WB.text, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{team.name}</div>
                      <div style={{ fontSize: FS.micro, color: WB.textAux, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{team.slug}</div>
                    </div>
                    <div className="row-actions" style={{ display: 'flex', gap: 2, flex: '0 0 auto' }}>
                      <IconActionButton icon={<EditOutlined />} title="编辑" onClick={(e) => { e.stopPropagation(); openEdit('team', team); }} />
                      <IconActionButton variant="danger" icon={<DeleteOutlined />} title="删除" onClick={(e) => { e.stopPropagation(); setConfirm({ kind: 'team', id: team.id, name: team.name }); }} />
                    </div>
                  </div>
                );
              })}
          </div>
        </section>
      </div>

      {/* 创建组织 Modal */}
      <Modal title="创建组织" open={orgModalOpen} onCancel={() => setOrgModalOpen(false)} onOk={() => orgForm.submit()} confirmLoading={createOrg.isPending}>
        <Form form={orgForm} layout="vertical" onFinish={v => createOrg.mutate(v)}>
          <Form.Item name="name" label="组织名称" rules={[{ required: true }]}>
            <Input placeholder="如：智谱科技" />
          </Form.Item>
          <Form.Item name="slug" label="Slug" rules={[{ required: true, pattern: /^[a-z0-9-]+$/ }]}>
            <Input placeholder="如：zhipu-tech" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Row gutter={16}>
            <Col span={8}><Form.Item name="rate_limit_rpm" label="RPM 上限"><InputNumber min={1} style={{ width: '100%' }} placeholder="不限" /></Form.Item></Col>
            <Col span={8}><Form.Item name="rate_limit_tpm" label="TPM 上限"><InputNumber min={1} style={{ width: '100%' }} placeholder="不限" /></Form.Item></Col>
            <Col span={8}><Form.Item name="budget_cap_tokens" label="预算(token)"><InputNumber min={0} style={{ width: '100%' }} placeholder="不限" /></Form.Item></Col>
          </Row>
        </Form>
      </Modal>

      {/* 创建部门 Modal */}
      <Modal title="创建部门" open={deptModalOpen} onCancel={() => setDeptModalOpen(false)} onOk={() => deptForm.submit()} confirmLoading={createDept.isPending}>
        <Form form={deptForm} layout="vertical" onFinish={v => createDept.mutate(v)}>
          <Form.Item name="name" label="部门名称" rules={[{ required: true }]}>
            <Input placeholder="如：研发部" />
          </Form.Item>
          <Form.Item name="slug" label="Slug" rules={[{ required: true, pattern: /^[a-z0-9-]+$/ }]}>
            <Input placeholder="如：rd" />
          </Form.Item>
          <Form.Item name="description" label="描述"><Input.TextArea rows={2} /></Form.Item>
        </Form>
      </Modal>

      {/* 创建团队 Modal */}
      <Modal title="创建团队" open={teamModalOpen} onCancel={() => setTeamModalOpen(false)} onOk={() => teamForm.submit()} confirmLoading={createTeam.isPending}>
        <Form form={teamForm} layout="vertical" onFinish={v => createTeam.mutate(v)}>
          <Form.Item name="name" label="团队名称" rules={[{ required: true }]}>
            <Input placeholder="如：AI平台组" />
          </Form.Item>
          <Form.Item name="slug" label="Slug" rules={[{ required: true, pattern: /^[a-z0-9-]+$/ }]}>
            <Input placeholder="如：ai-platform" />
          </Form.Item>
          <Form.Item name="description" label="描述"><Input.TextArea rows={2} /></Form.Item>
        </Form>
      </Modal>

      {/* 编辑 Modal（组织/部门/团队共用） */}
      <Modal
        title={`编辑${editTarget?.kind === 'org' ? '组织' : editTarget?.kind === 'dept' ? '部门' : '团队'}`}
        open={editModalOpen}
        onCancel={() => setEditModalOpen(false)}
        onOk={async () => {
          // 显式校验：失败时 toast 提示具体字段，避免 AntD 默默红框让用户以为"点了没反应"。
          try {
            await editForm.validateFields();
            editForm.submit();
          } catch (e) {
            const errs = (e as { errorFields?: { name?: string[]; errors?: string[] }[] })?.errorFields ?? [];
            const msg = errs.map(f => `${f.name?.join('.') ?? ''}: ${f.errors?.join('；') ?? ''}`).join(' | ') || '请检查表单字段';
            message.error(msg);
          }
        }}
        destroyOnClose
        confirmLoading={updateOrg.isPending || updateDept.isPending || updateTeam.isPending}
      >
        <Form
          // key 与当前编辑记录 id 绑定，记录变化时强制 Form 重挂载，
          // 配合 initialValues 干净初始化字段，避免上一次编辑遗留的值/校验状态污染本次提交。
          key={editTarget?.id ?? 'empty'}
          form={editForm}
          layout="vertical"
          onFinish={submitEdit}
          initialValues={{
            name: editRecord?.name,
            slug: editRecord?.slug,
            description: editRecord?.description ?? undefined,
            rate_limit_rpm: editRecord?.rate_limit_rpm ?? undefined,
            rate_limit_tpm: editRecord?.rate_limit_tpm ?? undefined,
            budget_cap_tokens: editRecord?.budget_cap_tokens ?? undefined,
          }}
        >
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="slug" label="Slug" rules={[{ required: true, pattern: /^[a-z0-9-]+$/ }]}>
            <Input placeholder="如：zhipu-tech" />
          </Form.Item>
          <Form.Item name="description" label="描述"><Input.TextArea rows={2} /></Form.Item>
          <Row gutter={16}>
            <Col span={8}><Form.Item name="rate_limit_rpm" label="RPM 上限"><InputNumber min={1} style={{ width: '100%' }} placeholder="不限" /></Form.Item></Col>
            <Col span={8}><Form.Item name="rate_limit_tpm" label="TPM 上限"><InputNumber min={1} style={{ width: '100%' }} placeholder="不限" /></Form.Item></Col>
            <Col span={8}><Form.Item name="budget_cap_tokens" label="预算(token)"><InputNumber min={0} style={{ width: '100%' }} placeholder="不限" /></Form.Item></Col>
          </Row>
        </Form>
      </Modal>

      <ConfirmModal
        open={!!confirm}
        title={<>确定删除{confirm?.kind === 'org' ? '组织' : confirm?.kind === 'dept' ? '部门' : '团队'}「{confirm?.name}」？</>}
        okText="删除"
        loading={deleteOrg.isPending || deleteDept.isPending || deleteTeam.isPending}
        onCancel={() => setConfirm(null)}
        onOk={() => {
          if (!confirm) return;
          if (confirm.kind === 'org') deleteOrg.mutate(confirm.id);
          else if (confirm.kind === 'dept') deleteDept.mutate(confirm.id);
          else deleteTeam.mutate(confirm.id);
          setConfirm(null);
        }}
      />
    </FinderShell>
  );
}
