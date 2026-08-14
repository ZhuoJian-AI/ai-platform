import { useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { Form, Input, Typography, message } from 'antd';
import {
  BankOutlined, ApartmentOutlined, TeamOutlined, UserOutlined, ReadOutlined,
} from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { memory } from '../../api/client';
import type { MemoryTreeNode } from '../../api/client';
import { ApiError } from '../../api/client';
import OrgSelect from '../../components/OrgSelect';
import {
  FinderShell, TitleBar, Sidebar, MacTree, Toolbar, ToolButton,
  FinderEmpty, FinderLoading, type FinderTreeNode,
} from '../../components/finder/primitives';
import { WB, FS } from '../../components/finder/theme';

const { TextArea } = Input;

const SCOPE_LABEL: Record<string, string> = {
  organization: '组织级',
  department: '部门级',
  team: '团队级',
  user: '个人级',
};

const NODE_ICON: Record<string, ReactNode> = {
  organization: <BankOutlined />,
  department: <ApartmentOutlined />,
  team: <TeamOutlined />,
  user: <UserOutlined />,
};

interface EditingMem {
  id: string;
  path: string;
  scope_type: string;
  content: string;
}

/** 长期记忆：Finder 风。随组织架构逐级嵌套的树（组织→部门→团队→用户），每个节点对应一条
 *  自动生成的长期记忆（markdown）。点击节点在右侧编辑区修订其内容。记忆随节点增删改
 *  自动生成/同步，此处不手动新建/删除。 */
export default function MemoryPage() {
  const qc = useQueryClient();
  const [orgId, setOrgId] = useState<string | undefined>();
  const [editing, setEditing] = useState<EditingMem | null>(null);
  const [form] = Form.useForm();

  const { data: tree, isLoading } = useQuery({
    queryKey: ['memoryTree', orgId],
    queryFn: () => memory.tree(orgId),
    enabled: true,
  });

  const { treeData, memByKey } = useMemo(() => {
    const memByKey = new Map<string, EditingMem>();
    const build = (nodes: MemoryTreeNode[], parentPath: string): FinderTreeNode[] =>
      nodes.map((n) => {
        const key = `${n.node_type}:${n.node_id}`;
        const path = parentPath ? `${parentPath} / ${n.name}` : n.name;
        if (n.memory) {
          memByKey.set(key, { id: n.memory.id, path, scope_type: n.memory.scope_type, content: n.memory.content ?? '' });
        }
        return {
          key,
          label: n.name,
          icon: NODE_ICON[n.node_type],
          pill: n.memory ? (SCOPE_LABEL[n.node_type] ?? n.node_type) : '无记忆',
          selectable: !!n.memory,
          children: n.children?.length ? build(n.children, path) : undefined,
        };
      });
    return { treeData: build(tree ?? [], ''), memByKey };
  }, [tree]);

  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  const saveMem = useMutation({
    mutationFn: (v: { content: string }) => memory.update(editing!.id, { content: v.content, source: 'manual' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['memoryTree'] });
      message.success('记忆已更新');
    },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '更新失败'),
  });

  return (
    <FinderShell style={{ height: 'calc(100vh - 64px)' }}>
      <TitleBar
        icon={<ReadOutlined />}
        title="长期记忆"
        titleExtra={<OrgSelect value={orgId} onChange={setOrgId} />}
      />

      <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
        {/* 左：组织架构树 */}
        <Sidebar header="组织架构" style={{ flex: 2, maxWidth: 264 }}>
          {isLoading ? <FinderLoading /> : treeData.length === 0 ? (
            <div style={{ padding: '8px 12px', color: WB.textAux, fontSize: FS.aux }}>{orgId ? '该组织下暂无记忆节点' : '请先选择组织'}</div>
          ) : (
            <MacTree
              nodes={treeData}
              selectedKey={selectedKey}
              onSelect={(key) => {
                const m = memByKey.get(key);
                if (m) {
                  setSelectedKey(key);
                  setEditing(m);
                  form.setFieldsValue({ content: m.content });
                }
              }}
            />
          )}
        </Sidebar>

        {/* 右：长期记忆编辑区 */}
        <section style={{ flex: 8, minWidth: 0, display: 'flex', flexDirection: 'column', background: '#fff' }}>
          {!editing ? (
            <FinderEmpty description="请从左侧选择记忆节点" />
          ) : (
            <>
              <Toolbar
                left={<span style={{ fontSize: FS.body, fontWeight: 600, color: WB.text }}>编辑长期记忆 · {editing.path}</span>}
                right={<ToolButton primary disabled={saveMem.isPending} onClick={() => form.submit()}>保存</ToolButton>}
              />
              <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', padding: '12px 16px' }}>
                <Typography.Text style={{ display: 'block', marginBottom: 8, fontSize: FS.micro, color: WB.textAux }}>
                  {SCOPE_LABEL[editing.scope_type] ?? editing.scope_type} · 内容以 markdown 存储；
                  {editing.scope_type === 'user'
                    ? '个人记忆分 ## 个人档案（系统同步）与 ## 沉淀记忆（智能体追加），可手动修订。'
                    : '## 档案 分节由系统按节点名称同步，其它分节可自由编辑。'}
                </Typography.Text>
                <Form form={form} layout="vertical" onFinish={(v) => saveMem.mutate(v)} style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
                  <Form.Item name="content" rules={[{ required: true, message: '请输入记忆内容' }]} style={{ flex: 1, minHeight: 0, marginBottom: 0 }} wrapperCol={{ style: { flex: 1, minHeight: 0 } }}>
                    <TextArea autoSize={{ minRows: 8, maxRows: 24 }} style={{ height: '100%', fontFamily: 'monospace', fontSize: FS.body }} />
                  </Form.Item>
                </Form>
              </div>
            </>
          )}
        </section>
      </div>
    </FinderShell>
  );
}
