import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import {
  message, Typography,
  Input, Select, Checkbox, Modal, List, Dropdown,
} from 'antd';
import {
  DeleteOutlined, BankOutlined, ApartmentOutlined,
  TeamOutlined, UserOutlined, FolderOutlined, FileTextOutlined,
  FolderAddOutlined, ArrowUpOutlined, HomeOutlined, UploadOutlined,
  DownloadOutlined, EyeOutlined,
  AppstoreOutlined, UnorderedListOutlined, SearchOutlined, CheckSquareOutlined,
  HistoryOutlined, RestOutlined, AuditOutlined, MoreOutlined,
  LinkOutlined,
} from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import { workspaces, WORKSPACE_MAX_FILE_BYTES } from '../../api/client';
import type {
  WorkspaceAuditEvent, WorkspaceFile, WorkspaceFileListItem, WorkspaceFileVersion,
  WorkspaceFolder, WorkspaceTreeNode,
} from '../../api/client';
import { ApiError } from '../../api/client';
import OrgSelect from '../../components/OrgSelect';
import {
  FinderShell, TitleBar, Sidebar, MacTree, Toolbar, PathBar, NavButton, ToolButton,
  FinderEmpty, FinderLoading,
  FinderPromptModal, type FinderTreeNode,
} from '../../components/finder/primitives';
import ConfirmModal from '../../components/finder/ConfirmModal';
import { WB, FS } from '../../components/finder/theme';
import {
  useWorkspaceUploadQueue, WorkspaceUploadPicker, WorkspaceUploadQueueStatus,
  workspaceUploadErrorText, type WorkspaceUploadRequest,
} from '../../components/files/WorkspaceUploadQueue';
import { auditSummary, auditTitle, workspaceDisplayName, workspaceVisiblePath } from '../../utils/workspacePresentation';
import { workspaceInternalUrl } from '../../utils/workspaceFileLinks';
import BrowserDrawer, { classifyFile, classifyUrl, type Source } from '../terminal/BrowserDrawer';

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

/** 取路径末段作为文件名。 */
function basename(p: string): string {
  return p.split('/').pop() || p;
}

/** 取路径扩展名（小写，无点返回空串）。 */
function extOf(p: string): string {
  const i = p.lastIndexOf('.');
  return i >= 0 ? p.slice(i + 1).toLowerCase() : '';
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function fileType(path: string): string {
  const ext = extOf(path);
  return ext ? ext.toUpperCase() : '文件';
}

const PARSE_LABEL: Record<string, string> = {
  queued: '等待解析', processing: '解析中', ready: '可使用', failed: '解析失败',
  unsupported: '不支持解析', unparsed: '未解析',
};

/** 工作空间管理：随组织架构逐级嵌套的文件夹树（组织→部门→团队→用户），
 * 每个节点对应一个同名绑定工作空间，选中节点即以 Finder 网格浏览器管理其中的文件夹 / 文件。
 * 视觉对齐终端 WorkspaceManagerView（Mac Finder 风、紧凑字号梯、靛蓝配色、居中 ConfirmModal）。
 */
export default function Workspaces() {
  const qc = useQueryClient();
  const [urlParams, setUrlParams] = useSearchParams();
  const linkedWorkspaceId = urlParams.get('workspace');
  const linkedFileId = urlParams.get('file');
  const linkedVersionId = urlParams.get('version');
  const trashRestoreAttemptRef = useRef(new Map<string, string>());
  const [orgId, setOrgId] = useState<string | undefined>();
  const [fileModalWs, setFileModalWs] = useState<{ id: string; name: string; path: string } | null>(null);
  const [selectedNodeKey, setSelectedNodeKey] = useState<string | null>(null);
  const [cwd, setCwd] = useState<string[]>([]); // 当前目录段数组，根为 []
  // 文件查看抽屉：可同时打开多个文件，抽屉顶部以紧凑 tab 条切换；活动文件即抽屉当前呈现者。
  const [activeFileId, setActiveFileId] = useState<string | null>(null);
  const [activeFileVersionId, setActiveFileVersionId] = useState<string | null>(null);
  const [folderModalOpen, setFolderModalOpen] = useState(false);
  const [folderName, setFolderName] = useState('');
  const [hovered, setHovered] = useState<string | null>(null);
  const [focused, setFocused] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [sortBy, setSortBy] = useState<'name' | 'time' | 'type' | 'size'>('name');
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');
  const [selecting, setSelecting] = useState(false);
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());
  const fileAreaRef = useRef<HTMLDivElement>(null);
  const dragSelectionRef = useRef<{
    pointerId: number; startX: number; startY: number; baseSelection: Set<string>;
  } | null>(null);
  const [marquee, setMarquee] = useState<{ left: number; top: number; width: number; height: number } | null>(null);
  const [trashOpen, setTrashOpen] = useState(false);
  const [auditOpen, setAuditOpen] = useState(false);
  const [versionFile, setVersionFile] = useState<WorkspaceFileListItem | null>(null);
  const restoreAttemptRef = useRef<{ fingerprint: string; key: string } | null>(null);
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

  // 稳定 /f/:id 地址鉴权完成后会进入本页面；这里再次按管理员身份校验
  // workspace、file 和历史版本的一致性，再在正常工作空间壳层打开统一抽屉。
  useEffect(() => {
    if (!linkedWorkspaceId || !linkedFileId) return;
    let disposed = false;
    const resolve = async () => {
      const [workspace, file] = await Promise.all([
        workspaces.get(linkedWorkspaceId),
        workspaces.getFile(linkedFileId),
        linkedVersionId ? workspaces.getFileVersion(linkedFileId, linkedVersionId) : Promise.resolve(null),
      ]);
      if (file.workspace_id !== workspace.id) throw new Error('workspace mismatch');
      if (disposed) return;
      setOrgId(workspace.organization_id);
      setFileModalWs((current) => current?.id === workspace.id
        ? current
        : { id: workspace.id, name: workspace.name, path: workspace.name });
      setActiveFileId(file.id);
      setActiveFileVersionId(linkedVersionId);
    };
    void resolve().catch(() => {
      if (!disposed) message.error('文件不存在或没有查看权限');
    });
    return () => { disposed = true; };
  }, [linkedFileId, linkedVersionId, linkedWorkspaceId]);

  // 组织树加载后补齐真实层级路径和左侧选中态；文件地址本身始终只依赖稳定 ID。
  useEffect(() => {
    if (!linkedWorkspaceId) return;
    const match = [...wsByKey.entries()].find(([, workspace]) => workspace.id === linkedWorkspaceId);
    if (!match) return;
    const [key, workspace] = match;
    setSelectedNodeKey((current) => current === key ? current : key);
    setFileModalWs((current) => current?.id === workspace.id && current.path === workspace.path ? current : workspace);
  }, [linkedWorkspaceId, wsByKey]);

  const replaceWorkspaceLocation = (workspaceId?: string | null, fileId?: string | null, versionId?: string | null) => {
    const next = new URLSearchParams(urlParams);
    next.set('view', 'workspace');
    if (workspaceId) next.set('workspace', workspaceId); else next.delete('workspace');
    if (fileId) next.set('file', fileId); else next.delete('file');
    if (fileId && versionId) next.set('version', versionId); else next.delete('version');
    setUrlParams(next, { replace: true });
  };

  useEffect(() => {
    setCwd([]); setSearch(''); setSelectedKeys(new Set());
  }, [fileModalWs?.id]);
  useEffect(() => { setSelectedKeys(new Set()); }, [cwd, search]);

  // 无搜索时展示当前层直系子项；搜索时覆盖整个工作空间并保留完整路径。
  const { folderItems, fileItems } = useMemo(() => {
    const allFolderPaths = new Map<string, WorkspaceFolder | null>();
    const addFolderPath = (path: string, rec: WorkspaceFolder | null = null) => {
      if (!path) return;
      if (!allFolderPaths.has(path)) allFolderPaths.set(path, rec);
      else if (rec && !allFolderPaths.get(path)) allFolderPaths.set(path, rec);
    };
    for (const f of folders ?? []) {
      const parts = f.path.split('/');
      for (let i = 1; i <= parts.length; i++) addFolderPath(parts.slice(0, i).join('/'), i === parts.length ? f : null);
    }
    for (const f of files ?? []) {
      const parts = f.path.split('/').slice(0, -1);
      for (let i = 1; i <= parts.length; i++) addFolderPath(parts.slice(0, i).join('/'));
    }
    const cwdPath = cwd.join('/');
    const query = search.trim().toLocaleLowerCase();
    const folderItems = [...allFolderPaths.entries()].flatMap(([path, record]) => {
      const parent = path.split('/').slice(0, -1).join('/');
      if (query ? !path.toLocaleLowerCase().includes(query) : parent !== cwdPath) return [];
      return [{ name: basename(path), path, record }];
    });
    const fileItems = (files ?? []).flatMap((file) => {
      const parent = file.path.split('/').slice(0, -1).join('/');
      if (query ? !file.path.toLocaleLowerCase().includes(query) : parent !== cwdPath) return [];
      return [{ file, name: workspaceDisplayName(file), path: file.path }];
    });
    const compare = (a: { name: string; path: string; record?: WorkspaceFolder | null; file?: WorkspaceFileListItem }, b: typeof a) => {
      if (sortBy === 'time') return new Date(b.file?.updated_at ?? b.record?.updated_at ?? 0).getTime() - new Date(a.file?.updated_at ?? a.record?.updated_at ?? 0).getTime();
      if (sortBy === 'size') return (b.file?.size ?? 0) - (a.file?.size ?? 0) || a.name.localeCompare(b.name);
      if (sortBy === 'type') return fileType(a.path).localeCompare(fileType(b.path)) || a.name.localeCompare(b.name);
      return a.name.localeCompare(b.name);
    };
    folderItems.sort(compare);
    fileItems.sort(compare);
    return { folderItems, fileItems };
  }, [files, folders, cwd, search, sortBy]);

  const resultKeys = useMemo(() => [
    ...folderItems.map((item) => `d:${item.path}`),
    ...fileItems.map((item) => `f:${item.file.id}`),
  ], [folderItems, fileItems]);

  const visibleFolderPath = (path: string) => {
    const related = (files ?? []).find((file) => file.path.startsWith(`${path}/`));
    if (related?.presentation.source_task_title && /(?:^|\/)[0-9a-f-]{36}(?:\/|$)/i.test(path)) {
      return path.replace(/[0-9a-f-]{36}/i, related.presentation.source_task_title);
    }
    return path.replace(/[0-9a-f-]{36}/gi, '任务产物');
  };

  const toggleSelected = (key: string) => setSelectedKeys((current) => {
    const next = new Set(current);
    if (next.has(key)) next.delete(key); else next.add(key);
    return next;
  });

  const pointerInFileArea = (event: { clientX: number; clientY: number }) => {
    const area = fileAreaRef.current;
    if (!area) return null;
    const bounds = area.getBoundingClientRect();
    return { x: event.clientX - bounds.left + area.scrollLeft, y: event.clientY - bounds.top + area.scrollTop, bounds };
  };

  const beginMarqueeSelection = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!selecting || event.button !== 0) return;
    const target = event.target as HTMLElement;
    if (target.closest('[data-workspace-item], button, input, [role="menu"]')) return;
    const point = pointerInFileArea(event);
    const area = fileAreaRef.current;
    if (!point || !area) return;
    const baseSelection = event.ctrlKey || event.metaKey || event.shiftKey ? new Set(selectedKeys) : new Set<string>();
    dragSelectionRef.current = { pointerId: event.pointerId, startX: point.x, startY: point.y, baseSelection };
    setSelectedKeys(baseSelection);
    setMarquee({ left: point.x, top: point.y, width: 0, height: 0 });
    area.setPointerCapture(event.pointerId);
    event.preventDefault();
  };

  const updateMarqueeSelection = (event: React.PointerEvent<HTMLDivElement>) => {
    const drag = dragSelectionRef.current;
    const area = fileAreaRef.current;
    const point = pointerInFileArea(event);
    if (!drag || drag.pointerId !== event.pointerId || !area || !point) return;
    const box = {
      left: Math.min(drag.startX, point.x), top: Math.min(drag.startY, point.y),
      width: Math.abs(point.x - drag.startX), height: Math.abs(point.y - drag.startY),
    };
    const next = new Set(drag.baseSelection);
    area.querySelectorAll<HTMLElement>('[data-workspace-key]').forEach((item) => {
      const rect = item.getBoundingClientRect();
      const itemBox = {
        left: rect.left - point.bounds.left + area.scrollLeft,
        top: rect.top - point.bounds.top + area.scrollTop,
        right: rect.right - point.bounds.left + area.scrollLeft,
        bottom: rect.bottom - point.bounds.top + area.scrollTop,
      };
      if (box.left < itemBox.right && box.left + box.width > itemBox.left && box.top < itemBox.bottom && box.top + box.height > itemBox.top) {
        next.add(item.dataset.workspaceKey!);
      }
    });
    setMarquee(box); setSelectedKeys(next); event.preventDefault();
  };

  const endMarqueeSelection = (event: React.PointerEvent<HTMLDivElement>) => {
    const drag = dragSelectionRef.current;
    const area = fileAreaRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    dragSelectionRef.current = null; setMarquee(null);
    if (area?.hasPointerCapture(event.pointerId)) area.releasePointerCapture(event.pointerId);
    event.preventDefault();
  };

  const { data: trash = [], isLoading: trashLoading } = useQuery<WorkspaceFile[]>({
    queryKey: ['workspace-trash', fileModalWs?.id],
    queryFn: () => workspaces.listTrash(fileModalWs!.id), enabled: !!fileModalWs && trashOpen,
  });
  const { data: auditEvents = [], isLoading: auditLoading } = useQuery<WorkspaceAuditEvent[]>({
    queryKey: ['workspace-audit', fileModalWs?.id],
    queryFn: () => workspaces.listAudit(fileModalWs!.id), enabled: !!fileModalWs && auditOpen,
  });
  const { data: versions = [], isLoading: versionsLoading } = useQuery<WorkspaceFileVersion[]>({
    queryKey: ['workspace-file-versions', versionFile?.id],
    queryFn: () => workspaces.listFileVersions(versionFile!.id), enabled: !!versionFile,
  });

  const uploadQueue = useWorkspaceUploadQueue<WorkspaceFile>({
    upload: (request, options) => workspaces.uploadFile(request.workspaceId, request.file, request.path, {
      ...options,
      targetFileId: request.targetFileId,
      baseVersionId: request.baseVersionId,
      idempotencyKey: request.idempotencyKey,
    }),
    onSuccess: (_file, request) => {
      qc.invalidateQueries({ queryKey: ['workspace-files'] });
      message.success(request.targetFileId ? `${request.file.name} 已作为新版本上传` : `${request.file.name} 已上传`);
    },
    onError: (error, request) => {
      message.error(`${request.file.name}：${workspaceUploadErrorText(error)}`);
    },
  });

  const enqueueSelectedUploads = (selected: File[]) => {
    if (!fileModalWs) return;
    const accepted = selected.filter((file) => {
      if (file.size <= WORKSPACE_MAX_FILE_BYTES) return true;
      message.warning(`${file.name} 超过 5GB 存储上限，未加入上传队列`);
      return false;
    });
    const existingByPath = new Map((files ?? []).map((file) => [file.path, file]));
    const seen = new Set<string>();
    const creates: WorkspaceUploadRequest[] = [];
    const versions: WorkspaceUploadRequest[] = [];
    let duplicateSelections = 0;
    let unavailableVersions = 0;
    for (const file of accepted) {
      const path = [...cwd, file.name].join('/');
      if (seen.has(path)) { duplicateSelections += 1; continue; }
      seen.add(path);
      const existing = existingByPath.get(path);
      if (!existing) {
        creates.push({ workspaceId: fileModalWs.id, path, file });
        continue;
      }
      if (!existing.current_version_id) { unavailableVersions += 1; continue; }
      versions.push({
        workspaceId: fileModalWs.id,
        path,
        file,
        targetFileId: existing.id,
        baseVersionId: existing.current_version_id,
        idempotencyKey: crypto.randomUUID(),
      });
    }
    if (creates.length) uploadQueue.enqueue(creates);
    if (duplicateSelections) message.warning(`选择中有 ${duplicateSelections} 个重名文件，已只保留每个名称的第一个`);
    if (unavailableVersions) message.error(`${unavailableVersions} 个同名文件缺少当前版本，未上传；请刷新后重试`);
    if (!versions.length) return;
    Modal.confirm({
      title: `将 ${versions.length} 个同名文件作为新版本上传？`,
      content: (
        <div>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
            同名文件不会自动覆盖。确认后将保留原文件地址和历史版本，并创建可恢复的新版本。
          </Typography.Paragraph>
          <List size="small" dataSource={versions} renderItem={(item) => <List.Item>{item.path}</List.Item>} />
        </div>
      ),
      okText: '作为新版本上传',
      cancelText: '取消同名文件',
      onOk: () => uploadQueue.enqueue(versions),
    });
  };

  /** 从鉴权下载端点取得原始二进制，兼容 OSS 与历史 Base64 文件。 */
  const downloadBinary = async (f: WorkspaceFile) => {
    try {
      const meta = (f.metadata ?? {}) as { mime?: string; name?: string };
      const a = document.createElement('a');
      const ticket = await workspaces.getFileDownloadTicket(f.id);
      let target = ticket.url;
      try {
        const probe = await fetch(ticket.url, {
          headers: { ...ticket.headers, Range: 'bytes=0-0' },
        });
        if (!probe.ok && ticket.fallback_url) target = ticket.fallback_url;
      } catch {
        if (ticket.fallback_url) target = ticket.fallback_url;
      }
      a.href = target;
      a.download = ticket.filename || meta.name || basename(f.path);
      a.target = '_blank';
      a.rel = 'noopener';
      document.body.appendChild(a);
      a.click();
      a.remove();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        try {
          const meta = (f.metadata ?? {}) as { name?: string };
          const blob = await workspaces.downloadFile(f.id);
          const url = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url;
          a.download = meta.name || basename(f.path);
          a.click();
          window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
          return;
        } catch { /* report the original compatibility failure below */ }
      }
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
    mutationFn: (request: { id: string; baseVersionId: string; idempotencyKey: string }) => workspaces.deleteFile(request.id, {
      base_version_id: request.baseVersionId,
      idempotency_key: request.idempotencyKey,
    }),
    onSuccess: (_data, request) => {
      qc.invalidateQueries({ queryKey: ['workspace-files'] });
      setActiveFileId((cur) => (cur === request.id ? null : cur));
      if (activeFileId === request.id) {
        setActiveFileVersionId(null);
        replaceWorkspaceLocation(fileModalWs?.id);
      }
      message.success('文件已移至回收站');
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
      message.success('文件夹及其内容已移至回收站');
    },
    onError: () => message.error('删除失败'),
  });

  const delFolderPath = useMutation({
    mutationFn: (path: string) => {
      if (!fileModalWs) return Promise.reject(new Error('no ws'));
      return workspaces.deleteFolderPath(fileModalWs.id, path);
    },
    onSuccess: (result, path) => {
      qc.invalidateQueries({ queryKey: ['workspace-folders'] });
      qc.invalidateQueries({ queryKey: ['workspace-files'] });
      if (cwd.join('/') === path) setCwd((current) => current.slice(0, -1));
      message.success(`文件夹已移至回收站（${result.files} 个文件，${result.folders} 个显式文件夹）`);
    },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '删除文件夹失败'),
  });

  const bulkDelete = useMutation({
    mutationFn: () => {
      if (!fileModalWs) return Promise.reject(new Error('no ws'));
      return workspaces.bulkDeleteItems(fileModalWs.id, {
        file_ids: [...selectedKeys].filter((key) => key.startsWith('f:')).map((key) => key.slice(2)),
        folder_paths: [...selectedKeys].filter((key) => key.startsWith('d:')).map((key) => key.slice(2)),
      });
    },
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ['workspace-folders'] });
      qc.invalidateQueries({ queryKey: ['workspace-files'] });
      setSelectedKeys(new Set());
      message.success(`已移动 ${result.deleted_files} 个文件、${result.deleted_folders} 个显式文件夹到回收站`);
    },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '批量删除失败'),
  });

  const restoreTrash = useMutation({
    mutationFn: (file: WorkspaceFile) => {
      if (!file.current_version_id) {
        return Promise.reject(new Error('回收站文件版本信息已过期，请刷新后重试'));
      }
      const fingerprint = `${file.id}\u0000${file.current_version_id}`;
      let idempotencyKey = trashRestoreAttemptRef.current.get(fingerprint);
      if (!idempotencyKey) {
        idempotencyKey = crypto.randomUUID();
        trashRestoreAttemptRef.current.set(fingerprint, idempotencyKey);
      }
      return workspaces.restoreTrash(fileModalWs!.id, file.id, {
        base_version_id: file.current_version_id,
        idempotency_key: idempotencyKey,
      });
    },
    onSuccess: (_result, file) => {
      if (file.current_version_id) {
        trashRestoreAttemptRef.current.delete(`${file.id}\u0000${file.current_version_id}`);
      }
      qc.invalidateQueries({ queryKey: ['workspace-trash'] });
      qc.invalidateQueries({ queryKey: ['workspace-files'] });
      message.success('文件已从回收站恢复');
    },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '恢复失败'),
  });

  const restoreVersion = useMutation({
    mutationFn: (versionId: string) => {
      const fingerprint = `${versionFile!.id}\u0000${versionFile?.current_version_id || ''}\u0000${versionId}`;
      if (restoreAttemptRef.current?.fingerprint !== fingerprint) {
        restoreAttemptRef.current = { fingerprint, key: crypto.randomUUID() };
      }
      if (!versionFile?.current_version_id) {
        return Promise.reject(new Error('当前文件版本信息已过期，请刷新后重试'));
      }
      return workspaces.restoreFileVersion(versionFile.id, versionId, {
        base_version_id: versionFile.current_version_id,
        idempotency_key: restoreAttemptRef.current.key,
      });
    },
    onSuccess: () => {
      restoreAttemptRef.current = null;
      qc.invalidateQueries({ queryKey: ['workspace-file-versions'] });
      qc.invalidateQueries({ queryKey: ['workspace-files'] });
      message.success('已恢复为新的当前版本');
    },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '版本恢复失败'),
  });

  const openWs = (ws: { id: string; name: string; path: string }) => {
    setFileModalWs(ws); setCwd([]); setSearch(''); setSelectedKeys(new Set()); setActiveFileId(null); setActiveFileVersionId(null);
    replaceWorkspaceLocation(ws.id);
  };

  /** 列表只含摘要；打开时按需拉取单文件正文。 */
  const openFile = (item: WorkspaceFileListItem) => {
    // 统一抽屉按稳定 file ID 自行加载；不再为管理员端维护另一套预览状态。
    setActiveFileId(item.id);
    setActiveFileVersionId(null);
    replaceWorkspaceLocation(item.workspace_id || fileModalWs?.id, item.id);
  };

  const downloadListFile = async (item: WorkspaceFileListItem) => {
    try {
      const file = await workspaces.getFile(item.id);
      if (isBinary(file)) await downloadBinary(file); else downloadText(file);
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : '下载失败');
    }
  };

  const copyFileAddress = async (item: WorkspaceFileListItem) => {
    const url = workspaceInternalUrl({ ...item, workspace_name: item.workspace_name || fileModalWs?.name }, window.location.origin);
    try {
      await navigator.clipboard.writeText(url);
      message.success('文件地址已复制；有权限的成员可打开');
    } catch {
      Modal.info({
        title: '复制文件地址',
        content: <Input readOnly value={url} onFocus={(event) => event.currentTarget.select()} />,
        okText: '关闭',
      });
    }
  };

  const copyVersionAddress = async (versionId: string) => {
    if (!versionFile) return;
    const url = workspaceInternalUrl({ ...versionFile, workspace_name: versionFile.workspace_name || fileModalWs?.name }, window.location.origin, versionId);
    try {
      await navigator.clipboard.writeText(url);
      message.success('历史版本地址已复制');
    } catch {
      Modal.info({ title: '复制历史版本地址', content: <Input readOnly value={url} onFocus={(event) => event.currentTarget.select()} />, okText: '关闭' });
    }
  };

  const submitFolder = () => {
    const name = folderName.trim();
    if (!name || name.includes('/')) { message.warning('请输入有效文件夹名（不含 /）'); return; }
    createFolder.mutate(name);
  };


  // 删除确认：界面正中 ConfirmModal（不再用悬浮 Popconfirm）。
  const [confirm, setConfirm] = useState<{
    kind: 'folder' | 'folderPath' | 'file' | 'bulk'; id: string; title: string; desc?: string;
    baseVersionId?: string; idempotencyKey?: string;
  } | null>(null);
  const confirmLoading = confirm?.kind === 'folder' ? delFolder.isPending
    : confirm?.kind === 'folderPath' ? delFolderPath.isPending
      : confirm?.kind === 'file' ? delFile.isPending : confirm?.kind === 'bulk' ? bulkDelete.isPending : false;
  const confirmOk = () => {
    if (!confirm) return;
    if (confirm.kind === 'folder') delFolder.mutate(confirm.id);
    else if (confirm.kind === 'folderPath') delFolderPath.mutate(confirm.id);
    else if (confirm.kind === 'file') {
      if (!confirm.baseVersionId || !confirm.idempotencyKey) {
        message.error('当前文件版本信息已过期，请刷新后重试');
        void qc.invalidateQueries({ queryKey: ['workspace-files'] });
        setConfirm(null);
        return;
      }
      delFile.mutate({
        id: confirm.id,
        baseVersionId: confirm.baseVersionId,
        idempotencyKey: confirm.idempotencyKey,
      });
    }
    else bulkDelete.mutate();
    setConfirm(null);
  };

  return (
    <FinderShell style={{ height: 'calc(100vh - 64px)' }}>
      <TitleBar
        icon={<FolderOutlined />}
        title="工作空间"
        titleExtra={<OrgSelect value={orgId} onChange={(v) => {
          setOrgId(v); setSelectedNodeKey(null); setFileModalWs(null); setActiveFileId(null); setActiveFileVersionId(null);
          replaceWorkspaceLocation(null);
        }} />}
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
                    <Input
                      allowClear prefix={<SearchOutlined />} placeholder="搜索整个工作空间"
                      value={search} onChange={(event) => setSearch(event.target.value)}
                      style={{ width: 190, height: 28, fontSize: FS.aux }}
                    />
                    <Select
                      size="small" value={sortBy} onChange={setSortBy} style={{ width: 94 }}
                      options={[
                        { value: 'name', label: '按名称' }, { value: 'time', label: '按时间' },
                        { value: 'type', label: '按类型' }, { value: 'size', label: '按大小' },
                      ]}
                    />
                    <ToolButton
                      icon={viewMode === 'grid' ? <UnorderedListOutlined /> : <AppstoreOutlined />}
                      onClick={() => setViewMode((mode) => mode === 'grid' ? 'list' : 'grid')}
                    />
                    <ToolButton
                      icon={<CheckSquareOutlined />}
                      onClick={() => {
                        setSelecting((value) => !value); setSelectedKeys(new Set());
                        setMarquee(null); dragSelectionRef.current = null;
                      }}
                    >{selecting ? '退出多选' : '多选'}</ToolButton>
                    {selecting && (
                      <>
                        <ToolButton onClick={() => setSelectedKeys(new Set(resultKeys))}>全选结果</ToolButton>
                        <ToolButton
                          danger icon={<DeleteOutlined />} disabled={!selectedKeys.size}
                          onClick={() => setConfirm({
                            kind: 'bulk', id: '', title: `将选中的 ${selectedKeys.size} 项移至回收站？`,
                            desc: '文件夹会连同全部子文件夹和文件一起移至回收站。',
                          })}
                        >批量删除</ToolButton>
                      </>
                    )}
                    <ToolButton icon={<RestOutlined />} onClick={() => setTrashOpen(true)}>回收站</ToolButton>
                    <ToolButton icon={<AuditOutlined />} onClick={() => setAuditOpen(true)}>审计</ToolButton>
                    {cwd.length > 0 && (
                      <ToolButton
                        danger icon={<DeleteOutlined />}
                        onClick={() => setConfirm({
                          kind: 'folderPath', id: cwd.join('/'), title: `删除“${cwd[cwd.length - 1]}”文件夹？`,
                          desc: '将一并移动当前文件夹、全部子文件夹和其中所有文件到回收站。',
                        })}
                      >删除当前文件夹</ToolButton>
                    )}
                    <ToolButton icon={<FolderAddOutlined style={{ fontSize: 13 }} />} onClick={() => { setFolderName(''); setFolderModalOpen(true); }}>
                      新建文件夹
                    </ToolButton>
                    <WorkspaceUploadPicker
                      onLimitExceeded={(count) => message.warning(`一次最多上传 5 个文件；已选择 ${count} 个，本次只加入前 5 个`)}
                      onSelect={enqueueSelectedUploads}
                    >
                      <ToolButton icon={<UploadOutlined style={{ fontSize: 13 }} />}>
                        上传文件（可多选）
                      </ToolButton>
                    </WorkspaceUploadPicker>
                    <Typography.Text
                      type="secondary"
                      title="支持 Word、Excel、PPT、PDF、Markdown 等常用文件；100MB 内可自动 AI 解析，较大文件仍可存储和下载"
                      style={{ fontSize: 11, whiteSpace: 'nowrap' }}
                    >
                      单次最多 5 个 · 单文件最大 5GB · AI 解析上限 100MB
                    </Typography.Text>
                    <WorkspaceUploadQueueStatus
                      items={uploadQueue.items}
                      activeCount={uploadQueue.activeCount}
                      completedCount={uploadQueue.completedCount}
                      failedCount={uploadQueue.failedCount}
                      overallProgress={uploadQueue.overallProgress}
                      onClearFinished={uploadQueue.clearFinished}
                    />
                  </>
                }
              />

              {/* 文件网格 / 列表；多选时支持鼠标拖框批量选中。 */}
              <div
                ref={fileAreaRef}
                style={{
                  flex: 1, overflowY: 'auto', padding: '18px 20px', position: 'relative',
                  userSelect: selecting ? 'none' : undefined, touchAction: selecting ? 'none' : undefined,
                }}
                className="wb-scroll-hide"
                onPointerDown={beginMarqueeSelection}
                onPointerMove={updateMarqueeSelection}
                onPointerUp={endMarqueeSelection}
                onPointerCancel={endMarqueeSelection}
              >
                {selecting && marquee && <div aria-hidden style={marqueeStyle(marquee)} />}
                {filesLoading ? (
                  <FinderLoading />
                ) : (folderItems.length === 0 && fileItems.length === 0) ? (
                  <div style={{ textAlign: 'center', color: WB.textAux, fontSize: FS.body, marginTop: 48 }}>
                    此处暂无文件夹 / 文件
                  </div>
                ) : (
                  <div style={viewMode === 'grid' ? { display: 'flex', flexWrap: 'wrap', gap: 4 } : { display: 'flex', flexDirection: 'column', gap: 2 }}>
                    {folderItems.map((it) => {
                      const key = `d:${it.path}`;
                      const isActive = hovered === key || focused === key;
                      const showActions = viewMode === 'list' || isActive;
                      const selected = selectedKeys.has(key);
                      return (
                        <div
                          key={key}
                          data-workspace-item data-workspace-key={key}
                          role="button" tabIndex={0} aria-label={`打开文件夹 ${it.name}`}
                          onMouseEnter={() => setHovered(key)} onMouseLeave={() => setHovered(null)}
                          onFocus={() => setFocused(key)}
                          onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setFocused(null); }}
                          onClick={() => selecting ? toggleSelected(key) : (setCwd(it.path.split('/')), setSearch(''))}
                          onKeyDown={(event) => {
                            if (event.key !== 'Enter' && event.key !== ' ') return;
                            event.preventDefault();
                            selecting ? toggleSelected(key) : (setCwd(it.path.split('/')), setSearch(''));
                          }}
                          style={viewMode === 'grid'
                            ? { ...iconCardStyle(isActive), background: selected ? WB.activeBg : (isActive ? WB.hover : 'transparent') }
                            : listRowStyle(selected || isActive)}
                        >
                          {selecting && <Checkbox checked={selected} onClick={(event) => event.stopPropagation()} onChange={() => toggleSelected(key)} style={viewMode === 'grid' ? { position: 'absolute', top: 5, left: 6 } : undefined} />}
                          <div style={viewMode === 'grid' ? iconInnerStyle : { display: 'contents' }}>
                            <FolderOutlined style={{ fontSize: viewMode === 'grid' ? 42 : 22, color: WB.macFolder }} />
                            <div style={viewMode === 'grid' ? iconNameStyle : listNameStyle} title={visibleFolderPath(it.path)}>{visibleFolderPath(it.name)}</div>
                            {viewMode === 'grid' && !!search.trim() && <div style={searchPathStyle} title={visibleFolderPath(it.path)}>{visibleFolderPath(it.path)}</div>}
                            {viewMode === 'list' && <><span style={listMetaStyle}>文件夹</span><span style={listMetaStyle}>{it.record?.updated_at ? new Date(it.record.updated_at).toLocaleString() : '路径推导'}</span><span style={listPathStyle}>{visibleFolderPath(it.path)}</span></>}
                            {!selecting && (
                              <Dropdown
                                trigger={['click']} placement="bottomRight"
                                menu={{
                                  items: [{ key: 'delete', label: '移至回收站', icon: <DeleteOutlined />, danger: true }],
                                  onClick: ({ domEvent }) => {
                                    domEvent.stopPropagation();
                                    setConfirm({
                                      kind: it.record ? 'folder' : 'folderPath', id: it.record ? it.record.id : it.path,
                                      title: '将该文件夹移至回收站？', desc: '将一并处理其下所有子文件夹与文件。',
                                    });
                                  },
                                }}
                              >
                                <button aria-label={`${it.name} 的更多操作`} style={moreActionBtnStyle(viewMode, showActions)} onClick={(event) => event.stopPropagation()}><MoreOutlined /></button>
                              </Dropdown>
                            )}
                          </div>
                        </div>
                      );
                    })}
                    {fileItems.map((it) => {
                      const key = `f:${it.file.id}`;
                      const isActive = hovered === key || focused === key;
                      const showActions = viewMode === 'list' || isActive;
                      const selected = selectedKeys.has(key);
                      return (
                        <div
                          key={key}
                          data-workspace-item data-workspace-key={key}
                          role="button" tabIndex={0} aria-label={`打开文件 ${it.name}`}
                          onMouseEnter={() => setHovered(key)} onMouseLeave={() => setHovered(null)}
                          onFocus={() => setFocused(key)}
                          onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setFocused(null); }}
                          onClick={() => selecting ? toggleSelected(key) : void openFile(it.file)}
                          onKeyDown={(event) => {
                            if (event.key !== 'Enter' && event.key !== ' ') return;
                            event.preventDefault(); selecting ? toggleSelected(key) : void openFile(it.file);
                          }}
                          style={viewMode === 'grid'
                            ? { ...iconCardStyle(isActive), background: selected ? WB.activeBg : (isActive ? WB.hover : 'transparent') }
                            : listRowStyle(selected || isActive)}
                        >
                          {selecting && <Checkbox checked={selected} onClick={(event) => event.stopPropagation()} onChange={() => toggleSelected(key)} style={viewMode === 'grid' ? { position: 'absolute', top: 5, left: 6 } : undefined} />}
                          <div style={viewMode === 'grid' ? iconInnerStyle : { display: 'contents' }}>
                            <FileTextOutlined style={{ fontSize: viewMode === 'grid' ? 42 : 22, color: WB.macFile }} />
                            <div style={viewMode === 'grid' ? iconNameStyle : listNameStyle} title={it.path}>{it.name}</div>
                            {viewMode === 'grid' && !!search.trim() && <div style={searchPathStyle} title={workspaceVisiblePath(it.file)}>{workspaceVisiblePath(it.file)}</div>}
                            {viewMode === 'grid'
                              ? <span style={{ fontSize: 10, color: WB.textMicro, marginTop: 1 }}>{formatBytes(it.file.size)}</span>
                              : <><span style={listMetaStyle}>{fileType(it.path)} · {formatBytes(it.file.size)}</span><span style={listMetaStyle}>{new Date(it.file.updated_at).toLocaleString()}</span><span style={listMetaStyle}>{PARSE_LABEL[it.file.parse_status] ?? it.file.parse_status}</span><span style={listPathStyle}>{workspaceVisiblePath(it.file)}</span></>}
                            {!selecting && (
                              <Dropdown
                                trigger={['click']} placement="bottomRight"
                                menu={{
                                  items: [
                                    { key: 'open', label: '查看文件', icon: <EyeOutlined /> },
                                    { key: 'copy-address', label: '复制文件地址', icon: <LinkOutlined /> },
                                    { key: 'download', label: '下载原文件', icon: <DownloadOutlined /> },
                                    { key: 'versions', label: '版本历史', icon: <HistoryOutlined /> },
                                    { key: 'delete', label: '移至回收站', icon: <DeleteOutlined />, danger: true },
                                  ],
                                  onClick: ({ key: action, domEvent }) => {
                                    domEvent.stopPropagation();
                                    if (action === 'open') void openFile(it.file);
                                    else if (action === 'copy-address') void copyFileAddress(it.file);
                                    else if (action === 'download') void downloadListFile(it.file);
                                    else if (action === 'versions') setVersionFile(it.file);
                                    else if (!it.file.current_version_id) {
                                      message.error('当前文件版本信息不可用，请刷新后重试');
                                      void qc.invalidateQueries({ queryKey: ['workspace-files'] });
                                    } else setConfirm({
                                      kind: 'file', id: it.file.id,
                                      baseVersionId: it.file.current_version_id,
                                      idempotencyKey: crypto.randomUUID(),
                                      title: '将该文件移至回收站？',
                                      desc: '文件将在回收站保留 30 天，可恢复。',
                                    });
                                  },
                                }}
                              >
                                <button aria-label={`${it.name} 的更多操作`} style={moreActionBtnStyle(viewMode, showActions)} onClick={(event) => event.stopPropagation()}><MoreOutlined /></button>
                              </Dropdown>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
                {folderItems.length === 0 && fileItems.length === 0 && !filesLoading && (
                  <Typography.Text style={{ display: 'block', marginTop: 16, fontSize: FS.micro, color: WB.textMicro, textAlign: 'center' }}>
                    点击文件夹进入 · 点击文件查看 · 同名文件需确认后才会保存为新版本
                  </Typography.Text>
                )}
              </div>
            </>
          )}
        </section>
      </div>

      {/* 管理员与员工共用同一个稳定 file ID 抽屉，编辑、版本与预览行为保持一致。 */}
      <BrowserDrawer
        open={!!activeFileId}
        initialFileId={activeFileId}
        initialVersionId={activeFileVersionId}
        onClose={() => {
          setActiveFileId(null);
          setActiveFileVersionId(null);
          replaceWorkspaceLocation(fileModalWs?.id);
        }}
        resolveHref={async (href): Promise<Source> => {
          if (/^https?:\/\//i.test(href)) return classifyUrl(href);
          const exact = (files ?? []).filter((file) => file.path === href || file.canonical_path === href);
          const suffix = exact.length ? [] : (files ?? []).filter((file) => file.path.endsWith(`/${href}`));
          const matches = exact.length ? exact : suffix;
          if (matches.length !== 1) {
            return { kind: 'unsupported', href, note: matches.length ? '存在多个同名文件，请使用复制的内部文件地址' : '当前工作空间未找到该文件' };
          }
          return classifyFile(await workspaces.getFile(matches[0].id));
        }}
        loadFileById={workspaces.getFile}
        loadFileVersionById={workspaces.getFileVersion}
        fallbackCapabilities={{ read: true, create: true, update: true, delete: true }}
        fallbackWorkspaceName={fileModalWs?.name}
        saveTextFile={(fileId, data) => workspaces.updateFile(fileId, data)}
        onReparse={async (fileId) => {
          await workspaces.reparseFile(fileId);
          await qc.invalidateQueries({ queryKey: ['workspace-files'] });
        }}
        loadOriginalPreview={workspaces.getFileOriginalPreview}
        loadOriginalPreviewSource={workspaces.getFileOriginalPreviewSource}
        loadPdfPreviewInfo={workspaces.getFilePdfPreviewInfo}
        loadPdfPreviewPage={workspaces.getFilePdfPreviewPage}
        loadOriginalFile={workspaces.downloadFile}
        loadDownloadTicket={workspaces.getFileDownloadTicket}
        loadPreviewSession={workspaces.createFilePreviewSession}
        refreshPreviewSession={workspaces.refreshFilePreviewSession}
        startFallbackPreview={workspaces.startFileFallbackPreview}
        getFallbackPreview={workspaces.getFileFallbackPreview}
        startSpreadsheetPreview={workspaces.startFileSpreadsheetPreview}
        getSpreadsheetPreview={workspaces.getFileSpreadsheetPreview}
        getSpreadsheetPage={workspaces.getFileSpreadsheetPage}
        createEditSession={workspaces.createFileEditSession}
        refreshEditSession={workspaces.refreshFileEditSession}
        closeEditSession={workspaces.closeFileEditSession}
        getEditSessionStatus={workspaces.getFileEditSessionStatus}
        listFileVersions={workspaces.listFileVersions}
        restoreFileVersion={workspaces.restoreFileVersion}
        onFileChanged={() => {
          void qc.invalidateQueries({ queryKey: ['workspace-files'] });
          void qc.invalidateQueries({ queryKey: ['workspace-file-versions'] });
        }}
      />

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

      <Modal title="回收站（保留 30 天）" open={trashOpen} footer={null} onCancel={() => setTrashOpen(false)} width={720}>
        <List
          loading={trashLoading} dataSource={trash} locale={{ emptyText: '回收站为空' }}
          renderItem={(file) => (
            <List.Item actions={[<a key="restore" onClick={() => restoreTrash.mutate(file)}>恢复</a>]}>
              <List.Item.Meta title={workspaceDisplayName(file)} description={`${workspaceVisiblePath(file)} · ${formatBytes(file.size)}`} />
            </List.Item>
          )}
        />
      </Modal>

      <Modal
        title={`版本历史${versionFile ? ` · ${workspaceDisplayName(versionFile)}` : ''}`}
        open={!!versionFile} footer={null} onCancel={() => setVersionFile(null)} width={720}
      >
        <List
          loading={versionsLoading} dataSource={versions} locale={{ emptyText: '暂无版本' }}
          renderItem={(version, index) => (
            <List.Item actions={[
              <a key="copy" onClick={() => { void copyVersionAddress(version.id); }}>复制版本地址</a>,
              ...(index === 0 ? [] : [<a key="restore" onClick={() => restoreVersion.mutate(version.id)}>恢复此版本</a>]),
            ]}>
              <List.Item.Meta
                title={`版本 ${version.version_no}${index === 0 ? '（当前）' : ''}`}
                description={`${formatBytes(version.size)} · ${new Date(version.created_at).toLocaleString()} · ${PARSE_LABEL[version.parse_status] ?? version.parse_status}`}
              />
            </List.Item>
          )}
        />
      </Modal>

      <Modal title="工作空间审计" open={auditOpen} footer={null} onCancel={() => setAuditOpen(false)} width={760}>
        <List
          loading={auditLoading} dataSource={auditEvents} locale={{ emptyText: '暂无审计事件' }}
          renderItem={(event) => (
            <List.Item>
              <List.Item.Meta title={auditTitle(event)} description={<div><div>{auditSummary(event)}</div><details style={{ marginTop: 6, fontSize: 11 }}><summary style={{ cursor: 'pointer' }}>技术详情</summary><pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{JSON.stringify({ action: event.action, metadata: event.metadata }, null, 2)}</pre></details></div>} />
            </List.Item>
          )}
        />
      </Modal>
    </FinderShell>
  );
}

const iconCardStyle = (active: boolean): CSSProperties => ({
  width: 108, padding: '10px 6px 8px', borderRadius: 8, cursor: 'pointer',
  display: 'flex', alignItems: 'flex-start', justifyContent: 'center',
  border: '1px solid transparent', transition: 'background .12s',
  background: active ? WB.hover : 'transparent', position: 'relative',
});

const iconInnerStyle: CSSProperties = {
  position: 'relative', display: 'flex', flexDirection: 'column', alignItems: 'center', width: 92,
};

const iconNameStyle: CSSProperties = {
  marginTop: 6, fontSize: FS.aux, color: WB.text, textAlign: 'center',
  overflow: 'hidden', textOverflow: 'ellipsis', display: '-webkit-box',
  WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', width: '100%', lineHeight: 1.3,
};

const searchPathStyle: CSSProperties = {
  ...iconNameStyle, fontSize: 9, color: WB.textMicro, marginTop: 2,
};

const listRowStyle = (active: boolean): CSSProperties => ({
  display: 'grid', gridTemplateColumns: '24px minmax(180px, 1.4fr) 120px 150px 110px minmax(160px, 1fr) auto',
  alignItems: 'center', gap: 10, minHeight: 40, padding: '5px 8px', borderRadius: 6,
  background: active ? WB.hover : 'transparent', cursor: 'pointer', fontSize: FS.aux,
});

const listNameStyle: CSSProperties = {
  minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: WB.text,
};

const listMetaStyle: CSSProperties = {
  color: WB.textAux, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
};

const listPathStyle: CSSProperties = {
  ...listMetaStyle, color: WB.textMicro, direction: 'rtl', textAlign: 'left',
};

const moreActionBtnStyle = (viewMode: 'grid' | 'list', visible: boolean): CSSProperties => ({
  width: 24, height: 24, borderRadius: 6, border: 'none', cursor: 'pointer',
  display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11,
  background: 'rgba(255,255,255,0.9)', boxShadow: '0 1px 3px rgba(0,0,0,0.18)',
  color: WB.text, opacity: visible ? 1 : 0, pointerEvents: visible ? 'auto' : 'none',
  transition: 'opacity .12s ease, background .12s ease',
  ...(viewMode === 'grid' ? { position: 'absolute', top: -6, right: -6, zIndex: 1 } : {}),
});

const marqueeStyle = (box: { left: number; top: number; width: number; height: number }): CSSProperties => ({
  position: 'absolute', left: box.left, top: box.top, width: box.width, height: box.height,
  zIndex: 2, boxSizing: 'border-box', border: `1px solid ${WB.primary}`, borderRadius: 4,
  background: 'rgba(99, 102, 241, 0.12)', pointerEvents: 'none',
});
