import { useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import {
  Drawer, Input, Tooltip, Typography, Upload, message,
} from 'antd';
import {
  DeleteOutlined, FolderAddOutlined, ArrowUpOutlined, HomeOutlined,
  UploadOutlined, FolderOutlined, FileTextOutlined, EditOutlined,
  SearchOutlined, EyeOutlined, CloseOutlined,
  BankOutlined, ApartmentOutlined, TeamOutlined, UserOutlined, PartitionOutlined,
} from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ontologyStore } from '../../api/client';
import type { OntologyFile, OntologyFolder } from '../../api/client';
import { ApiError } from '../../api/client';
import OrgSelect from '../../components/OrgSelect';
import { useOrgTree } from '../../hooks/useOrgTree';
import {
  FinderShell, TitleBar, Sidebar, MacTree, Toolbar, PathBar, NavButton, ToolButton,
  FinderGrid, IconCard, IconActionButton, IconName, FinderEmpty, FinderLoading,
  FinderPromptModal, type FinderTreeNode,
} from '../../components/finder/primitives';
import ConfirmModal from '../../components/finder/ConfirmModal';
import { WB, WB_FONT, FS } from '../../components/finder/theme';

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

/** 本体（Markdown 文件 + 文件夹）管理：Finder 风。
 *  左：组织架构树（节点作用域）；右：文件夹/文件网格；点文件以右侧抽屉查看/编辑。 */
export default function OntologyPage() {
  const qc = useQueryClient();
  const { treeData, nodeMap, isLoading: treeLoading } = useOrgTree();
  const [orgId, setOrgId] = useState<string | undefined>();

  const [scope, setScope] = useState<ScopeState | null>(null);
  const [cwd, setCwd] = useState<string[]>([]);
  const [keyword, setKeyword] = useState('');
  // 文件查看抽屉：可同时打开多个，顶部紧凑 tab 条切换。
  const [openFiles, setOpenFiles] = useState<OntologyFile[]>([]);
  const [activeFileId, setActiveFileId] = useState<string | null>(null);
  const [folderModal, setFolderModal] = useState<{ open: boolean; editing: OntologyFolder | null }>({ open: false, editing: null });
  const [folderName, setFolderName] = useState('');
  const [renameFileModal, setRenameFileModal] = useState<OntologyFile | null>(null);
  const [renameFileName, setRenameFileName] = useState('');
  const [confirm, setConfirm] = useState<{ kind: 'folder' | 'file'; id: string; name: string } | null>(null);
  const composingRef = useRef(false);

  const treeDataScoped = useMemo(() => {
    if (!orgId) return [];
    return treeData.filter((n) => n.key === `org:${orgId}`);
  }, [treeData, orgId]);

  const finderTree = useMemo((): FinderTreeNode[] => {
    const build = (nodes: typeof treeData): FinderTreeNode[] =>
      nodes.map((n) => ({ key: n.key, label: n.title, icon: iconForKey(n.key), children: n.children?.length ? build(n.children) : undefined }));
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
    queryKey: ['ontology-folders', scope?.orgId, scope?.scope_type, scope?.scope_id],
    queryFn: () => scope ? ontologyStore.listFolders(scope.orgId, scopeRef!) : Promise.resolve([]),
    enabled: !!scope,
  });
  const { data: files, isLoading: filesLoading } = useQuery({
    queryKey: ['ontology-files', scope?.orgId, scope?.scope_type, scope?.scope_id],
    queryFn: () => scope ? ontologyStore.listFiles(scope.orgId, scopeRef!) : Promise.resolve([]),
    enabled: !!scope,
  });

  const { folderItems, fileItems } = useMemo(() => {
    const folderByName = new Map<string, OntologyFolder | null>();
    const addFolder = (name: string, rec: OntologyFolder | null) => {
      if (!folderByName.has(name)) folderByName.set(name, rec);
      else if (rec && !folderByName.get(name)) folderByName.set(name, rec);
    };
    const prefix = cwd.length ? `${cwd.join('/')}/` : '';
    const rel = (p: string) => (prefix ? p.slice(prefix.length) : p);
    for (const f of folders ?? []) {
      const r = rel(f.path);
      if (!r) continue;
      if (r.includes('/')) addFolder(r.split('/')[0], null);
      else addFolder(r, f);
    }
    const directFiles: { file: OntologyFile; name: string }[] = [];
    for (const f of files ?? []) {
      const r = rel(f.path);
      if (!r) continue;
      if (r.includes('/')) addFolder(r.split('/')[0], null);
      else directFiles.push({ file: f, name: r });
    }
    const folderItems = [...folderByName.entries()].map(([name, record]) => ({ name, record })).sort((a, b) => a.name.localeCompare(b.name));
    directFiles.sort((a, b) => a.name.localeCompare(b.name));
    return { folderItems, fileItems: directFiles };
  }, [files, folders, cwd]);

  const uploadFile = useMutation({
    mutationFn: (v: { path: string; content: string }) => {
      if (!scope) return Promise.reject(new Error('no scope'));
      return ontologyStore.upsertFile(scope.orgId, { ...v, scope_type: scope.scope_type, scope_id: scope.scope_id });
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['ontology-files'] }); message.success('本体已上传'); },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '上传失败'),
  });
  const delFile = useMutation({
    mutationFn: (id: string) => ontologyStore.deleteFile(id),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: ['ontology-files'] });
      setOpenFiles((prev) => prev.filter((x) => x.id !== id));
      setActiveFileId((cur) => (cur === id ? null : cur));
      message.success('已删除');
    },
    onError: () => message.error('删除失败'),
  });
  const createFolder = useMutation({
    mutationFn: (name: string) => {
      if (!scope) return Promise.reject(new Error('no scope'));
      const path = [...cwd, name].join('/');
      return ontologyStore.createFolder(scope.orgId, { path, scope_type: scope.scope_type, scope_id: scope.scope_id });
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['ontology-folders'] }); setFolderModal({ open: false, editing: null }); setFolderName(''); message.success('文件夹已创建'); },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '创建失败'),
  });
  const renameFolderMut = useMutation({
    mutationFn: (v: { id: string; path: string }) => ontologyStore.renameFolder(v.id, v.path),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['ontology-folders'] }); qc.invalidateQueries({ queryKey: ['ontology-files'] }); setFolderModal({ open: false, editing: null }); setFolderName(''); message.success('已重命名'); },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '重命名失败'),
  });
  const delFolder = useMutation({
    mutationFn: (id: string) => ontologyStore.deleteFolder(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['ontology-folders'] }); qc.invalidateQueries({ queryKey: ['ontology-files'] }); message.success('文件夹及其内容已删除'); },
    onError: () => message.error('删除失败'),
  });
  const renameFileMut = useMutation({
    mutationFn: (v: { id: string; path: string }) => ontologyStore.updateFile(v.id, { path: v.path }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['ontology-files'] }); setRenameFileModal(null); message.success('已重命名'); },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '重命名失败'),
  });

  const openFile = (f: OntologyFile) => {
    setOpenFiles((prev) => (prev.some((x) => x.id === f.id) ? prev : [...prev, f]));
    setActiveFileId(f.id);
  };
  const closeFile = (id: string) => {
    setOpenFiles((prev) => prev.filter((x) => x.id !== id));
    setActiveFileId((cur) => {
      if (cur !== id) return cur;
      const remain = openFiles.filter((x) => x.id !== id);
      return remain[remain.length - 1]?.id ?? null;
    });
  };
  const activeFile = openFiles.find((f) => f.id === activeFileId) ?? null;

  const submitFolder = () => {
    const name = folderName.trim();
    if (!name || name.includes('/')) { message.warning('请输入有效名称（不含 /）'); return; }
    if (folderModal.editing) renameFolderMut.mutate({ id: folderModal.editing.id, path: [...cwd, name].join('/') });
    else createFolder.mutate(name);
  };

  const kw = keyword.trim().toLowerCase();
  const fItems = kw ? fileItems.filter((it) => it.name.toLowerCase().includes(kw)) : fileItems;
  const dItems = kw ? [] : folderItems; // 搜索时仅匹配文件，隐藏文件夹网格

  return (
    <FinderShell style={{ height: 'calc(100vh - 64px)' }}>
      <TitleBar
        icon={<PartitionOutlined />}
        title="本体"
        titleExtra={<OrgSelect value={orgId} onChange={(v) => { setOrgId(v); setCwd([]); setOpenFiles([]); setActiveFileId(null); setScope(null); }} />}
        extra={
          <>
            <Input size="small" allowClear placeholder="搜索本体文件" prefix={<SearchOutlined style={{ color: WB.textAux }} />} style={{ width: 180 }} value={keyword} onChange={(e) => setKeyword(e.target.value)} />
          </>
        }
      />

      <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
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
                setCwd([]); setOpenFiles([]); setActiveFileId(null);
                setScope({ scope_type: info.type, scope_id: info.type === 'organization' ? null : info.id, orgId: info.orgId, nodeName: info.name });
              }}
            />
          )}
        </Sidebar>

        <section style={{ flex: 8, minWidth: 0, display: 'flex', flexDirection: 'column', background: '#fff' }}>
          {!scope ? (
            <FinderEmpty description="请从左侧选择节点" />
          ) : (
            <>
              <Toolbar
                left={
                  <>
                    <NavButton icon={<ArrowUpOutlined style={{ transform: 'rotate(-90deg)' }} />} disabled={cwd.length === 0} onClick={() => setCwd((c) => c.slice(0, -1))} title="返回上一级" />
                    <PathBar rootLabel="根" rootIcon={<HomeOutlined style={{ fontSize: 12 }} />} segs={cwd} onSeg={(i) => setCwd((c) => (i < 0 ? [] : c.slice(0, i + 1)))} />
                  </>
                }
                right={
                  <>
                    <ToolButton icon={<FolderAddOutlined style={{ fontSize: 13 }} />} onClick={() => { setFolderName(''); setFolderModal({ open: true, editing: null }); }}>新建文件夹</ToolButton>
                    <Upload showUploadList={false} accept=".md,.markdown,.txt"
                      beforeUpload={(file) => {
                        const reader = new FileReader();
                        reader.onload = () => {
                          const text = String(reader.result ?? '');
                          const path = [...cwd, file.name].join('/');
                          uploadFile.mutate({ path, content: text });
                        };
                        reader.onerror = () => message.error('读取文件失败');
                        reader.readAsText(file);
                        return false;
                      }}
                    >
                      <ToolButton primary icon={<UploadOutlined style={{ fontSize: 13 }} />} disabled={uploadFile.isPending}>上传本体</ToolButton>
                    </Upload>
                  </>
                }
              />

              <div style={{ flex: 1, overflowY: 'auto', padding: '18px 20px' }} className="wb-scroll-hide">
                {(foldersLoading || filesLoading) && folderItems.length === 0 && fileItems.length === 0 ? (
                  <FinderLoading />
                ) : (dItems.length === 0 && fItems.length === 0) ? (
                  <div style={{ textAlign: 'center', color: WB.textAux, fontSize: FS.body, marginTop: 48 }}>
                    {kw ? '无匹配本体文件' : '此处暂无文件夹 / 本体'}
                  </div>
                ) : (
                  <FinderGrid>
                    {dItems.map((it) => (
                      <IconCard
                        key={`d:${it.name}`}
                        onClick={() => setCwd((c) => [...c, it.name])}
                        actions={(hover) => (it.record && hover) ? (
                          <span key="a" style={{ position: 'absolute', top: -6, right: -6, zIndex: 2, display: 'flex', gap: 4 }} onClick={(e) => e.stopPropagation()}>
                            <Tooltip title="重命名"><IconActionButton icon={<EditOutlined />} onClick={() => { setFolderName(it.name); setFolderModal({ open: true, editing: it.record }); }} /></Tooltip>
                            <IconActionButton icon={<DeleteOutlined />} variant="danger" onClick={() => it.record && setConfirm({ kind: 'folder', id: it.record.id, name: it.name })} />
                          </span>
                        ) : null}
                      >
                        <FolderOutlined style={{ fontSize: 42, color: WB.macFolder }} />
                        <IconName>{it.name}</IconName>
                      </IconCard>
                    ))}
                    {fItems.map((it) => (
                      <IconCard
                        key={`f:${it.file.id}`}
                        actions={(hover) => hover ? (
                          <span key="a" style={{ position: 'absolute', top: -6, right: -6, zIndex: 2, display: 'flex', gap: 4 }} onClick={(e) => e.stopPropagation()}>
                            <Tooltip title="查看"><IconActionButton icon={<EyeOutlined />} onClick={() => openFile(it.file)} /></Tooltip>
                            <Tooltip title="重命名"><IconActionButton icon={<EditOutlined />} onClick={() => { setRenameFileModal(it.file); setRenameFileName(it.name); }} /></Tooltip>
                            <IconActionButton icon={<DeleteOutlined />} variant="danger" onClick={() => setConfirm({ kind: 'file', id: it.file.id, name: it.name })} />
                          </span>
                        ) : null}
                      >
                        <div onClick={() => openFile(it.file)} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', cursor: 'pointer' }}>
                          <FileTextOutlined style={{ fontSize: 42, color: WB.macFile }} />
                          <IconName>{it.name}</IconName>
                          <span style={{ fontSize: 10, color: WB.textMicro, marginTop: 1 }}>{it.file.size} B</span>
                        </div>
                      </IconCard>
                    ))}
                  </FinderGrid>
                )}
                {dItems.length === 0 && fItems.length === 0 && !foldersLoading && !filesLoading && (
                  <Typography.Text style={{ display: 'block', marginTop: 16, fontSize: FS.micro, color: WB.textMicro, textAlign: 'center' }}>
                    点击文件夹进入 · 点击文件查看 · 「上传本体」写入当前目录（同名覆盖）
                  </Typography.Text>
                )}
              </div>
            </>
          )}
        </section>
      </div>

      {/* 文件查看 / 编辑：右侧抽屉 */}
      <Drawer
        open={!!activeFileId}
        onClose={() => setActiveFileId(null)}
        width={720}
        rootStyle={{ fontFamily: WB_FONT }}
        styles={{ header: { borderBottom: `1px solid ${WB.border}` }, body: { padding: 0, display: 'flex', flexDirection: 'column' } }}
        title={activeFile ? basename(activeFile.path) : '本体查看'}
      >
        {openFiles.length > 1 && (
          <div style={{ display: 'flex', gap: 4, padding: '8px 16px', borderBottom: `1px solid ${WB.border}`, overflowX: 'auto' }} className="wb-scroll-hide">
            {openFiles.map((f) => {
              const active = f.id === activeFileId;
              return (
                <span key={f.id} onClick={() => setActiveFileId(f.id)} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: FS.aux, cursor: 'pointer', padding: '3px 8px', borderRadius: 6, whiteSpace: 'nowrap', background: active ? WB.activeBg : 'transparent', color: active ? WB.primary : WB.text }}>
                  <FileTextOutlined style={{ fontSize: 11 }} />{basename(f.path)}
                  <CloseOutlined onClick={(e) => { e.stopPropagation(); closeFile(f.id); }} style={{ fontSize: 10, color: WB.textAux }} />
                </span>
              );
            })}
          </div>
        )}
        <div style={{ flex: 1, minHeight: 0 }}>
          {activeFile && <OntologyFileViewer file={activeFile} />}
        </div>
      </Drawer>

      {/* 新建 / 重命名 文件夹 */}
      <FinderPromptModal
        open={folderModal.open}
        title={folderModal.editing ? '重命名文件夹' : '新建文件夹'}
        placeholder="文件夹名"
        value={folderName}
        setValue={setFolderName}
        suffix={folderName ? <Typography.Text style={{ fontSize: FS.micro, color: WB.textAux }}>→ {[...cwd, folderName].join('/')}</Typography.Text> : null}
        composingRef={composingRef}
        loading={createFolder.isPending || renameFolderMut.isPending}
        okText={folderModal.editing ? '重命名' : '创建'}
        onCancel={() => { setFolderModal({ open: false, editing: null }); setFolderName(''); }}
        onOk={submitFolder}
      />

      {/* 重命名 本体文件 */}
      <FinderPromptModal
        open={!!renameFileModal}
        title="重命名本体"
        placeholder="文件名.md"
        value={renameFileName}
        setValue={setRenameFileName}
        suffix={renameFileName ? <Typography.Text style={{ fontSize: FS.micro, color: WB.textAux }}>→ {[...cwd, renameFileName].join('/')}</Typography.Text> : null}
        composingRef={composingRef}
        loading={renameFileMut.isPending}
        okText="重命名"
        onCancel={() => setRenameFileModal(null)}
        onOk={() => {
          const name = renameFileName.trim();
          if (!name || name.includes('/')) { message.warning('请输入有效文件名（不含 /）'); return; }
          if (renameFileModal) renameFileMut.mutate({ id: renameFileModal.id, path: [...cwd, name].join('/') });
        }}
      />

      <ConfirmModal
        open={!!confirm}
        title={confirm?.kind === 'folder' ? '删除文件夹' : '删除本体'}
        desc={confirm?.kind === 'folder'
          ? `将一并删除文件夹「${confirm?.name}」及其下所有内容，此操作不可撤销。`
          : `确定删除本体「${confirm?.name}」？此操作不可撤销。`}
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

/** 本体文件查看器：Markdown 渲染 + 内联编辑（保存调 PATCH）。 */
function OntologyFileViewer({ file }: { file: OntologyFile }) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(file.content ?? '');

  useEffect(() => { setDraft(file.content ?? ''); setEditing(false); }, [file.id, file.content]);

  const save = useMutation({
    mutationFn: (content: string) => ontologyStore.updateFile(file.id, { content }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['ontology-files'] }); message.success('已保存'); setEditing(false); },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '保存失败'),
  });

  if (editing) {
    return (
      <div style={{ height: '100%', display: 'flex', flexDirection: 'column', padding: 12 }}>
        <div style={{ marginBottom: 8, display: 'flex', gap: 8 }}>
          <ToolButton primary disabled={save.isPending} onClick={() => save.mutate(draft)}>保存</ToolButton>
          <ToolButton onClick={() => { setDraft(file.content ?? ''); setEditing(false); }}>取消</ToolButton>
        </div>
        <Input.TextArea value={draft} onChange={(e) => setDraft(e.target.value)} style={{ flex: 1, minHeight: 0, fontFamily: 'monospace', fontSize: FS.body }} />
      </div>
    );
  }
  return (
    <div style={{ height: '100%', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <div style={{ padding: '8px 16px', borderBottom: `1px solid ${WB.border}` }}>
        <ToolButton icon={<EditOutlined style={{ fontSize: 13 }} />} onClick={() => setEditing(true)}>编辑</ToolButton>
      </div>
      <div className="wb-md" style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '16px 20px' }}>
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{file.content ?? ''}</ReactMarkdown>
      </div>
    </div>
  );
}

function basename(p: string): string {
  return p.split('/').pop() || p;
}
