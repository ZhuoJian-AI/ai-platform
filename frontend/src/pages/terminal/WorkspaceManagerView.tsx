import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import {
  Input, Typography, Upload, message, Empty, Tooltip, Spin,
} from 'antd';
import {
  DeleteOutlined, BankOutlined, ApartmentOutlined, TeamOutlined, UserOutlined,
  FolderOutlined, FileTextOutlined, FolderAddOutlined, ArrowUpOutlined,
  HomeOutlined, UploadOutlined, EyeOutlined, RightOutlined,
} from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  terminal, type Workspace, type WorkspaceFileListItem, type WorkspaceFolder, type TerminalResources,
} from '../../api/client';
import { ApiError } from '../../api/client';
import BrowserDrawer, { classifyFile, classifyUrl, type Source } from './BrowserDrawer';
import ConfirmModal from '../../components/finder/ConfirmModal';
// extOf 已由 classifyFile 内部使用，此处不再直接引用

/** WorkBuddy 配色（与 Terminal.tsx 保持一致）。 */
const WB = {
  primary: '#6366F1', primaryHover: '#818CF8',
  sidebar: '#F5F5F7', hover: '#ECECEF', border: '#E5E7EB',
  macFolder: '#5AC8FA', macFile: '#6366F1',
};

/** 统一字体栈：与终端 Terminal.tsx 完全一致，根容器设置后所有子文本继承。 */
const WB_FONT = '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif';

const SCOPE_ORDER = ['organization', 'department', 'team', 'user'] as const;
const SCOPE_LABEL: Record<string, string> = {
  organization: '组织', department: '部门', team: '团队', user: '个人',
};
const SCOPE_ICON: Record<string, ReactNode> = {
  organization: <BankOutlined />, department: <ApartmentOutlined />, team: <TeamOutlined />, user: <UserOutlined />,
};

const MAX_UPLOAD_BYTES = 5 * 1024 * 1024; // 单文件上传上限 5MB（内联文本存储）

interface TreeNode {
  key: string;
  name: string;
  scope: string;
  wsId: string;
  children?: TreeNode[];
}

/** 把用户可见的扁平工作空间列表（各 scope 级至多一个）组织成「组织→部门→团队→个人」的单链树。 */
function buildTree(workspaces: Workspace[]): { treeData: TreeNode[]; wsById: Map<string, Workspace> } {
  const wsById = new Map<string, Workspace>();
  for (const w of workspaces) wsById.set(w.id, w);
  const byScope = new Map<string, Workspace>();
  for (const w of workspaces) if (!byScope.has(w.scope_type)) byScope.set(w.scope_type, w);
  const present = SCOPE_ORDER.filter((s) => byScope.has(s));
  let child: TreeNode | null = null;
  for (let i = present.length - 1; i >= 0; i--) {
    const s = present[i];
    const w = byScope.get(s)!;
    const node: TreeNode = {
      key: `ws:${w.id}`,
      name: w.name,
      scope: s,
      wsId: w.id,
      children: child ? [child] : undefined,
    };
    child = node;
  }
  return { treeData: child ? [child] : [], wsById };
}

/** 把路径相对当前目录的前缀裁掉，返回相对段（无前缀时原样返回）。 */
function relPath(p: string, cwd: string[]): string {
  const prefix = cwd.length ? `${cwd.join('/')}/` : '';
  return prefix ? p.slice(prefix.length) : p;
}

/** 文件扩展名（小写、无点）。 */
function fileName(path: string): string {
  return path.split('/').pop() || path;
}

/** 工作空间管理视图：MacOS Finder 风格。
 *  左栏（2:8）为用户权限可见的工作空间树（组织→部门→团队→个人，逐级嵌套）；
 *  右栏为选中工作空间的文件夹 / 文件图标浏览器。
 *  全部字体沿用终端 WB_FONT，字号与终端一致（标题 14 / 主文本 13 / 辅助 12 / 微 11）。 */
export default function WorkspaceManagerView({ resources }: { resources: TerminalResources | undefined }) {
  const qc = useQueryClient();
  const workspaces = resources?.workspaces ?? [];
  const { treeData, wsById } = useMemo(() => buildTree(workspaces), [workspaces]);

  // 默认选中用户个人工作空间（或 defaults.workspace_id，或首个可见工作空间）
  const defaultWsId = resources?.defaults?.workspace_id
    ?? workspaces.find((w) => w.scope_type === 'user')?.id
    ?? workspaces[0]?.id
    ?? null;
  const [selectedWsId, setSelectedWsId] = useState<string | null>(null);
  useEffect(() => {
    if (selectedWsId === null && defaultWsId) setSelectedWsId(defaultWsId);
  }, [defaultWsId, selectedWsId]);
  const selectedWs = selectedWsId ? wsById.get(selectedWsId) ?? null : null;

  const [cwd, setCwd] = useState<string[]>([]); // 当前目录段数组，根为 []
  const [folderModalOpen, setFolderModalOpen] = useState(false);
  const [folderName, setFolderName] = useState('');
  const [hovered, setHovered] = useState<string | null>(null);
  const composingRef = useRef(false);

  // 浏览器抽屉：点击文件后右侧弹出，复用 BrowserDrawer
  const [browserOpen, setBrowserOpen] = useState(false);
  const [browserHref, setBrowserHref] = useState<string | null>(null);
  const [browserSeq, setBrowserSeq] = useState(0);

  const wsId = selectedWs?.id ?? null;
  const { data: files, isLoading: filesLoading } = useQuery({
    queryKey: ['ws-mgr-files', wsId],
    queryFn: () => wsId ? terminal.listWsFiles(wsId) : Promise.resolve([]),
    enabled: !!wsId,
  });
  const { data: folders } = useQuery({
    queryKey: ['ws-mgr-folders', wsId],
    queryFn: () => wsId ? terminal.listWsFolders(wsId) : Promise.resolve([]),
    enabled: !!wsId,
  });

  // 切换工作空间时回到根目录
  useEffect(() => { setCwd([]); }, [wsId]);

  // 当前层级直系子项：显式文件夹 + 由文件 / 更深文件夹路径推导的隐式文件夹 + 直系文件。
  const { folderItems, fileItems } = useMemo(() => {
    const folderByName = new Map<string, WorkspaceFolder | null>();
    const addFolder = (name: string, rec: WorkspaceFolder | null) => {
      if (!folderByName.has(name)) folderByName.set(name, rec);
      else if (rec && !folderByName.get(name)) folderByName.set(name, rec);
    };
    for (const f of folders ?? []) {
      const r = relPath(f.path, cwd);
      if (!r) continue;
      if (r.includes('/')) addFolder(r.split('/')[0], null);
      else addFolder(r, f);
    }
    const directFiles: { file: WorkspaceFileListItem; name: string }[] = [];
    for (const f of files ?? []) {
      const r = relPath(f.path, cwd);
      if (!r) continue;
      if (r.includes('/')) addFolder(r.split('/')[0], null);
      else directFiles.push({ file: f, name: r });
    }
    const folderItems = [...folderByName.entries()]
      .map(([name, record]) => ({ name, record }))
      .sort((a, b) => a.name.localeCompare(b.name));
    directFiles.sort((a, b) => a.name.localeCompare(b.name));
    return { folderItems, fileItems: directFiles };
  }, [files, folders, cwd]);

  const createFolder = useMutation({
    mutationFn: (name: string) => {
      if (!wsId) return Promise.reject(new Error('no ws'));
      return terminal.createWsFolder(wsId, { path: [...cwd, name].join('/') });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['ws-mgr-folders'] });
      setFolderModalOpen(false); setFolderName('');
      message.success('文件夹已创建');
    },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '创建失败'),
  });

  const delFolder = useMutation({
    mutationFn: (id: string) => terminal.deleteWsFolder(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['ws-mgr-folders'] });
      qc.invalidateQueries({ queryKey: ['ws-mgr-files'] });
      message.success('文件夹及其内容已删除');
    },
    onError: () => message.error('删除失败'),
  });

  const uploadFile = useMutation({
    mutationFn: (v: { path: string; file: File }) => {
      if (!wsId) return Promise.reject(new Error('no ws'));
      return terminal.uploadWsFile(wsId, v.file, v.path);
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['ws-mgr-files'] }); message.success('文件已上传'); },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '上传失败'),
  });

  const reparseFile = async (fileId: string) => {
    const updated = await terminal.reparseWsFile(fileId);
    await qc.invalidateQueries({ queryKey: ['ws-mgr-files'] });
    if (updated.parse_status === 'ready') message.success('文件解析完成');
    else message.warning(updated.parse_error || '文件仍无法解析');
  };

  const delFile = useMutation({
    mutationFn: (id: string) => terminal.deleteWsFile(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['ws-mgr-files'] }); message.success('文件已删除'); },
    onError: () => message.error('删除失败'),
  });

  // 删除确认弹窗：不再用悬浮 Popconfirm，改为界面正中的模态框（字体与终端一致）。
  const [confirm, setConfirm] = useState<{ kind: 'folder' | 'file'; id: string; title: string; desc?: string } | null>(null);
  const confirmLoading = confirm?.kind === 'folder' ? delFolder.isPending : confirm?.kind === 'file' ? delFile.isPending : false;
  const confirmOk = () => {
    if (!confirm) return;
    if (confirm.kind === 'folder') delFolder.mutate(confirm.id);
    else delFile.mutate(confirm.id);
    setConfirm(null);
  };

  // 把任意 href（http URL 或当前工作空间文件路径）解析为浏览器抽屉可渲染的 Source。
  const resolveHref = useCallback(async (rawHref: string): Promise<Source> => {
    if (/^https?:\/\//i.test(rawHref)) return classifyUrl(rawHref);
    // react-markdown 会把含非 ASCII 的链接目标 percent-encode，工作空间路径需先解码再匹配
    let href = rawHref;
    try { href = decodeURIComponent(rawHref); } catch { /* 非法转义，保留原值 */ }
    if (!wsId) return { kind: 'unsupported', href, note: '未选择工作空间' };
    let list: WorkspaceFileListItem[];
    try { list = await terminal.listWsFiles(wsId); }
    catch { return { kind: 'unsupported', href, note: '工作空间文件读取失败' }; }
    const f = list.find((x) => x.path === href || x.path.endsWith('/' + href) || href.endsWith(x.path));
    if (!f) return { kind: 'unsupported', href, note: `未找到该文件：${href}` };
    try { return classifyFile(await terminal.getWsFile(f.id)); }
    catch { return { kind: 'unsupported', href, note: '文件详情读取失败' }; }
  }, [wsId]);

  const openFile = (path: string) => {
    setBrowserHref(path);
    setBrowserSeq((n) => n + 1);
    setBrowserOpen(true);
  };

  const submitFolder = () => {
    const name = folderName.trim();
    if (!name || name.includes('/')) { message.warning('请输入有效文件夹名（不含 /）'); return; }
    createFolder.mutate(name);
  };

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, fontFamily: WB_FONT, background: '#fff' }}>
      {/* 顶部标题栏 */}
      <div style={titleBarStyle}>
        <FolderOutlined style={{ color: WB.primary, fontSize: 16 }} />
        <span style={{ fontSize: 13, fontWeight: 600, color: '#1d1d1f' }}>工作空间</span>
        <Typography.Text style={{ fontSize: 12, color: '#86868b' }}>
          {selectedWs ? `${selectedWs.name}` : '选择左侧节点'}
        </Typography.Text>
      </div>

      {/* 2:8 主体 */}
      <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
        {/* 左栏：MacOS 风格工作空间树 */}
        <aside style={sidebarStyle}>
          <div style={sidebarHeaderStyle}>收藏</div>
          {treeData.length === 0 ? (
            <div style={{ padding: '8px 12px', color: '#86868b', fontSize: 12 }}>暂无可访问的工作空间</div>
          ) : (
            <MacTree
              nodes={treeData}
              selectedKey={selectedWsId ? `ws:${selectedWsId}` : null}
              onSelect={(wsIdSel) => setSelectedWsId(wsIdSel)}
            />
          )}
        </aside>

        {/* 右栏：MacOS Finder 风格文件夹 / 文件浏览器 */}
        <section style={{ flex: 8, minWidth: 0, display: 'flex', flexDirection: 'column', background: '#fff' }}>
          {!selectedWs ? (
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="选择左侧工作空间节点以管理其文件夹 / 文件" />
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
                      <HomeOutlined style={{ fontSize: 12, marginRight: 4 }} />{selectedWs.name}
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
                  <button style={toolBtnStyle} onClick={() => { setFolderName(''); setFolderModalOpen(true); }}>
                    <FolderAddOutlined style={{ fontSize: 13 }} /> 新建文件夹
                  </button>
                  <Upload
                    showUploadList={false}
                    beforeUpload={(file) => {
                      if (file.size > MAX_UPLOAD_BYTES) {
                        message.warning(`文件过大（> ${MAX_UPLOAD_BYTES / 1024 / 1024}MB），请选择更小的文件`);
                        return Upload.LIST_IGNORE;
                      }
                      uploadFile.mutate({ path: [...cwd, file.name].join('/'), file: file as File });
                      return false;
                    }}
                  >
                    <button style={toolBtnStyle} disabled={uploadFile.isPending}>
                      <UploadOutlined style={{ fontSize: 13 }} /> 上传文件
                    </button>
                  </Upload>
                </div>
              </div>

              {/* 图标网格 */}
              <div style={{ flex: 1, overflowY: 'auto', padding: '18px 20px' }} className="wb-scroll-hide">
                {filesLoading ? (
                  <div style={{ display: 'flex', justifyContent: 'center', padding: 48 }}><Spin /></div>
                ) : (folderItems.length === 0 && fileItems.length === 0) ? (
                  <div style={{ textAlign: 'center', color: '#86868b', fontSize: 13, marginTop: 48 }}>
                    此处暂无文件夹 / 文件
                  </div>
                ) : (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                    {folderItems.map((it) => {
                      const key = `d:${it.name}`;
                      const isHover = hovered === key;
                      return (
                        <div
                          key={key}
                          onMouseEnter={() => setHovered(key)}
                          onMouseLeave={() => setHovered(null)}
                          onClick={() => setCwd((c) => [...c, it.name])}
                          style={iconCardStyle(isHover)}
                        >
                          <div style={{ position: 'relative', display: 'flex', flexDirection: 'column', alignItems: 'center', width: 92, cursor: 'pointer' }}>
                            {it.record && isHover && (
                              <span
                                style={{ position: 'absolute', top: -6, right: -6, zIndex: 2 }}
                                onClick={(e) => e.stopPropagation()}
                              >
                                <button
                                  style={iconActionBtnStyle('danger')}
                                  onClick={() => setConfirm({
                                    kind: 'folder', id: it.record!.id,
                                    title: '删除该文件夹？',
                                    desc: '将一并删除其下所有子文件夹与文件',
                                  })}
                                ><DeleteOutlined /></button>
                              </span>
                            )}
                            <FolderOutlined style={{ fontSize: 42, color: WB.macFolder }} />
                            <div style={iconNameStyle}>{it.name}</div>
                          </div>
                        </div>
                      );
                    })}
                    {fileItems.map((it) => {
                      const key = `f:${it.file.id}`;
                      const isHover = hovered === key;
                      return (
                        <div
                          key={key}
                          onMouseEnter={() => setHovered(key)}
                          onMouseLeave={() => setHovered(null)}
                          style={iconCardStyle(isHover)}
                        >
                          <div style={{ position: 'relative', display: 'flex', flexDirection: 'column', alignItems: 'center', width: 92 }}>
                            {isHover && (
                              <span style={{ position: 'absolute', top: -6, right: -6, zIndex: 2, display: 'flex', gap: 4 }}>
                                <Tooltip title="查看文件">
                                  <button style={iconActionBtnStyle('default')} onClick={() => openFile(it.file.path)}>
                                    <EyeOutlined />
                                  </button>
                                </Tooltip>
                                <button
                                  style={iconActionBtnStyle('danger')}
                                  onClick={() => setConfirm({ kind: 'file', id: it.file.id, title: '删除该文件？' })}
                                ><DeleteOutlined /></button>
                              </span>
                            )}
                            <div onClick={() => openFile(it.file.path)} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', cursor: 'pointer' }}>
                              <FileTextOutlined style={{ fontSize: 42, color: WB.macFile }} />
                              <div style={iconNameStyle}>{fileName(it.file.path)}</div>
                              <span style={{ fontSize: 10, color: '#aeaeb2', marginTop: 1 }}>{it.file.size} B</span>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
                {folderItems.length === 0 && fileItems.length === 0 && !filesLoading && (
                  <Typography.Text style={{ display: 'block', marginTop: 16, fontSize: 11, color: '#aeaeb2', textAlign: 'center' }}>
                    点击文件夹进入 · 点击文件查看 · 「上传文件」写入当前目录（同名覆盖）
                  </Typography.Text>
                )}
              </div>
            </>
          )}
        </section>
      </div>

      {/* 查看文件：复用任务消息区右侧浏览器抽屉 */}
      <BrowserDrawer
        key={browserSeq}
        open={browserOpen}
        initialHref={browserHref}
        onClose={() => setBrowserOpen(false)}
        resolveHref={resolveHref}
        onReparse={reparseFile}
      />

      {/* 新建文件夹 */}
      <NewFolderModal
        open={folderModalOpen}
        value={folderName}
        setValue={setFolderName}
        cwd={cwd}
        composingRef={composingRef}
        loading={createFolder.isPending}
        onCancel={() => { setFolderModalOpen(false); setFolderName(''); }}
        onOk={submitFolder}
      />

      {/* 删除确认：界面正中模态框（字体随根容器继承终端 WB_FONT） */}
      <ConfirmModal
        open={!!confirm}
        title={confirm?.title ?? ''}
        desc={confirm?.desc}
        loading={confirmLoading}
        onCancel={() => setConfirm(null)}
        onOk={confirmOk}
      />
    </div>
  );
}

// ── MacOS 风格工作空间树（Finder 侧栏） ──────────────────────────────────

function MacTree({ nodes, selectedKey, onSelect }: {
  nodes: TreeNode[];
  selectedKey: string | null;
  onSelect: (wsId: string) => void;
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
          onClick={() => onSelect(node.wsId)}
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

// ── 新建文件夹弹窗（MacOS 风格） ─────────────────────────────────────────

function NewFolderModal(props: {
  open: boolean; value: string; setValue: (v: string) => void; cwd: string[];
  composingRef: { current: boolean }; loading: boolean;
  onCancel: () => void; onOk: () => void;
}) {
  const { open, value, setValue, cwd, composingRef, loading, onCancel, onOk } = props;
  if (!open) return null;
  return (
    <div style={modalOverlayStyle} onClick={onCancel}>
      <div style={modalCardStyle} onClick={(e) => e.stopPropagation()}>
        <div style={{ padding: '14px 18px', fontSize: 13, fontWeight: 600, color: '#1d1d1f', borderBottom: `1px solid ${WB.border}` }}>新建文件夹</div>
        <div style={{ padding: '18px' }}>
          <Input
            autoFocus
            placeholder="文件夹名"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onCompositionStart={() => { composingRef.current = true; }}
            onCompositionEnd={(e) => { composingRef.current = false; setValue((e.target as HTMLInputElement).value); }}
            onPressEnter={(e) => {
              if (composingRef.current || (e.nativeEvent as KeyboardEvent & { isComposing?: boolean }).isComposing) return;
              onOk();
            }}
            style={{ fontSize: 13 }}
            suffix={value ? <Typography.Text style={{ fontSize: 11, color: '#86868b' }}>→ {[...cwd, value].join('/')}</Typography.Text> : null}
          />
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, padding: '0 18px 16px' }}>
          <button style={toolBtnStyle} onClick={onCancel}>取消</button>
          <button style={{ ...toolBtnStyle, background: WB.primary, color: '#fff', border: 'none' }} disabled={loading} onClick={onOk}>
            {loading ? '创建中…' : '创建'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── 删除确认弹窗改用共享 ConfirmModal（见 ./ConfirmModal） ──────────────

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

const iconActionBtnStyle = (variant: 'default' | 'danger'): CSSProperties => ({
  width: 22, height: 22, borderRadius: 6, border: 'none', cursor: 'pointer',
  display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11,
  background: 'rgba(255,255,255,0.9)', boxShadow: '0 1px 3px rgba(0,0,0,0.18)',
  color: variant === 'danger' ? '#ff3b30' : '#1d1d1f',
});

const modalOverlayStyle: CSSProperties = {
  position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.3)', zIndex: 1000,
  display: 'flex', alignItems: 'center', justifyContent: 'center',
};

const modalCardStyle: CSSProperties = {
  width: 380, background: '#fff', borderRadius: 12,
  boxShadow: '0 12px 32px rgba(0,0,0,0.18)', overflow: 'hidden',
};
