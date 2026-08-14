import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import {
  Input, Modal, Tooltip, Typography, Upload, message,
} from 'antd';
import {
  DeleteOutlined, EditOutlined, SearchOutlined, UploadOutlined,
  FolderOutlined, FileTextOutlined, EyeOutlined, DownOutlined, RightOutlined,
  BankOutlined, ApartmentOutlined, TeamOutlined, UserOutlined, ToolOutlined,
} from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { skillStore } from '../../api/client';
import type { SkillFile, SkillFileMeta, SkillFolder } from '../../api/client';
import { ApiError } from '../../api/client';
import OrgSelect from '../../components/OrgSelect';
import { useOrgTree } from '../../hooks/useOrgTree';
import {
  FinderShell, TitleBar, Sidebar, MacTree, ToolButton,
  FinderEmpty, FinderLoading, type FinderTreeNode,
} from '../../components/finder/primitives';
import ConfirmModal from '../../components/finder/ConfirmModal';
import { WB, FS } from '../../components/finder/theme';

interface ScopeState {
  scope_type: 'organization' | 'department' | 'team' | 'user';
  scope_id: string | null;
  orgId: string;
  nodeName: string;
}

const SCOPE_PREFIX: Record<ScopeState['scope_type'], string> = {
  organization: 'org', department: 'dept', team: 'team', user: 'user',
};
const NODE_ICON: Record<string, ReactNode> = {
  org: <BankOutlined />, dept: <ApartmentOutlined />, team: <TeamOutlined />, user: <UserOutlined />,
};
const iconForKey = (key: string): ReactNode => NODE_ICON[key.split(':')[0]] ?? <FolderOutlined />;

function slugify(s: string): string {
  return s.toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .replace(/-{2,}/g, '-')
    .slice(0, 100) || `skill-${Date.now()}`;
}

/** 技能（文件夹）管理：Finder 风。左：组织架构树（节点作用域）；右：技能列表（可展开看文件）。
 *  一个技能 = 一个文件夹；上传 skill.md 即新建技能，skill.md 内 ```skill JSON 块定义 function-tool。 */
export default function Skills() {
  const qc = useQueryClient();
  const { treeData, nodeMap, isLoading: treeLoading } = useOrgTree();
  const [orgId, setOrgId] = useState<string | undefined>();

  const [scope, setScope] = useState<ScopeState | null>(null);
  const [keyword, setKeyword] = useState('');
  const [expanded, setExpanded] = useState<string | null>(null);
  const [renameModal, setRenameModal] = useState<SkillFolder | null>(null);
  const [renameName, setRenameName] = useState('');
  const [viewFile, setViewFile] = useState<SkillFile | null>(null);
  const [confirm, setConfirm] = useState<{ kind: 'folder' | 'file'; id: string; name: string } | null>(null);

  const treeDataScoped = useMemo(() => {
    if (!orgId) return [];
    return treeData.filter((n) => n.key === `org:${orgId}`);
  }, [treeData, orgId]);

  const finderTree = useMemo((): FinderTreeNode[] => {
    const build = (nodes: typeof treeData): FinderTreeNode[] =>
      nodes.map((n) => ({
        key: n.key, label: n.title, icon: iconForKey(n.key),
        children: n.children?.length ? build(n.children) : undefined,
      }));
    return build(treeDataScoped);
  }, [treeDataScoped]);

  // 选中组织变化（或树首次加载且未选 scope）→ 落到该组织根节点作为默认作用域
  useEffect(() => {
    if (scope || treeLoading || !orgId) return;
    const info = nodeMap.get(`org:${orgId}`);
    if (info) setScope({ scope_type: 'organization', scope_id: null, orgId: info.orgId, nodeName: info.name });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId, treeLoading, treeData]);

  const scopeRef = scope ? { scope_type: scope.scope_type, scope_id: scope.scope_id } : null;
  const selectedKey = scope ? `${SCOPE_PREFIX[scope.scope_type]}:${scope.scope_id ?? scope.orgId}` : null;

  const { data: folders, isLoading: foldersLoading } = useQuery({
    queryKey: ['skill-folders', scope?.orgId, scope?.scope_type, scope?.scope_id],
    queryFn: () => scope ? skillStore.listFolders(scope.orgId, scopeRef!) : Promise.resolve([]),
    enabled: !!scope,
  });

  const { data: expandedFiles } = useQuery({
    queryKey: ['skill-files', expanded],
    queryFn: () => expanded ? skillStore.listFiles(expanded) : Promise.resolve([]),
    enabled: !!expanded,
  });

  const uploadSkill = useMutation({
    mutationFn: (v: { name: string; slug: string; content: string }) => {
      if (!scope) return Promise.reject(new Error('no scope'));
      return skillStore.createFolder(scope.orgId, {
        name: v.name, slug: v.slug, scope_type: scope.scope_type, scope_id: scope.scope_id,
      }).then((folder) => skillStore.upsertFile(folder.id, { path: 'skill.md', content: v.content }).then(() => folder));
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['skill-folders'] }); message.success('技能已上传'); },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '上传失败'),
  });

  const uploadFile = useMutation({
    mutationFn: (v: { folderId: string; path: string; content: string }) =>
      skillStore.upsertFile(v.folderId, { path: v.path, content: v.content }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['skill-files'] }); message.success('文件已上传'); },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '上传失败'),
  });

  const delFolder = useMutation({
    mutationFn: (id: string) => skillStore.deleteFolder(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['skill-folders'] }); if (expanded) setExpanded(null); message.success('已删除'); },
    onError: () => message.error('删除失败'),
  });

  const delFile = useMutation({
    mutationFn: (id: string) => skillStore.deleteFile(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['skill-files'] }); message.success('已删除'); },
    onError: () => message.error('删除失败'),
  });

  const renameFolder = useMutation({
    mutationFn: (v: { id: string; name: string }) => skillStore.updateFolder(v.id, { name: v.name }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['skill-folders'] }); setRenameModal(null); message.success('已重命名'); },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '重命名失败'),
  });

  const openView = (f: SkillFileMeta) => {
    skillStore.getFile(f.id).then(setViewFile).catch(() => message.error('读取失败'));
  };

  const kw = keyword.trim().toLowerCase();
  const filtered = kw ? (folders ?? []).filter((f) => f.name.toLowerCase().includes(kw) || f.slug.toLowerCase().includes(kw)) : (folders ?? []);

  return (
    <FinderShell style={{ height: 'calc(100vh - 64px)' }}>
      <TitleBar
        icon={<ToolOutlined />}
        title="技能"
        titleExtra={<OrgSelect value={orgId} onChange={(v) => { setOrgId(v); setExpanded(null); setViewFile(null); setScope(null); }} />}
        extra={
          <>
            <Input size="small" allowClear placeholder="搜索技能" prefix={<SearchOutlined style={{ color: WB.textAux }} />} style={{ width: 180 }} value={keyword} onChange={(e) => setKeyword(e.target.value)} />
            <Upload showUploadList={false} accept=".md,.markdown,.txt"
              beforeUpload={(file) => {
                const reader = new FileReader();
                reader.onload = () => {
                  const text = String(reader.result ?? '');
                  const base = file.name.replace(/\.(md|markdown|txt)$/i, '');
                  uploadSkill.mutate({ name: base, slug: slugify(base), content: text });
                };
                reader.onerror = () => message.error('读取文件失败');
                reader.readAsText(file);
                return false;
              }}
            >
              <ToolButton primary icon={<UploadOutlined style={{ fontSize: 13 }} />} disabled={uploadSkill.isPending}>上传技能</ToolButton>
            </Upload>
          </>
        }
      />

      <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
        {/* 左栏：组织架构树 */}
        <Sidebar header="组织架构" style={{ flex: 2, maxWidth: 240 }}>
          {treeLoading ? <FinderLoading /> : finderTree.length === 0 ? (
            <div style={{ padding: '8px 12px', color: WB.textAux, fontSize: FS.aux }}>暂无组织架构</div>
          ) : (
            <MacTree
              nodes={finderTree}
              selectedKey={selectedKey}
              onSelect={(key) => {
                const info = nodeMap.get(key);
                if (!info) return;
                setExpanded(null);
                setScope({ scope_type: info.type, scope_id: info.type === 'organization' ? null : info.id, orgId: info.orgId, nodeName: info.name });
              }}
            />
          )}
        </Sidebar>

        {/* 右栏：技能列表（可展开看文件） */}
        <section style={{ flex: 8, minWidth: 0, display: 'flex', flexDirection: 'column', background: '#fff' }}>
          {!scope ? (
            <FinderEmpty description="请从左侧选择节点" />
          ) : (
            <div style={{ flex: 1, overflowY: 'auto', padding: '4px 0' }} className="wb-scroll-hide">
              {foldersLoading ? <FinderLoading /> : filtered.length === 0 ? (
                <div style={{ textAlign: 'center', color: WB.textAux, fontSize: FS.body, marginTop: 40 }}>
                  {kw ? '无匹配技能' : '该节点下暂无技能，点「上传技能」新建'}
                </div>
              ) : filtered.map((f) => {
                const open = expanded === f.id;
                return (
                  <div key={f.id}>
                    <div
                      onClick={() => setExpanded(open ? null : f.id)}
                      onMouseEnter={(e) => { e.currentTarget.style.background = open ? WB.hover : WB.hover; }}
                      onMouseLeave={(e) => { e.currentTarget.style.background = open ? '#f5f5f7' : 'transparent'; }}
                      style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 12px', margin: '1px 6px', borderRadius: 6, cursor: 'pointer', fontSize: FS.body, lineHeight: 1, background: open ? '#f5f5f7' : 'transparent' }}
                    >
                      {open ? <DownOutlined style={{ fontSize: 11, color: WB.textAux }} /> : <RightOutlined style={{ fontSize: 11, color: WB.textAux }} />}
                      <FolderOutlined style={{ fontSize: 16, color: '#faad14' }} />
                      <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: WB.text }}>{f.name}</span>
                      <span style={{ display: 'flex', gap: 2, flex: '0 0 auto' }} onClick={(e) => e.stopPropagation()}>
                        <Tooltip title="重命名"><ActionBtn icon={<EditOutlined />} onClick={() => { setRenameModal(f); setRenameName(f.name); }} /></Tooltip>
                        <ActionBtn icon={<DeleteOutlined />} danger onClick={() => setConfirm({ kind: 'folder', id: f.id, name: f.name })} />
                      </span>
                    </div>
                    {open && (
                      <div style={{ padding: '4px 12px 10px 40px', borderBottom: `1px solid ${WB.border}` }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                          <Upload showUploadList={false}
                            beforeUpload={(file) => {
                              const reader = new FileReader();
                              reader.onload = () => {
                                uploadFile.mutate({ folderId: f.id, path: file.name, content: String(reader.result ?? '') });
                              };
                              reader.onerror = () => message.error('读取文件失败');
                              reader.readAsText(file);
                              return false;
                            }}
                          >
                            <ToolButton icon={<UploadOutlined style={{ fontSize: 12 }} />} disabled={uploadFile.isPending}>上传文件</ToolButton>
                          </Upload>
                          <Typography.Text style={{ fontSize: FS.micro, color: WB.textAux }}>skill.md 定义函数 manifest</Typography.Text>
                        </div>
                        {(expandedFiles?.length ?? 0) === 0 ? (
                          <div style={{ padding: '4px 0', color: WB.textAux, fontSize: FS.micro }}>暂无文件</div>
                        ) : (expandedFiles ?? []).map((fl) => (
                          <div key={fl.id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0', fontSize: FS.body }}>
                            <FileTextOutlined style={{ fontSize: 14, color: '#8c8c8c' }} />
                            <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: WB.text }}>{fl.path}</span>
                            <span style={{ fontSize: FS.micro, color: WB.textAux }}>{fl.size} B</span>
                            <span style={{ display: 'flex', gap: 2, flex: '0 0 auto' }}>
                              <Tooltip title="查看"><ActionBtn icon={<EyeOutlined />} onClick={() => openView(fl)} /></Tooltip>
                              <ActionBtn icon={<DeleteOutlined />} danger onClick={() => setConfirm({ kind: 'file', id: fl.id, name: fl.path })} />
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </section>
      </div>

      {/* 重命名技能 */}
      <Modal title="重命名技能" open={!!renameModal}
        onCancel={() => setRenameModal(null)}
        onOk={() => {
          const name = renameName.trim();
          if (!name) { message.warning('请输入名称'); return; }
          if (renameModal) renameFolder.mutate({ id: renameModal.id, name });
        }}
        confirmLoading={renameFolder.isPending}>
        <Input value={renameName} onChange={(e) => setRenameName(e.target.value)} placeholder="技能名称" />
      </Modal>

      {/* 查看文件 */}
      <Modal title={viewFile?.path ?? ''} open={!!viewFile}
        onCancel={() => setViewFile(null)} footer={null} width={720}>
        {viewFile && (
          <div className="wb-md" style={{ maxHeight: '60vh', overflowY: 'auto', padding: 8 }}>
            {/\.md$/i.test(viewFile.path) || !viewFile.content ? (
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{viewFile.content ?? ''}</ReactMarkdown>
            ) : (
              <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: 12, background: '#f5f5f5', padding: 8 }}>{viewFile.content}</pre>
            )}
          </div>
        )}
      </Modal>

      <ConfirmModal
        open={!!confirm}
        title={confirm?.kind === 'folder' ? '删除技能' : '删除文件'}
        desc={confirm?.kind === 'folder'
          ? `将删除技能「${confirm?.name}」及其全部文件，此操作不可撤销。`
          : `确定删除文件「${confirm?.name}」？此操作不可撤销。`}
        loading={confirm?.kind === 'folder' ? delFolder.isPending : delFile.isPending}
        onCancel={() => setConfirm(null)}
        onOk={() => {
          if (!confirm) return;
          if (confirm.kind === 'folder') delFolder.mutate(confirm.id);
          else delFile.mutate(confirm.id);
          setConfirm(null);
        }}
      />
    </FinderShell>
  );
}

/** 紧凑行内动作按钮（图标按钮）。 */
function ActionBtn({ icon, danger, onClick, title }: {
  icon: ReactNode; danger?: boolean; onClick?: () => void; title?: string;
}) {
  return (
    <Tooltip title={title}>
      <button
        onClick={onClick}
        style={{
          width: 24, height: 24, borderRadius: 5, border: 'none', cursor: 'pointer',
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 13,
          background: 'transparent', color: danger ? WB.danger : WB.textAux,
        }}
      >
        {icon}
      </button>
    </Tooltip>
  );
}
