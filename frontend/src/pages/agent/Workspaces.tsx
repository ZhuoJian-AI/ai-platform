import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import {
  Drawer, Upload, message, Tooltip, Typography, Button, Empty, Segmented, Spin, Tag,
} from 'antd';
import {
  DeleteOutlined, BankOutlined, ApartmentOutlined,
  TeamOutlined, UserOutlined, FolderOutlined, FileTextOutlined,
  FolderAddOutlined, ArrowUpOutlined, HomeOutlined, UploadOutlined,
  DownloadOutlined, EyeOutlined, CloseOutlined, ReloadOutlined,
} from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { workspaces } from '../../api/client';
import type { WorkspaceFile, WorkspaceFileListItem, WorkspaceFolder, WorkspaceTreeNode } from '../../api/client';
import { ApiError } from '../../api/client';
import OrgSelect from '../../components/OrgSelect';
import {
  FinderShell, TitleBar, Sidebar, MacTree, Toolbar, PathBar, NavButton, ToolButton,
  FinderGrid, IconCard, IconActionButton, IconName, FinderEmpty, FinderLoading,
  FinderPromptModal, type FinderTreeNode,
} from '../../components/finder/primitives';
import ConfirmModal from '../../components/finder/ConfirmModal';
import { WB, WB_FONT, FS } from '../../components/finder/theme';

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

const MAX_UPLOAD_BYTES = 5 * 1024 * 1024; // 单文件上传上限 5MB（内联文本存储）

const IMAGE_EXTS = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp', 'ico', 'avif']);

/** 取路径末段作为文件名。 */
function basename(p: string): string {
  return p.split('/').pop() || p;
}

/** 取路径扩展名（小写，无点返回空串）。 */
function extOf(p: string): string {
  const i = p.lastIndexOf('.');
  return i >= 0 ? p.slice(i + 1).toLowerCase() : '';
}

/** 把路径相对当前目录的前缀裁掉，返回相对段（无前缀时原样返回）。 */
function relPath(p: string, cwd: string[]): string {
  const prefix = cwd.length ? `${cwd.join('/')}/` : '';
  return prefix ? p.slice(prefix.length) : p;
}

/** 工作空间管理：随组织架构逐级嵌套的文件夹树（组织→部门→团队→用户），
 * 每个节点对应一个同名绑定工作空间，选中节点即以 Finder 网格浏览器管理其中的文件夹 / 文件。
 * 视觉对齐终端 WorkspaceManagerView（Mac Finder 风、紧凑字号梯、靛蓝配色、居中 ConfirmModal）。
 */
export default function Workspaces() {
  const qc = useQueryClient();
  const [orgId, setOrgId] = useState<string | undefined>();
  const [fileModalWs, setFileModalWs] = useState<{ id: string; name: string; path: string } | null>(null);
  const [selectedNodeKey, setSelectedNodeKey] = useState<string | null>(null);
  const [cwd, setCwd] = useState<string[]>([]); // 当前目录段数组，根为 []
  // 文件查看抽屉：可同时打开多个文件，抽屉顶部以紧凑 tab 条切换；活动文件即抽屉当前呈现者。
  const [openFiles, setOpenFiles] = useState<WorkspaceFile[]>([]);
  const [activeFileId, setActiveFileId] = useState<string | null>(null);
  const [folderModalOpen, setFolderModalOpen] = useState(false);
  const [folderName, setFolderName] = useState('');
  // IME 输入法合成态：合成中（拼音未上屏）时屏蔽 Enter 提交，避免「Enter 选词」误触发。
  const composingRef = useRef(false);

  const { data: tree, isLoading } = useQuery({
    queryKey: ['workspaceTree', orgId],
    queryFn: () => workspaces.tree(orgId),
    enabled: !!orgId,
  });

  const { data: files, isLoading: filesLoading } = useQuery({
    queryKey: ['workspace-files', fileModalWs?.id],
    queryFn: () => fileModalWs ? workspaces.listFiles(fileModalWs.id) : Promise.resolve([]),
    enabled: !!fileModalWs,
  });

  const { data: folders } = useQuery({
    queryKey: ['workspace-folders', fileModalWs?.id],
    queryFn: () => fileModalWs ? workspaces.listFolders(fileModalWs.id) : Promise.resolve([]),
    enabled: !!fileModalWs,
  });

  // 递归把后端组织树转为 Finder 树数据，同时建 key → 工作空间信息 的映射
  const { treeData, wsByKey } = useMemo(() => {
    const wsByKey = new Map<string, { id: string; name: string; path: string }>();
    const build = (nodes: WorkspaceTreeNode[], parentPath: string): FinderTreeNode[] =>
      nodes.map((n) => {
        const key = `${n.node_type}:${n.node_id}`;
        const path = parentPath ? `${parentPath} / ${n.name}` : n.name;
        if (n.workspace) wsByKey.set(key, { id: n.workspace.id, name: n.workspace.name, path });
        return {
          key,
          label: n.name,
          icon: NODE_ICON[n.node_type],
          pill: n.workspace ? (SCOPE_LABEL[n.node_type] ?? n.node_type) : '无工作空间',
          selectable: !!n.workspace,
          children: n.children?.length ? build(n.children, path) : undefined,
        };
      });
    return { treeData: build(tree ?? [], ''), wsByKey };
  }, [tree]);

  // 当前层级直系子项：显式文件夹 + 由文件 / 更深文件夹路径推导的隐式文件夹 + 直系文件。
  const { folderItems, fileItems } = useMemo(() => {
    const folderByName = new Map<string, WorkspaceFolder | null>();
    const addFolder = (name: string, rec: WorkspaceFolder | null) => {
      if (!folderByName.has(name)) folderByName.set(name, rec);
      else if (rec && !folderByName.get(name)) folderByName.set(name, rec); // 显式记录优先
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
      .map(([name, rec]) => ({ name, record: rec }))
      .sort((a, b) => a.name.localeCompare(b.name));
    directFiles.sort((a, b) => a.name.localeCompare(b.name));
    return { folderItems, fileItems: directFiles };
  }, [files, folders, cwd]);

  const uploadFile = useMutation({
    mutationFn: (v: { path: string; file: File }) => {
      if (!fileModalWs) return Promise.reject(new Error('no ws'));
      return workspaces.uploadFile(fileModalWs.id, v.file, v.path);
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['workspace-files'] }); message.success('文件已上传'); },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '上传失败'),
  });

  const reparseFile = useMutation({
    mutationFn: (id: string) => workspaces.reparseFile(id),
    onSuccess: (updated) => {
      setOpenFiles((items) => items.map((f) => f.id === updated.id ? updated : f));
      qc.invalidateQueries({ queryKey: ['workspace-files'] });
      if (updated.parse_status === 'ready') message.success('文件解析完成');
      else message.warning(updated.parse_error || '文件仍无法解析');
    },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '重新解析失败'),
  });

  /** 从鉴权下载端点取得原始二进制，兼容 OSS 与历史 Base64 文件。 */
  const downloadBinary = async (f: WorkspaceFile) => {
    try {
      const meta = (f.metadata ?? {}) as { mime?: string; name?: string };
      const blob = await workspaces.downloadFile(f.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = meta.name || basename(f.path);
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : '下载失败');
    }
  };

  const isBinary = (f: WorkspaceFile) => !!((f.metadata ?? {}) as { binary?: boolean }).binary;

  /** 把文本文件 content 作为 blob 下载（.doc/.html 等按 HTML，其余按纯文本）。 */
  const downloadText = (f: WorkspaceFile) => {
    try {
      const ext = extOf(f.path);
      const mime = ['html', 'htm', 'doc', 'docx'].includes(ext) ? 'text/html'
        : ext === 'md' ? 'text/markdown' : 'text/plain';
      const blob = new Blob([f.content ?? ''], { type: `${mime};charset=utf-8` });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = basename(f.path);
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
    } catch {
      message.error('下载失败');
    }
  };

  const delFile = useMutation({
    mutationFn: (id: string) => workspaces.deleteFile(id),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: ['workspace-files'] });
      setOpenFiles((prev) => prev.filter((x) => x.id !== id));
      setActiveFileId((cur) => (cur === id ? null : cur));
      message.success('文件已删除');
    },
    onError: () => message.error('删除失败'),
  });

  const createFolder = useMutation({
    mutationFn: (name: string) => {
      if (!fileModalWs) return Promise.reject(new Error('no ws'));
      const path = [...cwd, name].join('/');
      return workspaces.createFolder(fileModalWs.id, { path });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['workspace-folders'] });
      setFolderModalOpen(false); setFolderName('');
      message.success('文件夹已创建');
    },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '创建失败'),
  });

  const delFolder = useMutation({
    mutationFn: (id: string) => workspaces.deleteFolder(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['workspace-folders'] });
      qc.invalidateQueries({ queryKey: ['workspace-files'] });
      message.success('文件夹及其内容已删除');
    },
    onError: () => message.error('删除失败'),
  });

  const openWs = (ws: { id: string; name: string; path: string }) => {
    setFileModalWs(ws); setCwd([]); setOpenFiles([]); setActiveFileId(null);
  };

  /** 列表只含摘要；打开时按需拉取单文件正文。 */
  const openFile = async (item: WorkspaceFileListItem) => {
    if (openFiles.some((f) => f.id === item.id)) {
      setActiveFileId(item.id);
      return;
    }
    try {
      const file = await workspaces.getFile(item.id);
      setOpenFiles((prev) => (prev.some((f) => f.id === file.id) ? prev : [...prev, file]));
      setActiveFileId(file.id);
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : '文件读取失败');
    }
  };

  const downloadListFile = async (item: WorkspaceFileListItem) => {
    try {
      const file = await workspaces.getFile(item.id);
      if (isBinary(file)) await downloadBinary(file); else downloadText(file);
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : '下载失败');
    }
  };

  const closeFile = (id: string) => {
    setOpenFiles((prev) => prev.filter((x) => x.id !== id));
    setActiveFileId((cur) => {
      if (cur !== id) return cur;
      const remain = openFiles.filter((x) => x.id !== id);
      return remain[remain.length - 1]?.id ?? null;
    });
  };

  const submitFolder = () => {
    const name = folderName.trim();
    if (!name || name.includes('/')) { message.warning('请输入有效文件夹名（不含 /）'); return; }
    createFolder.mutate(name);
  };

  const activeFile = openFiles.find((f) => f.id === activeFileId) ?? null;

  // 删除确认：界面正中 ConfirmModal（不再用悬浮 Popconfirm）。
  const [confirm, setConfirm] = useState<{ kind: 'folder' | 'file'; id: string; title: string; desc?: string } | null>(null);
  const confirmLoading = confirm?.kind === 'folder' ? delFolder.isPending : confirm?.kind === 'file' ? delFile.isPending : false;
  const confirmOk = () => {
    if (!confirm) return;
    if (confirm.kind === 'folder') delFolder.mutate(confirm.id);
    else delFile.mutate(confirm.id);
    setConfirm(null);
  };

  return (
    <FinderShell style={{ height: 'calc(100vh - 64px)' }}>
      <TitleBar
        icon={<FolderOutlined />}
        title="工作空间"
        titleExtra={<OrgSelect value={orgId} onChange={(v) => { setOrgId(v); setSelectedNodeKey(null); setFileModalWs(null); setOpenFiles([]); setActiveFileId(null); }} />}
        extra={
          fileModalWs ? (
            <Typography.Text style={{ fontSize: FS.aux, color: WB.textAux }}>
              {fileModalWs.path}
            </Typography.Text>
          ) : null
        }
      />

      {/* 2:8 主体 */}
      <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
        {/* 左栏：组织架构树 */}
        <Sidebar header="组织架构">
          {(!tree || tree.length === 0) && !isLoading ? (
            <div style={{ padding: '8px 12px', color: WB.textAux, fontSize: FS.aux }}>
              {orgId ? '该组织下暂无工作空间节点' : '请先选择组织'}
            </div>
          ) : isLoading ? (
            <FinderLoading />
          ) : (
            <MacTree
              nodes={treeData}
              selectedKey={selectedNodeKey}
              onSelect={(key) => {
                setSelectedNodeKey(key);
                const ws = wsByKey.get(key);
                if (ws) openWs(ws);
              }}
            />
          )}
        </Sidebar>

        {/* 右栏：Finder 文件夹 / 文件浏览器 */}
        <section style={{ flex: 8, minWidth: 0, display: 'flex', flexDirection: 'column', background: '#fff' }}>
          {!fileModalWs ? (
            <FinderEmpty description="请从左侧选择工作空间节点" />
          ) : (
            <>
              {/* 工具条 + Mac 路径栏 */}
              <Toolbar
                left={
                  <>
                    <NavButton
                      icon={<ArrowUpOutlined style={{ transform: 'rotate(-90deg)' }} />}
                      disabled={cwd.length === 0}
                      onClick={() => setCwd((c) => c.slice(0, -1))}
                      title="返回上一级"
                    />
                    <PathBar
                      rootLabel={fileModalWs.name}
                      rootIcon={<HomeOutlined style={{ fontSize: 12 }} />}
                      segs={cwd}
                      onSeg={(i) => setCwd((c) => (i < 0 ? [] : c.slice(0, i + 1)))}
                    />
                  </>
                }
                right={
                  <>
                    <ToolButton icon={<FolderAddOutlined style={{ fontSize: 13 }} />} onClick={() => { setFolderName(''); setFolderModalOpen(true); }}>
                      新建文件夹
                    </ToolButton>
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
                      <ToolButton icon={<UploadOutlined style={{ fontSize: 13 }} />} disabled={uploadFile.isPending}>
                        上传文件
                      </ToolButton>
                    </Upload>
                  </>
                }
              />

              {/* 图标网格 */}
              <div style={{ flex: 1, overflowY: 'auto', padding: '18px 20px' }} className="wb-scroll-hide">
                {filesLoading ? (
                  <FinderLoading />
                ) : (folderItems.length === 0 && fileItems.length === 0) ? (
                  <div style={{ textAlign: 'center', color: WB.textAux, fontSize: FS.body, marginTop: 48 }}>
                    此处暂无文件夹 / 文件
                  </div>
                ) : (
                  <FinderGrid>
                    {folderItems.map((it) => {
                      const key = `d:${it.name}`;
                      return (
                        <IconCard
                          key={key}
                          onClick={() => setCwd((c) => [...c, it.name])}
                          actions={(hover) => (it.record && hover) ? (
                            <span
                              key="a"
                              style={{ position: 'absolute', top: -6, right: -6, zIndex: 2 }}
                              onClick={(e) => e.stopPropagation()}
                            >
                              <IconActionButton
                                icon={<DeleteOutlined />}
                                variant="danger"
                                onClick={() => setConfirm({
                                  kind: 'folder', id: it.record!.id,
                                  title: '删除该文件夹？',
                                  desc: '将一并删除其下所有子文件夹与文件',
                                })}
                              />
                            </span>
                          ) : null}
                        >
                          <FolderOutlined style={{ fontSize: 42, color: WB.macFolder }} />
                          <IconName>{it.name}</IconName>
                        </IconCard>
                      );
                    })}
                    {fileItems.map((it) => {
                      const key = `f:${it.file.id}`;
                      return (
                        <IconCard
                          key={key}
                          actions={(hover) => hover ? (
                            <span
                              key="a"
                              style={{ position: 'absolute', top: -6, right: -6, zIndex: 2, display: 'flex', gap: 4 }}
                              onClick={(e) => e.stopPropagation()}
                            >
                              <Tooltip title="查看文件">
                                <IconActionButton icon={<EyeOutlined />} onClick={() => { void openFile(it.file); }} />
                              </Tooltip>
                              <Tooltip title="下载">
                                <IconActionButton
                                  icon={<DownloadOutlined />}
                                  onClick={() => { void downloadListFile(it.file); }}
                                />
                              </Tooltip>
                              <IconActionButton
                                icon={<DeleteOutlined />}
                                variant="danger"
                                onClick={() => setConfirm({ kind: 'file', id: it.file.id, title: '删除该文件？' })}
                              />
                            </span>
                          ) : null}
                        >
                          <div onClick={() => { void openFile(it.file); }} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', cursor: 'pointer' }}>
                            <FileTextOutlined style={{ fontSize: 42, color: WB.macFile }} />
                            <IconName>{basename(it.file.path)}</IconName>
                            <span style={{ fontSize: 10, color: WB.textMicro, marginTop: 1 }}>{it.file.size} B</span>
                          </div>
                        </IconCard>
                      );
                    })}
                  </FinderGrid>
                )}
                {folderItems.length === 0 && fileItems.length === 0 && !filesLoading && (
                  <Typography.Text style={{ display: 'block', marginTop: 16, fontSize: FS.micro, color: WB.textMicro, textAlign: 'center' }}>
                    点击文件夹进入 · 点击文件查看 · 「上传文件」写入当前目录（同名覆盖）
                  </Typography.Text>
                )}
              </div>
            </>
          )}
        </section>
      </div>

      {/* 文件查看：右侧抽屉承载 FileViewer（md / html / pdf / img / 纯文本 / 下载全保留） */}
      <Drawer
        open={!!activeFileId}
        onClose={() => setActiveFileId(null)}
        width={720}
        rootStyle={{ fontFamily: WB_FONT }}
        styles={{ header: { borderBottom: `1px solid ${WB.border}` }, body: { padding: 0, display: 'flex', flexDirection: 'column' } }}
        title={activeFile ? basename(activeFile.path) : '文件查看'}
        extra={activeFile && (
          <ToolButton
            icon={<DownloadOutlined style={{ fontSize: 13 }} />}
            onClick={() => isBinary(activeFile) ? downloadBinary(activeFile) : downloadText(activeFile)}
          >下载</ToolButton>
        )}
      >
        {/* 多文件切换条（仅打开 >1 个文件时出现） */}
        {openFiles.length > 1 && (
          <div style={{ display: 'flex', gap: 4, padding: '8px 16px', borderBottom: `1px solid ${WB.border}`, overflowX: 'auto' }} className="wb-scroll-hide">
            {openFiles.map((f) => {
              const active = f.id === activeFileId;
              return (
                <span
                  key={f.id}
                  onClick={() => setActiveFileId(f.id)}
                  style={{
                    display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: FS.aux, cursor: 'pointer',
                    padding: '3px 8px', borderRadius: 6, whiteSpace: 'nowrap',
                    background: active ? WB.activeBg : 'transparent',
                    color: active ? WB.primary : WB.text,
                  }}
                >
                  <FileTextOutlined style={{ fontSize: 11 }} />{basename(f.path)}
                  <CloseOutlined
                    onClick={(e) => { e.stopPropagation(); closeFile(f.id); }}
                    style={{ fontSize: 10, color: WB.textAux }}
                  />
                </span>
              );
            })}
          </div>
        )}
        <div style={{ flex: 1, minHeight: 0 }}>
          {activeFile && (
            <FileViewer
              file={activeFile}
              onDownload={() => isBinary(activeFile) ? downloadBinary(activeFile) : downloadText(activeFile)}
              onReparse={() => reparseFile.mutate(activeFile.id)}
              reparsing={reparseFile.isPending}
            />
          )}
        </div>
      </Drawer>

      {/* 新建文件夹：MacOS 风格弹窗 */}
      <FinderPromptModal
        open={folderModalOpen}
        title="新建文件夹"
        placeholder="文件夹名"
        value={folderName}
        setValue={setFolderName}
        suffix={folderName ? <Typography.Text style={{ fontSize: FS.micro, color: WB.textAux }}>→ {[...cwd, folderName].join('/')}</Typography.Text> : null}
        composingRef={composingRef}
        loading={createFolder.isPending}
        onCancel={() => { setFolderModalOpen(false); setFolderName(''); }}
        onOk={submitFolder}
      />

      {/* 删除确认：界面正中模态（字体随根容器继承终端 WB_FONT） */}
      <ConfirmModal
        open={!!confirm}
        title={confirm?.title ?? ''}
        desc={confirm?.desc}
        loading={confirmLoading}
        onCancel={() => setConfirm(null)}
        onOk={confirmOk}
      />
    </FinderShell>
  );
}

/** 文件查看器：按文本 / 二进制分类直接呈现内容。
 *  - 二进制图片：data URL 内嵌 <img>；二进制 PDF：data URL 内嵌 <iframe>；其它二进制：仅提供下载。
 *  - 文本：Markdown 用 react-markdown 渲染；HTML（含 .doc/.docx 存为 HTML）用 iframe srcDoc；其余纯文本用 <pre>。
 */
function FileViewer({ file, onDownload, onReparse, reparsing }: {
  file: WorkspaceFile; onDownload: () => void; onReparse: () => void; reparsing: boolean;
}) {
  const meta = (file.metadata ?? {}) as { binary?: boolean; mime?: string; name?: string };
  const ext = extOf(file.path);
  const content = file.content ?? '';
  const [view, setView] = useState<'original' | 'ai'>('original');
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewType, setPreviewType] = useState('application/pdf');
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  useEffect(() => {
    setView('original');
    setPreviewUrl(null);
    setPreviewError(null);
    if (!meta.binary) return;
    let cancelled = false;
    let objectUrl: string | null = null;
    setPreviewLoading(true);
    workspaces.getFileOriginalPreview(file.id)
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setPreviewType(blob.type || 'application/pdf');
        setPreviewUrl(objectUrl);
      })
      .catch((error) => { if (!cancelled) setPreviewError((error as Error)?.message || '原文件预览加载失败'); })
      .finally(() => { if (!cancelled) setPreviewLoading(false); });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [file.id, meta.binary]);

  // 二进制文件
  if (meta.binary) {
    const hasAiContent = file.parse_status === 'ready' && !!file.extracted_text;
    return (
      <div style={{ height: '100%', minHeight: 0, display: 'flex', flexDirection: 'column' }}>
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12,
          padding: '8px 14px', borderBottom: `1px solid ${WB.border}`, background: '#FAFAFB',
        }}>
          <Segmented size="small" value={view} onChange={(value) => setView(value as 'original' | 'ai')}
            options={[
              { label: '原文件预览', value: 'original' },
              { label: 'AI 解析内容', value: 'ai', disabled: !hasAiContent },
            ]} />
          <div><Tag color="blue">原文件</Tag>{hasAiContent && <Tag color="green">AI 已解析</Tag>}</div>
        </div>
        <div style={{ flex: 1, minHeight: 0 }}>
          {view === 'original' && (
            previewLoading ? <div style={viewerCenter}><Spin tip="正在生成原文件预览…" /></div>
              : previewUrl ? (
                previewType.startsWith('image/')
                  ? <div style={viewerCenter}><img src={previewUrl} alt={file.path} style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }} /></div>
                  : <iframe title="原文件预览" src={previewUrl} style={{ width: '100%', height: '100%', border: 'none' }} />
              ) : (
                <div style={viewerCenter}>
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={previewError || '原文件预览暂不可用，可下载后查看'} />
                  <Button icon={<DownloadOutlined />} onClick={onDownload}>下载原文件</Button>
                </div>
              )
          )}
          {view === 'ai' && hasAiContent && (
            <div style={{ height: '100%', overflowY: 'auto', padding: '16px 20px' }}>
              <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 12, fontSize: FS.aux }}>
                这是提供给 AI 检索和分析的结构化文本，不代表原文件排版。
              </Typography.Text>
              <div className="wb-md"><ReactMarkdown remarkPlugins={[remarkGfm]}>{file.extracted_text}</ReactMarkdown></div>
            </div>
          )}
          {view === 'ai' && !hasAiContent && (
            <div style={viewerCenter}>
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={file.parse_error || '该文件尚未生成 AI 可读内容'} />
              <Button icon={<ReloadOutlined />} onClick={onReparse} loading={reparsing}>重新解析</Button>
            </div>
          )}
        </div>
      </div>
    );
  }

  // 文本类
  if (ext === 'md' || ext === 'markdown') {
    return (
      <div className="wb-md" style={{ height: '100%', overflowY: 'auto', padding: '16px 20px' }}>
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
      </div>
    );
  }
  if (['html', 'htm', 'doc', 'docx'].includes(ext) && /^\s*</.test(content.trim())) {
    return <iframe title="html" srcDoc={content} style={{ width: '100%', height: '100%', border: 'none' }} sandbox="allow-same-origin allow-popups" />;
  }
  if (IMAGE_EXTS.has(ext)) {
    // 非二进制图片（如以文本存储的 SVG）以 srcDoc 内嵌呈现
    return <iframe title="img" srcDoc={content} style={{ width: '100%', height: '100%', border: 'none' }} />;
  }
  return (
    <div style={{ height: '100%', overflow: 'auto', padding: '12px 16px', background: '#fafafa' }}>
      <pre className="wb-pre" style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{content}</pre>
    </div>
  );
}

const viewerCenter: CSSProperties = {
  height: '100%',
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  justifyContent: 'center',
  gap: 8,
  padding: 16,
  background: '#fafafa',
};
