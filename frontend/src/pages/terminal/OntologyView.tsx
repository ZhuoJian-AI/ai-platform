import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { Input, Typography, Upload, message, Empty, Spin, Tooltip } from 'antd';
import {
  DeleteOutlined, BankOutlined, ApartmentOutlined, TeamOutlined, UserOutlined,
  FolderOutlined, FileTextOutlined, FolderAddOutlined, ArrowUpOutlined,
  HomeOutlined, UploadOutlined, EditOutlined, RightOutlined, PartitionOutlined, TagsOutlined,
} from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { terminal, type OntologyFile, type OntologyFolder, type KbNode } from '../../api/client';
import { ApiError } from '../../api/client';
import { useUserAuth } from '../../context/UserAuthContext';
import ConfirmModal from '../../components/finder/ConfirmModal';
import OntologyFileDrawer from './OntologyFileDrawer';

/** WorkBuddy 配色（与 KnowledgeBaseView / WorkspaceManagerView 一致）。 */
const WB = {
  primary: '#6366F1', sidebar: '#F5F5F7', hover: '#ECECEF', border: '#E5E7EB',
  macFolder: '#5AC8FA', macFile: '#8b5cf6',
};
const WB_FONT = '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif';

const SCOPE_LABEL: Record<string, string> = {
  organization: '组织', department: '部门', team: '团队', user: '个人',
};
const SCOPE_ICON: Record<string, ReactNode> = {
  organization: <BankOutlined />, department: <ApartmentOutlined />, team: <TeamOutlined />, user: <UserOutlined />,
};

interface TreeNode {
  key: string;
  name: string;
  scope: string;
  scopeId: string | null;
  children?: TreeNode[];
}

/** 把后端单链 KbNode[] 组装成 组织→部门→团队→个人 嵌套树（每级至多一个）。 */
function buildTree(nodes: KbNode[]): TreeNode[] {
  let child: TreeNode | null = null;
  for (let i = nodes.length - 1; i >= 0; i--) {
    const n = nodes[i];
    const node: TreeNode = {
      key: `${n.scope_type}:${n.scope_id ?? ''}`,
      name: n.name, scope: n.scope_type, scopeId: n.scope_id,
      children: child ? [child] : undefined,
    };
    child = node;
  }
  return child ? [child] : [];
}

type ConfirmTarget = { kind: 'folder' | 'file'; id: string; name: string };

type NameMode = 'create-folder' | 'rename-folder' | 'rename-file';
interface NameModalState {
  open: boolean; mode: NameMode; target?: OntologyFolder | OntologyFile | null; value: string;
}

/** 终端「本体」视图：左右两栏（仿工作空间 / 知识库）。
 *  左栏：用户可见作用域单链（组织/部门/团队/个人）；右栏：选中 scope 下的本体文件夹 / Markdown 文件。
 *  导入 / 新建：任意可见 scope 均可；重命名 / 编辑 / 删除：仅限「自己创建」（created_by === 当前用户）。 */
export default function OntologyView() {
  const qc = useQueryClient();
  const { user } = useUserAuth();
  const myId = user?.id ?? null;
  const composingRef = useRef(false);

  const [scope, setScope] = useState<{ type: string; id: string | null; name: string } | null>(null);
  const [cwd, setCwd] = useState<string[]>([]); // 当前目录段数组，根为 []
  const [hovered, setHovered] = useState<string | null>(null);

  const [nameModal, setNameModal] = useState<NameModalState>({ open: false, mode: 'create-folder', value: '' });
  const [confirm, setConfirm] = useState<ConfirmTarget | null>(null);
  const [drawerFile, setDrawerFile] = useState<OntologyFile | null>(null);

  // 左栏 scope 链
  const { data: kbNodes, isLoading: nodesLoading } = useQuery({
    queryKey: ['ontology-nodes'], queryFn: () => terminal.ontologyNodes(),
  });
  const treeData = useMemo(() => buildTree(kbNodes ?? []), [kbNodes]);

  // 默认选中个人节点
  useEffect(() => {
    if (scope || !kbNodes?.length) return;
    const userNode = kbNodes.find((n) => n.scope_type === 'user');
    if (userNode) setScope({ type: userNode.scope_type, id: userNode.scope_id, name: userNode.name });
  }, [kbNodes, scope]);

  // 切换 scope 回到根
  useEffect(() => { setCwd([]); }, [scope?.type, scope?.id]);

  const scopeRef = scope ? { scope_type: scope.type, scope_id: scope.id } : null;
  const { data: folders, isLoading: foldersLoading } = useQuery({
    queryKey: ['ontology-folders', scope?.type, scope?.id],
    queryFn: () => scope ? terminal.listOntologyFolders(scopeRef!) : Promise.resolve([]),
    enabled: !!scope,
  });
  const { data: files, isLoading: filesLoading } = useQuery({
    queryKey: ['ontology-files', scope?.type, scope?.id],
    queryFn: () => scope ? terminal.listOntologyFiles(scopeRef!) : Promise.resolve([]),
    enabled: !!scope,
  });

  // 当前层级直系子项：显式文件夹 + 由路径推导的隐式文件夹 + 直系文件
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

  const isOwner = (created_by: string | null) => !!myId && created_by === myId;

  // ── 文件夹 增/改/删 ──
  const createFolder = useMutation({
    mutationFn: (name: string) => {
      if (!scope) return Promise.reject(new Error('no scope'));
      const path = [...cwd, name].join('/');
      return terminal.createOntologyFolder({ path, scope_type: scope.type, scope_id: scope.id });
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['ontology-folders'] }); setNameModal((m) => ({ ...m, open: false })); message.success('文件夹已创建'); },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '创建失败'),
  });
  const renameFolder = useMutation({
    mutationFn: (v: { id: string; path: string }) => terminal.renameOntologyFolder(v.id, v.path),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['ontology-folders'] }); qc.invalidateQueries({ queryKey: ['ontology-files'] }); setNameModal((m) => ({ ...m, open: false })); message.success('已重命名'); },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '重命名失败'),
  });
  const delFolder = useMutation({
    mutationFn: (id: string) => terminal.deleteOntologyFolder(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['ontology-folders'] }); qc.invalidateQueries({ queryKey: ['ontology-files'] }); message.success('文件夹及其内容已删除'); },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '删除失败'),
  });

  // ── 文件 增/改/删 ──
  const uploadFile = useMutation({
    mutationFn: (v: { path: string; content: string }) => {
      if (!scope) return Promise.reject(new Error('no scope'));
      return terminal.upsertOntologyFile({ ...v, metadata: {}, scope_type: scope.type, scope_id: scope.id });
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['ontology-files'] }); message.success('本体已上传'); },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '上传失败'),
  });
  const renameFile = useMutation({
    mutationFn: (v: { id: string; path: string }) => terminal.updateOntologyFile(v.id, { path: v.path }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['ontology-files'] }); setNameModal((m) => ({ ...m, open: false })); message.success('已重命名'); },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '重命名失败'),
  });
  const delFile = useMutation({
    mutationFn: (id: string) => terminal.deleteOntologyFile(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['ontology-files'] }); message.success('已删除'); },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '删除失败'),
  });

  const submitNameModal = () => {
    const m = nameModal;
    const name = m.value.trim();
    if (!name || name.includes('/')) { message.warning('请输入有效名称（不含 /）'); return; }
    if (m.mode === 'create-folder') createFolder.mutate(name);
    else if (m.mode === 'rename-folder' && m.target) renameFolder.mutate({ id: (m.target as OntologyFolder).id, path: [...cwd, name].join('/') });
    else if (m.mode === 'rename-file' && m.target) renameFile.mutate({ id: (m.target as OntologyFile).id, path: [...cwd, name].join('/') });
  };

  const confirmLoading = confirm?.kind === 'folder' ? delFolder.isPending : delFile.isPending;
  const confirmOk = () => {
    if (!confirm) return;
    if (confirm.kind === 'folder') delFolder.mutate(confirm.id);
    else delFile.mutate(confirm.id);
    setConfirm(null);
  };

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, fontFamily: WB_FONT, background: '#fff' }}>
      {/* 顶部标题栏 */}
      <div style={titleBarStyle}>
        <PartitionOutlined style={{ color: WB.primary, fontSize: 16 }} />
        <span style={{ fontSize: 13, fontWeight: 600, color: '#1d1d1f' }}>本体</span>
        <Typography.Text style={{ fontSize: 12, color: '#86868b' }}>
          {scope ? `${scope.name} · ${SCOPE_LABEL[scope.type]}` : '选择左侧节点'}
        </Typography.Text>
      </div>

      {/* 2:8 主体 */}
      <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
        {/* 左栏：作用域树 */}
        <aside style={sidebarStyle}>
          <div style={sidebarHeaderStyle}>组织架构</div>
          {nodesLoading ? (
            <div style={{ padding: 16, textAlign: 'center' }}><Spin /></div>
          ) : treeData.length === 0 ? (
            <div style={{ padding: '8px 12px', color: '#86868b', fontSize: 12 }}>暂无可访问的作用域</div>
          ) : (
            <MacTree
              nodes={treeData}
              selectedKey={scope ? `${scope.type}:${scope.id ?? ''}` : null}
              onSelect={(type, id, name) => setScope({ type, id, name })}
            />
          )}
        </aside>

        {/* 右栏：文件夹 / 本体文件 浏览器 */}
        <section style={{ flex: 8, minWidth: 0, display: 'flex', flexDirection: 'column', background: '#fff' }}>
          {!scope ? (
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="选择左侧节点以管理本体文件夹 / 文件" />
            </div>
          ) : (
            <>
              {/* 工具条 + Mac 路径栏 */}
              <div style={toolbarStyle}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0, flex: 1 }}>
                  <button
                    style={navBtnStyle(cwd.length === 0)}
                    disabled={cwd.length === 0}
                    onClick={() => setCwd((c) => c.slice(0, -1))}
                    title="返回上一级"
                  ><ArrowUpOutlined style={{ transform: 'rotate(-90deg)' }} /></button>
                  <div style={pathBarStyle}>
                    <span className="wb-path-seg" onClick={() => setCwd([])} style={pathSegStyle}>
                      <HomeOutlined style={{ fontSize: 12, marginRight: 4 }} />{scope.name}
                    </span>
                    {cwd.map((seg, i) => (
                      <span key={i} style={{ display: 'inline-flex', alignItems: 'center' }}>
                        <RightOutlined style={{ fontSize: 9, color: '#b0b0b5', margin: '0 2px' }} />
                        <span className="wb-path-seg" onClick={() => setCwd((c) => c.slice(0, i + 1))} style={pathSegStyle}>
                          {seg}
                        </span>
                      </span>
                    ))}
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button style={toolBtnStyle} onClick={() => setNameModal({ open: true, mode: 'create-folder', value: '' })}>
                    <FolderAddOutlined style={{ fontSize: 13 }} /> 新建文件夹
                  </button>
                  <Upload
                    showUploadList={false}
                    accept=".md,.markdown,.txt"
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
                    <button style={toolBtnStyle} disabled={uploadFile.isPending}>
                      <UploadOutlined style={{ fontSize: 13 }} /> 上传本体
                    </button>
                  </Upload>
                </div>
              </div>

              {/* 图标网格 */}
              <div style={{ flex: 1, overflowY: 'auto', padding: '18px 20px' }} className="wb-scroll-hide">
                {(foldersLoading || filesLoading) && (folders?.length === 0 && files?.length === 0) ? (
                  <div style={{ display: 'flex', justifyContent: 'center', padding: 48 }}><Spin /></div>
                ) : (folderItems.length === 0 && fileItems.length === 0) ? (
                  <div style={{ textAlign: 'center', color: '#86868b', fontSize: 13, marginTop: 48 }}>
                    此处暂无文件夹 / 本体
                  </div>
                ) : (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                    {folderItems.map((it) => {
                      const key = `d:${it.name}`;
                      const isHover = hovered === key;
                      const owner = it.record ? isOwner(it.record.created_by) : false;
                      return (
                        <div
                          key={key}
                          onMouseEnter={() => setHovered(key)}
                          onMouseLeave={() => setHovered(null)}
                          style={iconCardStyle(isHover)}
                        >
                          <div style={{ position: 'relative', display: 'flex', flexDirection: 'column', alignItems: 'center', width: 92, cursor: 'pointer' }}>
                            {it.record && isHover && (
                              <span style={{ position: 'absolute', top: -6, right: -6, zIndex: 2, display: 'flex', gap: 4 }} onClick={(e) => e.stopPropagation()}>
                                <IconAction title={owner ? '重命名' : '仅可重命名自己创建的'} disabled={!owner} icon={<EditOutlined />} onClick={() => setNameModal({ open: true, mode: 'rename-folder', target: it.record, value: it.name })} />
                                <IconAction title={owner ? '删除' : '仅可删除自己创建的'} danger disabled={!owner} icon={<DeleteOutlined />} onClick={() => it.record && setConfirm({ kind: 'folder', id: it.record.id, name: it.name })} />
                              </span>
                            )}
                            <div onClick={() => setCwd((c) => [...c, it.name])} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                              <FolderOutlined style={{ fontSize: 42, color: WB.macFolder }} />
                              <div style={iconNameStyle}>{it.name}</div>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                    {fileItems.map((it) => {
                      const key = `f:${it.file.id}`;
                      const isHover = hovered === key;
                      const owner = isOwner(it.file.created_by);
                      return (
                        <div
                          key={key}
                          onMouseEnter={() => setHovered(key)}
                          onMouseLeave={() => setHovered(null)}
                          style={iconCardStyle(isHover)}
                        >
                          <div style={{ position: 'relative', display: 'flex', flexDirection: 'column', alignItems: 'center', width: 92 }}>
                            {isHover && (
                              <span style={{ position: 'absolute', top: -6, right: -6, zIndex: 2, display: 'flex', gap: 4 }} onClick={(e) => e.stopPropagation()}>
                                <IconAction title={owner ? '查看 / 编辑' : '查看（仅创建者可编辑）'} icon={<EditOutlined />} onClick={() => setDrawerFile(it.file)} />
                                <IconAction title={owner ? '重命名' : '仅可重命名自己创建的'} disabled={!owner} icon={<TagsOutlined />} onClick={() => setNameModal({ open: true, mode: 'rename-file', target: it.file, value: it.name })} />
                                <IconAction title={owner ? '删除' : '仅可删除自己创建的'} danger disabled={!owner} icon={<DeleteOutlined />} onClick={() => setConfirm({ kind: 'file', id: it.file.id, name: it.name })} />
                              </span>
                            )}
                            <div onClick={() => setDrawerFile(it.file)} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', cursor: 'pointer' }}>
                              <FileTextOutlined style={{ fontSize: 42, color: WB.macFile }} />
                              <div style={iconNameStyle}>{it.name}</div>
                              <span style={{ fontSize: 10, color: '#aeaeb2', marginTop: 1 }}>{it.file.size} B</span>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
                {folderItems.length === 0 && fileItems.length === 0 && !foldersLoading && !filesLoading && (
                  <Typography.Text style={{ display: 'block', marginTop: 16, fontSize: 11, color: '#aeaeb2', textAlign: 'center' }}>
                    本体为 Markdown 格式；点击文件夹进入 · 点击文件查看 · 「上传本体」写入当前目录（同名覆盖）
                  </Typography.Text>
                )}
              </div>
            </>
          )}
        </section>
      </div>

      {/* 新建 / 重命名 模态 */}
      <NameModal
        state={nameModal}
        setState={setNameModal}
        composingRef={composingRef}
        loading={createFolder.isPending || renameFolder.isPending || renameFile.isPending}
        onOk={submitNameModal}
      />

      {/* 删除确认 */}
      <ConfirmModal
        open={!!confirm}
        title={confirm?.kind === 'folder' ? '删除该文件夹？' : '删除该本体？'}
        desc={confirm?.kind === 'folder' ? `将一并删除文件夹「${confirm?.name}」及其下所有内容，此操作不可撤销。` : `确定删除本体「${confirm?.name}」？此操作不可撤销。`}
        loading={confirmLoading}
        onCancel={() => setConfirm(null)}
        onOk={confirmOk}
      />

      {/* 查看 / 编辑抽屉 */}
      <OntologyFileDrawer
        open={!!drawerFile}
        file={drawerFile}
        canEdit={!!drawerFile && isOwner(drawerFile.created_by)}
        onClose={() => setDrawerFile(null)}
      />
    </div>
  );
}

// ── MacOS 风格作用域树（与 KnowledgeBaseView 同款） ──────────────────────

function MacTree({ nodes, selectedKey, onSelect }: {
  nodes: TreeNode[];
  selectedKey: string | null;
  onSelect: (type: string, id: string | null, name: string) => void;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(nodes.map((n) => n.key)));
  const toggle = (key: string) => setExpanded((s) => {
    const next = new Set(s);
    if (next.has(key)) next.delete(key); else next.add(key);
    return next;
  });
  const renderNode = (node: TreeNode, level: number): ReactNode => {
    const hasChildren = !!node.children?.length;
    const isOpen = expanded.has(node.key);
    const active = selectedKey === node.key;
    return (
      <div key={node.key}>
        <div
          onClick={() => onSelect(node.scope, node.scopeId, node.name)}
          onMouseEnter={(e) => { if (!active) e.currentTarget.style.background = WB.hover; }}
          onMouseLeave={(e) => { if (!active) e.currentTarget.style.background = 'transparent'; }}
          style={treeRowStyle(active, level)}
        >
          <span style={{ width: 12, display: 'inline-flex', justifyContent: 'center', flex: '0 0 12px' }}>
            {hasChildren && (
              <RightOutlined
                onClick={(e) => { e.stopPropagation(); toggle(node.key); }}
                style={{ fontSize: 9, color: '#86868b', cursor: 'pointer', transform: isOpen ? 'rotate(90deg)' : 'none', transition: 'transform .15s' }}
              />
            )}
          </span>
          <span style={{ fontSize: 14, color: active ? WB.primary : '#86868b', flex: '0 0 auto' }}>{SCOPE_ICON[node.scope]}</span>
          <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: active ? WB.primary : '#1d1d1f', fontWeight: active ? 600 : 400 }}>{node.name}</span>
          <span style={scopePillStyle}>{SCOPE_LABEL[node.scope]}</span>
        </div>
        {hasChildren && isOpen && node.children!.map((c) => renderNode(c, level + 1))}
      </div>
    );
  };
  return <div style={{ padding: '2px 0' }}>{nodes.map((n) => renderNode(n, 0))}</div>;
}

// ── 新建 / 重命名 模态（MacOS 风格） ─────────────────────────────────────

function NameModal(props: {
  state: NameModalState;
  setState: (updater: (m: NameModalState) => NameModalState) => void;
  composingRef: { current: boolean };
  loading: boolean;
  onOk: () => void;
}) {
  const { state, setState, composingRef, loading, onOk } = props;
  if (!state.open) return null;
  const META: Record<NameMode, { title: string; placeholder: string }> = {
    'create-folder': { title: '新建文件夹', placeholder: 'my-folder' },
    'rename-folder': { title: '重命名文件夹', placeholder: 'my-folder' },
    'rename-file': { title: '重命名本体', placeholder: 'ontology.md' },
  };
  const meta = META[state.mode];
  return (
    <div style={modalOverlayStyle} onClick={() => setState((m) => ({ ...m, open: false }))}>
      <div style={modalCardStyle} onClick={(e) => e.stopPropagation()}>
        <div style={{ padding: '14px 18px', fontSize: 13, fontWeight: 600, color: '#1d1d1f', borderBottom: `1px solid ${WB.border}` }}>{meta.title}</div>
        <div style={{ padding: '18px' }}>
          <Input
            autoFocus
            placeholder={meta.placeholder}
            value={state.value}
            onChange={(e) => setState((m) => ({ ...m, value: e.target.value }))}
            onCompositionStart={() => { composingRef.current = true; }}
            onCompositionEnd={(e) => { composingRef.current = false; setState((m) => ({ ...m, value: (e.target as HTMLInputElement).value })); }}
            onPressEnter={(e) => {
              if (composingRef.current || (e.nativeEvent as KeyboardEvent & { isComposing?: boolean }).isComposing) return;
              onOk();
            }}
            style={{ fontSize: 13 }}
            suffix={state.value ? <Typography.Text style={{ fontSize: 11, color: '#86868b' }}>→ {state.value}</Typography.Text> : null}
          />
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, padding: '0 18px 16px' }}>
          <button style={toolBtnStyle} onClick={() => setState((m) => ({ ...m, open: false }))}>取消</button>
          <button style={{ ...toolBtnStyle, background: WB.primary, color: '#fff', border: 'none' }} disabled={loading} onClick={onOk}>
            {loading ? '保存中…' : '保存'}
          </button>
        </div>
      </div>
    </div>
  );
}

function IconAction(props: { title: string; icon: ReactNode; onClick: () => void; danger?: boolean; disabled?: boolean }) {
  const { title, icon, onClick, danger, disabled } = props;
  const btn = (
    <button style={iconActionBtnStyle(danger, disabled)} disabled={disabled} onClick={onClick}>{icon}</button>
  );
  return <Tooltip title={title}>{btn}</Tooltip>;
}

// ── 共享样式 ─────────────────────────────────────────────────────────────

const titleBarStyle: CSSProperties = {
  height: 44, display: 'flex', alignItems: 'center', padding: '0 16px', gap: 8,
  borderBottom: `1px solid ${WB.border}`, flex: '0 0 auto', background: '#fbfbfd',
};

const sidebarStyle: CSSProperties = {
  flex: 2, minWidth: 188, maxWidth: 264, background: WB.sidebar,
  borderRight: `1px solid ${WB.border}`, overflowY: 'auto', padding: '8px 0',
};

const sidebarHeaderStyle: CSSProperties = {
  fontSize: 11, fontWeight: 600, color: '#86868b', letterSpacing: 0.4,
  textTransform: 'uppercase', padding: '6px 14px 4px',
};

const treeRowStyle = (active: boolean, level: number): CSSProperties => ({
  display: 'flex', alignItems: 'center', gap: 6, height: 30,
  margin: '1px 6px', padding: '0 8px', borderRadius: 6, cursor: 'pointer',
  fontSize: 13, lineHeight: 1, userSelect: 'none',
  paddingLeft: 8 + level * 16,
  background: active ? '#E8EAFE' : 'transparent',
  color: active ? WB.primary : '#1d1d1f',
  fontWeight: active ? 600 : 400,
});

const scopePillStyle: CSSProperties = {
  fontSize: 10, color: '#86868b', background: 'rgba(0,0,0,0.06)',
  padding: '1px 6px', borderRadius: 8, flex: '0 0 auto', lineHeight: '14px',
};

const toolbarStyle: CSSProperties = {
  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
  padding: '10px 16px', borderBottom: `1px solid ${WB.border}`, flex: '0 0 auto', gap: 8, flexWrap: 'wrap',
  background: '#fbfbfd',
};

const pathBarStyle: CSSProperties = {
  display: 'flex', alignItems: 'center', flex: 1, minWidth: 0, overflow: 'hidden',
  background: '#eef0f3', borderRadius: 6, padding: '4px 10px', height: 28,
  fontSize: 12, color: '#1d1d1f',
};

const pathSegStyle: CSSProperties = {
  cursor: 'pointer', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
  display: 'inline-flex', alignItems: 'center', borderRadius: 4, padding: '0 2px',
};

const navBtnStyle = (disabled: boolean): CSSProperties => ({
  width: 28, height: 28, borderRadius: 6, border: 'none', cursor: disabled ? 'not-allowed' : 'pointer',
  display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12,
  background: disabled ? 'transparent' : '#eef0f3', color: disabled ? '#c7c7cc' : '#1d1d1f',
  flex: '0 0 28px',
});

const toolBtnStyle: CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12, color: '#1d1d1f',
  background: '#eef0f3', border: 'none', cursor: 'pointer', padding: '5px 10px', borderRadius: 6,
  height: 28,
};

const iconCardStyle = (hover: boolean): CSSProperties => ({
  width: 108, padding: '10px 6px 8px', borderRadius: 8, cursor: 'default',
  display: 'flex', alignItems: 'flex-start', justifyContent: 'center',
  border: '1px solid transparent', transition: 'background .12s',
  background: hover ? '#f0f1f4' : 'transparent',
});

const iconNameStyle: CSSProperties = {
  marginTop: 6, fontSize: 12, color: '#1d1d1f', textAlign: 'center',
  overflow: 'hidden', textOverflow: 'ellipsis', display: '-webkit-box',
  WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', width: '100%', lineHeight: 1.3,
};

const iconActionBtnStyle = (danger?: boolean, disabled?: boolean): CSSProperties => ({
  width: 22, height: 22, borderRadius: 6, border: 'none',
  cursor: disabled ? 'not-allowed' : 'pointer',
  display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11,
  background: 'rgba(255,255,255,0.9)', boxShadow: '0 1px 3px rgba(0,0,0,0.18)',
  color: disabled ? '#d1d5db' : (danger ? '#ff3b30' : '#1d1d1f'),
});

const modalOverlayStyle: CSSProperties = {
  position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.3)', zIndex: 1000,
  display: 'flex', alignItems: 'center', justifyContent: 'center',
};

const modalCardStyle: CSSProperties = {
  width: 380, background: '#fff', borderRadius: 12,
  boxShadow: '0 12px 32px rgba(0,0,0,0.18)', overflow: 'hidden',
};
