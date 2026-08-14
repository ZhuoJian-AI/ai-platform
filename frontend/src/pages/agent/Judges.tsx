import { useState, useEffect } from 'react';
import {
  Modal, Table, Tag, Form, Input, Switch, message,
} from 'antd';
import { PlusOutlined, DeleteOutlined, EditOutlined, SafetyOutlined } from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { judges } from '../../api/client';
import type { JudgeTemplate } from '../../api/client';
import { ApiError } from '../../api/client';
import BoundNodeSlugSelect from '../../components/BoundNodeSlugSelect';
import OrgSelect from '../../components/OrgSelect';
import JsonEditor from '../../components/JsonEditor';
import {
  FinderShell, TitleBar, ToolButton,
} from '../../components/finder/primitives';
import ConfirmModal from '../../components/finder/ConfirmModal';

const { TextArea } = Input;

/** Judge 模板：Finder 外壳 + 表格 CRUD。可复用的 LLM-as-judge 评分维度与权重。 */
export default function Judges() {
  const qc = useQueryClient();
  const [orgId, setOrgId] = useState<string | undefined>();
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<JudgeTemplate | null>(null);
  const [form] = Form.useForm();
  const [confirmId, setConfirmId] = useState<string | null>(null);

  const { data: list, isLoading } = useQuery({
    queryKey: ['judges', orgId],
    queryFn: () => orgId ? judges.list(orgId) : Promise.resolve([]),
    enabled: !!orgId,
  });

  const isEdit = !!editing;
  const openCreate = () => { setEditing(null); form.resetFields(); setModalOpen(true); };
  const openEdit = (r: JudgeTemplate) => { setEditing(r); setModalOpen(true); };
  useEffect(() => { if (modalOpen && editing) form.setFieldsValue({ ...editing, criteria: editing.criteria }); }, [modalOpen, editing, form]);

  const save = useMutation({
    mutationFn: (v: Record<string, unknown>) => {
      if (!orgId) return Promise.reject(new Error('no org'));
      return isEdit && editing ? judges.update(editing.id, v) : judges.create(orgId, v);
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['judges'] }); setModalOpen(false); message.success('已保存'); },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '保存失败'),
  });
  const del = useMutation({
    mutationFn: (id: string) => judges.delete(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['judges'] }); message.success('已删除'); },
    onError: () => message.error('删除失败'),
  });

  return (
    <FinderShell style={{ height: 'calc(100vh - 64px)' }}>
      <TitleBar
        icon={<SafetyOutlined />}
        title="Judge 模板"
        titleExtra={<OrgSelect value={orgId} onChange={setOrgId} />}
        extra={<ToolButton primary icon={<PlusOutlined style={{ fontSize: 13 }} />} onClick={openCreate} disabled={!orgId}>新建模板</ToolButton>}
      />

      <div style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: '12px 16px' }}>
        <Table
          dataSource={list ?? []} rowKey="id" loading={isLoading} pagination={{ pageSize: 20 }}
          columns={[
            { title: '名称', dataIndex: 'name', width: 200 },
            { title: 'Slug', dataIndex: 'slug', width: 180 },
            { title: '维度数', dataIndex: 'criteria', width: 90, render: (v: unknown[]) => Array.isArray(v) ? v.length : 0 },
            { title: '启用', dataIndex: 'is_active', width: 70, render: (v: boolean) => <Tag color={v ? 'green' : 'red'}>{v ? '是' : '否'}</Tag> },
            { title: '操作', width: 160, fixed: 'right', render: (_: unknown, r: JudgeTemplate) => (
              <span style={{ display: 'flex', gap: 4 }}>
                <ToolButton icon={<EditOutlined style={{ fontSize: 12 }} />} onClick={() => openEdit(r)}>编辑</ToolButton>
                <ToolButton danger icon={<DeleteOutlined style={{ fontSize: 12 }} />} onClick={() => setConfirmId(r.id)}>删除</ToolButton>
              </span>
            )},
          ]}
        />
      </div>

      <Modal title={isEdit ? '编辑判官模板' : '新建判官模板'} open={modalOpen}
        onCancel={() => setModalOpen(false)} onOk={() => form.submit()} confirmLoading={save.isPending} width={640}
        destroyOnClose>
        <Form form={form} layout="vertical" onFinish={(v) => save.mutate(v)} initialValues={{ is_active: true, criteria: [] }}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="slug" label="Slug（绑定节点）" rules={[{ required: true, message: '请选择绑定节点' }]}>
            {isEdit ? <Input disabled /> : <BoundNodeSlugSelect orgId={orgId} />}
          </Form.Item>
          <Form.Item name="description" label="描述"><Input /></Form.Item>
          <Form.Item name="criteria" label="评分维度（JSON）" extra='[{"dimension":"准确性","weight":0.7,"description":"..."}]'>
            <JsonEditor value={[]} onChange={(v) => form.setFieldValue('criteria', v)} rows={5} placeholder="[]" />
          </Form.Item>
          <Form.Item name="scoring_rubric" label="评分细则"><TextArea rows={3} /></Form.Item>
          <Form.Item name="is_active" label="启用" valuePropName="checked"><Switch /></Form.Item>
        </Form>
      </Modal>

      <ConfirmModal
        open={!!confirmId}
        title="删除判官模板？"
        desc="此操作不可撤销，确定继续？"
        loading={del.isPending}
        onCancel={() => setConfirmId(null)}
        onOk={() => {
          if (confirmId) del.mutate(confirmId);
          setConfirmId(null);
        }}
      />
    </FinderShell>
  );
}
